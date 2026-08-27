"""Celery entrypoint for durable spot-weld quality execution."""

import inspect
import threading
import uuid
from collections.abc import Callable

from app.database import SessionLocal
from app.services.spot_weld_quality import execute_quality_run
from app.tasks.celery_app import celery_app


def _execute_task(
    run_id: str,
    *,
    worker_id: str,
    task_id: str,
    cancellation_requested: Callable[[], bool] | None = None,
) -> dict:
    with SessionLocal() as db:
        return execute_quality_run(
            db,
            run_id,
            worker_id=worker_id,
            task_id=task_id,
            cancellation_requested=cancellation_requested,
        ).to_dict()


@celery_app.task(bind=True, name="ml_platform.execute_spot_weld_quality")
def execute_spot_weld_quality_task(self, run_id: str):
    return _execute_task(
        run_id,
        worker_id=self.request.hostname or "worker",
        task_id=self.request.id or "unknown",
    )


class CeleryQualityDispatcher:
    def __init__(self, task=execute_spot_weld_quality_task):
        self.task = task

    def enqueue(self, run_id: str) -> str:
        result = self.task.delay(str(run_id))
        return str(result.id)

    def cancel(self, task_id: str) -> None:
        from celery.result import AsyncResult

        AsyncResult(task_id, app=self.task.app).revoke(terminate=True, signal="SIGTERM")


class LocalQualityDispatcher:
    """Run quality jobs in a background thread when local Celery is disabled."""

    def __init__(self, execute: Callable[..., dict] = _execute_task):
        self.execute = execute
        self._pending: dict[str, str] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()
        self._supports_cancellation = "cancellation_requested" in inspect.signature(execute).parameters

    def enqueue(self, run_id: str) -> str:
        task_id = f"local:{uuid.uuid4()}"
        with self._lock:
            self._pending[task_id] = str(run_id)
        return task_id

    def start(self, task_id: str) -> None:
        with self._lock:
            run_id = self._pending.pop(task_id, None)
            if task_id in self._cancelled:
                self._cancelled.discard(task_id)
                return
        if run_id is None:
            return
        thread = threading.Thread(
            target=self._execute,
            args=(run_id, task_id),
            daemon=True,
        )
        with self._lock:
            self._threads[task_id] = thread
        try:
            thread.start()
        except Exception:
            with self._lock:
                self._threads.pop(task_id, None)
            raise

    def cancel(self, task_id: str) -> None:
        with self._lock:
            is_active = task_id in self._pending or task_id in self._threads
            self._pending.pop(task_id, None)
            if is_active:
                self._cancelled.add(task_id)

    def _execute(self, run_id: str, task_id: str) -> None:
        try:
            kwargs = {"worker_id": "local", "task_id": task_id}
            if self._supports_cancellation:
                kwargs["cancellation_requested"] = lambda: self._is_cancelled(task_id)
            self.execute(run_id, **kwargs)
        finally:
            with self._lock:
                self._threads.pop(task_id, None)
                self._cancelled.discard(task_id)

    def _is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._cancelled
