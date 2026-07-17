"""Reconcile stale durable training jobs after worker loss."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.models.training import TrainingJob


@dataclass(frozen=True)
class TrainingRecoveryResult:
    requeued: int = 0
    failed: int = 0
    cancelled: int = 0

    @property
    def total(self) -> int:
        return self.requeued + self.failed + self.cancelled


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def reconcile_stale_training_jobs(
    db,
    *,
    active_task_ids: set[str],
    stale_after: timedelta,
) -> TrainingRecoveryResult:
    cutoff = utcnow() - stale_after
    jobs = db.query(TrainingJob).filter(
        TrainingJob.status.in_(["running", "cancel_requested"]),
    ).all()
    requeued = failed = cancelled = 0
    for job in jobs:
        if job.task_id in active_task_ids:
            continue
        heartbeat = job.heartbeat_at
        if heartbeat is not None and heartbeat >= cutoff:
            continue
        if job.status == "cancel_requested":
            job.status = "cancelled"
            job.finished_at = utcnow()
            cancelled += 1
        elif job.latest_checkpoint_uri:
            job.status = "pending"
            job.attempt = int(job.attempt or 0) + 1
            job.task_id = None
            job.worker_id = None
            job.heartbeat_at = None
            job.error_code = None
            job.error_message = None
            requeued += 1
        else:
            job.status = "failed"
            job.error_code = "TRAINING_WORKER_LOST"
            job.error_message = "Training worker was lost without a checkpoint"
            job.finished_at = utcnow()
            failed += 1
    db.commit()
    return TrainingRecoveryResult(requeued, failed, cancelled)
