"""Celery application configuration."""

from celery import Celery

from app.config import settings


celery_app = Celery(
    "ml_platform",
    include=["app.tasks.workflow_tasks", "app.tasks.training_tasks"],
    broker=(settings.celery_broker_url.get_secret_value() if settings.celery_broker_url else None),
    backend=(settings.celery_result_backend.get_secret_value() if settings.celery_result_backend else None),
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=settings.task_soft_timeout_seconds,
    task_time_limit=settings.task_hard_timeout_seconds,
    beat_schedule={
        "pipeline-scheduler-tick": {
            "task": "ml_platform.scheduler_tick",
            "schedule": 60.0,
        },
        "pipeline-scheduler-recovery": {
            "task": "ml_platform.recover_pipeline_schedules",
            "schedule": 60.0,
        },
        "inference-deployment-reconciliation": {
            "task": "ml_platform.reconcile_inference_deployments",
            "schedule": 60.0,
        },
    },
)

# Register tasks for CLI/import smoke checks as well as worker include discovery.
from app.tasks import training_tasks  # noqa: E402,F401
from app.tasks import scheduler_tasks  # noqa: E402,F401
from app.tasks import inference_tasks  # noqa: E402,F401
