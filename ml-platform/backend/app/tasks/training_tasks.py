"""Celery entrypoint for durable training execution."""

import uuid

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
