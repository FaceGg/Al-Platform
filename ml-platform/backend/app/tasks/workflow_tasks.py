"""Celery workflow task helpers and idempotent claim logic."""

import uuid
import threading
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.events.base import NullRunEventPublisher
from app.events.redis import RedisRunEventPublisher
from app.models.run import WorkflowRun
from app.config import settings
from app.services.workflow_execution import execute_workflow_run
from app.tasks.celery_app import celery_app


def utcnow():
    return datetime.now(timezone.utc)


def claim_run(db, run_id, task_id: str, worker_id: str, stale_after: timedelta = timedelta(minutes=2)) -> bool:
    run = db.query(WorkflowRun).with_for_update().filter(
        WorkflowRun.id == run_id,
    ).first()
    if run is None:
        return False
    stale = run.heartbeat_at is not None and _aware(utcnow()) - _aware(run.heartbeat_at) > stale_after
    if run.status == "running" and not stale:
        return False
    if run.status not in {"pending", "queued", "running"}:
        return False
    run.status = "running"
    run.task_id = task_id
    run.worker_id = worker_id
    run.heartbeat_at = utcnow()
    db.commit()
    return True


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def build_event_publisher():
    if settings.redis_events_url is None:
        return NullRunEventPublisher()
    from redis import Redis

    client = Redis.from_url(
        settings.redis_events_url.get_secret_value(),
        decode_responses=False,
    )
    return RedisRunEventPublisher(client)


def heartbeat_run(
    run_id,
    task_id: str,
    stop_event,
    *,
    session_factory=SessionLocal,
    interval_seconds: float = 30.0,
) -> None:
    while not stop_event.is_set():
        with session_factory() as db:
            run = db.query(WorkflowRun).filter(
                WorkflowRun.id == run_id,
                WorkflowRun.task_id == task_id,
                WorkflowRun.status.in_(["running", "cancel_requested"]),
            ).first()
            if run is None:
                return
            run.heartbeat_at = utcnow()
            db.commit()
        if stop_event.wait(interval_seconds):
            return


@celery_app.task(bind=True, name="ml_platform.execute_workflow")
def execute_workflow_task(self, run_id: str):
    run_uuid = uuid.UUID(run_id)
    task_id = self.request.id
    with SessionLocal() as db:
        if not claim_run(db, run_uuid, task_id, self.request.hostname or "worker"):
            return {"status": "skipped", "run_id": run_id}
    stop_event = threading.Event()
    heartbeat = threading.Thread(
        target=heartbeat_run,
        args=(run_uuid, task_id, stop_event),
        daemon=True,
        name=f"workflow-heartbeat-{run_id}",
    )
    publisher = build_event_publisher()
    heartbeat.start()
    try:
        execute_workflow_run(run_id, event_publisher=publisher)
    finally:
        try:
            close = getattr(publisher, "close", None)
            if close is not None:
                close()
        finally:
            stop_event.set()
            heartbeat.join(timeout=2)
    return {"status": "completed", "run_id": run_id}
