"""Celery Beat tasks for persisted pipeline schedules."""

from app.database import SessionLocal
from app.services.pipeline_scheduler import (
    PipelineScheduler,
    reconcile_schedule_runs,
    recover_stale_schedule_runs,
)
from app.tasks.celery_app import celery_app


def _enqueue_workflow(run_id: str, timeout_seconds: int | None = None) -> str:
    options = {"time_limit": timeout_seconds} if timeout_seconds is not None else {}
    return celery_app.send_task(
        "ml_platform.execute_workflow",
        args=[run_id],
        **options,
    ).id


@celery_app.task(name="ml_platform.scheduler_tick")
def scheduler_tick():
    with SessionLocal() as db:
        return PipelineScheduler(enqueue=_enqueue_workflow).tick(db)


@celery_app.task(name="ml_platform.recover_pipeline_schedules")
def recover_pipeline_schedules():
    with SessionLocal() as db:
        reconciled = reconcile_schedule_runs(db)
        recovered = recover_stale_schedule_runs(db)
        return {"reconciled": reconciled, "recovered": recovered}
