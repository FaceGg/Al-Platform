"""Reconcile stale durable training jobs after worker loss."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.models.training import TrainingJob


@dataclass(frozen=True)
class TrainingRecoveryResult:
    requeued: int = 0
    failed: int = 0
    cancelled: int = 0
    requeued_job_ids: tuple[str, ...] = ()
    redispatched_job_ids: tuple[str, ...] = ()

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
    redispatch_after: timedelta = timedelta(seconds=60),
) -> TrainingRecoveryResult:
    cutoff = utcnow() - stale_after
    jobs = db.query(TrainingJob).filter(
        TrainingJob.status.in_(["running", "cancel_requested"]),
    ).all()
    requeued = failed = cancelled = 0
    requeued_job_ids: list[str] = []
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
        elif job.latest_checkpoint_uri or job.operator_id == "automl":
            job.status = "pending"
            job.attempt = int(job.attempt or 0) + 1
            job.task_id = None
            job.worker_id = None
            # fresh heartbeat doubles as the redispatch rate limiter below
            job.heartbeat_at = utcnow()
            job.error_code = None
            job.error_message = None
            requeued += 1
            requeued_job_ids.append(str(job.id))
        else:
            job.status = "failed"
            job.error_code = "TRAINING_WORKER_LOST"
            job.error_message = "Training worker was lost without a checkpoint"
            job.finished_at = utcnow()
            failed += 1

    # Self-heal jobs stuck before any worker claimed them: a dispatch/claim
    # race (queue delivery before the queued status commits) leaves a job
    # queued with no live celery task, and nothing re-delivered it. Claim
    # arbitration makes duplicate delivery safe, so re-send stale ones and
    # stamp the heartbeat as the rate limiter for the next tick.
    redispatch_cutoff = utcnow() - redispatch_after
    stuck = db.query(TrainingJob).filter(
        TrainingJob.status.in_(["pending", "queued"]),
    ).all()
    redispatched_job_ids: list[str] = []
    for job in stuck:
        if job.task_id and job.task_id in active_task_ids:
            continue
        last_activity = job.heartbeat_at or job.created_at
        if last_activity is not None and last_activity >= redispatch_cutoff:
            continue
        job.heartbeat_at = utcnow()
        redispatched_job_ids.append(str(job.id))

    db.commit()
    return TrainingRecoveryResult(requeued, failed, cancelled, tuple(requeued_job_ids), tuple(redispatched_job_ids))
