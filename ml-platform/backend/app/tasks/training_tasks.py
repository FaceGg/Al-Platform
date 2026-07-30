"""Celery and local background tasks for training execution."""

import threading
import uuid
from collections.abc import Callable

from app.services.training_execution import execute_training_job
from app.services.automl_execution import execute_automl_job
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, name="ml_platform.execute_training")
def execute_training_task(self, job_id: str):
    outcome = execute_training_job(
        uuid.UUID(job_id),
        worker_id=self.request.hostname or "worker",
        task_id=self.request.id or "unknown",
    )
    return {
        "job_id": outcome.job_id,
        "status": outcome.status,
        "error_code": outcome.error_code,
    }


@celery_app.task(bind=True, name="ml_platform.execute_automl")
def execute_automl_task(self, job_id: str):
    from app.services.automl_execution import AutoMLDependencies

    outcome = execute_automl_job(
        uuid.UUID(job_id),
        dependencies=AutoMLDependencies(
            worker_id=self.request.hostname or "worker",
            task_id=self.request.id or "unknown",
        ),
    )
    return {
        "job_id": outcome.job_id,
        "status": outcome.status,
        "best_candidate": outcome.best_candidate,
        "error_code": outcome.error_code,
    }


def execute_local_training_task(job_id: str, task_id: str):
    return execute_training_job(job_id, worker_id="local", task_id=task_id)


def execute_local_automl_task(job_id: str, task_id: str):
    from app.services.automl_execution import AutoMLDependencies

    return execute_automl_job(
        job_id,
        dependencies=AutoMLDependencies(worker_id="local", task_id=task_id),
    )


class LocalTrainingDispatcher:
    """Run training and AutoML jobs in background threads for local mode."""

    def __init__(self, execute: Callable[[str, str], object]):
        self.execute = execute
        self._pending: dict[str, str] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def enqueue(self, job_id) -> str:
        task_id = f"local:{uuid.uuid4()}"
        with self._lock:
            self._pending[task_id] = str(job_id)
        return task_id

    def start(self, task_id: str) -> None:
        with self._lock:
            job_id = self._pending.pop(task_id)
        thread = threading.Thread(
            target=self._execute,
            args=(job_id, task_id),
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

    def _execute(self, job_id: str, task_id: str) -> None:
        try:
            self.execute(job_id, task_id)
        finally:
            with self._lock:
                self._threads.pop(task_id, None)

    def cancel(self, _task_id: str) -> None:
        return None
