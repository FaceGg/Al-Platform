"""Celery Beat tasks for persisted pipeline schedules."""

from app.database import SessionLocal
from app.services.pipeline_scheduler import PipelineScheduler, recover_stale_schedule_runs
from app.tasks.celery_app import celery_app
from app.tasks.workflow_tasks import execute_workflow_task


def _enqueue_workflow(run_id: str) -> str:
    return execute_workflow_task.delay(run_id).id


@celery_app.task(name="ml_platform.scheduler_tick")
def scheduler_tick():
    with SessionLocal() as db:
        return PipelineScheduler(enqueue=_enqueue_workflow).tick(db)


@celery_app.task(name="ml_platform.recover_pipeline_schedules")
def recover_pipeline_schedules():
    with SessionLocal() as db:
        return recover_stale_schedule_runs(db)
