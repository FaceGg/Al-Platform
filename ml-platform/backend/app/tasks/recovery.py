"""Idempotent scans for pending and stale workflow tasks."""

from datetime import timedelta

from app.tasks.workflow_tasks import utcnow, _aware
from app.models.run import WorkflowRun


def recover_pending_runs(db, enqueue, limit: int = 100) -> int:
    runs = db.query(WorkflowRun).filter(
        WorkflowRun.status.in_(["pending", "queued"]),
        WorkflowRun.task_id.is_(None),
    ).limit(limit).all()
    count = 0
    for run in runs:
        task_id = enqueue(str(run.id))
        run.status = "queued"
        run.task_id = task_id
        db.commit()
        count += 1
    return count


def reconcile_stale_runs(db, active_task_ids: set[str], hard_timeout: timedelta) -> int:
    cutoff = utcnow() - hard_timeout
    runs = db.query(WorkflowRun).filter(
        WorkflowRun.status.in_(["running", "cancel_requested"]),
    ).all()
    count = 0
    for run in runs:
        if run.task_id in active_task_ids:
            continue
        heartbeat = _aware(run.heartbeat_at) if run.heartbeat_at else None
        if heartbeat is None or heartbeat < cutoff:
            if run.status == "cancel_requested":
                run.status = "cancelled"
                run.cancelled_at = utcnow()
                run.error_code = None
                run.error_message = None
            else:
                run.status = "failed"
                run.error_code = "TASK_HARD_TIMEOUT"
                run.error_message = "Workflow task exceeded the hard timeout"
            run.finished_at = utcnow()
            db.commit()
            count += 1
    return count
