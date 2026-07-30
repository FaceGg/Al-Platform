"""Celery entrypoint for durable spot-weld quality execution."""

import threading
import uuid
from collections.abc import Callable

from app.database import SessionLocal
from app.services.spot_weld_quality import execute_quality_run
from app.tasks.celery_app import celery_app


def _execute_task(run_id: str, *, worker_id: str, task_id: str) -> dict:
    with SessionLocal() as db:
        return execute_quality_run(
            db, run_id, worker_id=worker_id, task_id=task_id,
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


class LocalQualityDispatcher:
    """Run quality jobs in a background thread when local Celery is disabled."""

    def __init__(self, execute: Callable[..., dict] = _execute_task):
        self.execute = execute
        self._threads: dict[str, threading.Thread] = {}

    def enqueue(self, run_id: str) -> str:
        task_id = f"local:{uuid.uuid4()}"
        thread = threading.Thread(
            target=self.execute,
            args=(str(run_id),),
            kwargs={"worker_id": "local", "task_id": task_id},
            daemon=True,
        )
        self._threads[task_id] = thread
        thread.start()
        return task_id
