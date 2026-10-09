"""Week 14 Kubernetes job tasks: bounded watch, submit retry, reconcile sweep,
timeout sweeper and finished-job GC.

The watch is a bounded single pass: each iteration re-reads cluster truth and
converges through :func:`kubernetes_executor.apply_cluster_job`, so the state
machine and terminal guards stay in exactly one place. Periodic cadence comes
from the celery beat entries (``kubernetes-job-reconcile`` / ``-gc``); client
failures back off exponentially (1s doubling to a 30s cap) and fall back to a
fixed 30s bounded poll after repeated misses. A 410 Gone resets the stored
resourceVersion so the next pass re-lists instead of resuming a dead stream.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.cloud_resources import KubernetesCluster, KubernetesCredentialRef
from app.models.kubernetes_execution import KubernetesJobRun
from app.services import kubernetes_executor as executor
from app.services.kubernetes_client import GONE, KubernetesClientError
from app.services.operation_lifecycle import claim_operation, heartbeat_operation
from app.tasks.celery_app import celery_app

DEFAULT_LEASE_SECONDS = 30
POLL_INTERVAL_SECONDS = 30


def watch_job_run(
    db: Session,
    job_run: KubernetesJobRun,
    credential_ref,
    run_settings,
    client=None,
    *,
    worker_id: str,
    since_resource_version: str | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    max_iterations: int = 8,
    sleep_fn=time.sleep,
    backoff_start: int = 1,
    backoff_cap: int = POLL_INTERVAL_SECONDS,
    fallback_after: int = 4,
    poll_interval: int = POLL_INTERVAL_SECONDS,
) -> dict:
    """Claim the operation lease and converge one job toward its terminal state."""
    summary = {
        "claimed": False,
        "status": job_run.status,
        "iterations": 0,
        "last_resource_version": since_resource_version,
        "fell_back": False,
    }
    job_run = db.merge(job_run, load=True)
    if job_run.status in executor.TERMINAL_STATUSES:
        summary["reason"] = "terminal"
        return summary
    try:
        claimed = claim_operation(db, job_run.operation_id, worker_id, lease_seconds)
    except ValueError:
        claimed = False
    if not claimed:
        summary["reason"] = "lease"
        return summary
    summary["claimed"] = True
    db.expire_all()
    job_run = db.get(KubernetesJobRun, job_run.id)

    last_rv = since_resource_version
    consecutive = 0
    backoff = max(1, backoff_start)
    iterations = 0
    while iterations < max_iterations and job_run.status not in executor.TERMINAL_STATUSES:
        iterations += 1
        try:
            heartbeat_operation(db, job_run.operation_id, worker_id, lease_seconds)
        except ValueError:
            summary.update({"status": job_run.status, "iterations": iterations, "reason": "lease_lost"})
            return summary
        try:
            cluster, job = executor.fetch_cluster_job(db, job_run, credential_ref, run_settings, client=client)
        except KubernetesClientError as error:
            if error.code == GONE:
                last_rv = None
            consecutive += 1
            if consecutive >= fallback_after:
                summary["fell_back"] = True
                sleep_fn(poll_interval)
            else:
                wait = min(backoff, backoff_cap)
                sleep_fn(wait)
                backoff = min(backoff * 2, backoff_cap)
            continue
        consecutive = 0
        backoff = max(1, backoff_start)
        if job is not None and job.get("resource_version"):
            last_rv = str(job["resource_version"])
        executor.apply_cluster_job(db, job_run, cluster, job, credential_ref, run_settings, client=client)
        db.expire_all()
        job_run = db.get(KubernetesJobRun, job_run.id)
    summary.update({"status": job_run.status, "iterations": iterations, "last_resource_version": last_rv})
    return summary


def reconcile_non_terminal_jobs(
    db: Session,
    credential_ref,
    run_settings,
    *,
    client=None,
    worker_id: str = "scheduler",
) -> dict[str, str]:
    """Restart-recovery sweep: converge every non-terminal row toward cluster truth."""
    results: dict[str, str] = {}
    rows = (
        db.query(KubernetesJobRun)
        .filter(KubernetesJobRun.status.in_(executor.NON_TERMINAL_STATUSES))
        .order_by(KubernetesJobRun.created_at)
        .all()
    )
    for row in rows:
        executor.reconcile_job(db, row, credential_ref, run_settings, client=client)
        results[str(row.id)] = row.status
    return results


def mark_timed_out_jobs(db: Session, *, now=None) -> list[str]:
    """Second timeout channel beside activeDeadlineSeconds; the terminal guard
    makes whichever channel lands first the only writer."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    swept: list[str] = []
    rows = (
        db.query(KubernetesJobRun)
        .filter(KubernetesJobRun.status.in_(executor.NON_TERMINAL_STATUSES))
        .all()
    )
    for row in rows:
        if row.submitted_at is None:
            continue
        started = row.submitted_at if row.submitted_at.tzinfo is None else row.submitted_at.replace(tzinfo=None)
        if now - started <= timedelta(seconds=row.timeout_seconds):
            continue
        if executor._set_terminal(row, "timed_out", error_code="KUBE_JOB_TIMEOUT", detail="timeout sweeper"):
            executor._settle_operation(db, row, "timed_out", "KUBE_JOB_TIMEOUT")
            db.commit()
        swept.append(str(row.id))
    return swept


def gc_finished_jobs(
    db: Session,
    credential_ref,
    run_settings,
    *,
    client=None,
    older_than_seconds: int | None = None,
) -> int:
    """Best-effort cluster-side delete for finished jobs past the TTL; DB rows stay."""
    ttl = older_than_seconds or run_settings.kubernetes_job_ttl_seconds_finished
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=ttl)
    rows = (
        db.query(KubernetesJobRun)
        .filter(KubernetesJobRun.status.in_(executor.TERMINAL_STATUSES))
        .filter(KubernetesJobRun.finished_at < cutoff)
        .all()
    )
    deleted = 0
    cluster_clients: dict = {}
    for row in rows:
        try:
            target = client
            if target is None:
                cluster_id = row.cluster_id
                if cluster_id not in cluster_clients:
                    cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == cluster_id).first()
                    ref = (
                        db.query(KubernetesCredentialRef)
                        .filter(KubernetesCredentialRef.cluster_id == cluster_id)
                        .first()
                    )
                    cluster_clients[cluster_id] = (
                        executor._client_for(cluster, ref, run_settings)
                        if cluster is not None and ref is not None
                        else None
                    )
                target = cluster_clients[cluster_id]
            if target is None:
                continue
            target.delete_job(row.job_name)
            deleted += 1
        except KubernetesClientError:
            continue
    return deleted


@celery_app.task(name="ml_platform.kubernetes_job_submit")
def kubernetes_job_submit(job_run_id: str) -> dict:
    """Retry the cluster create for a run whose durable row committed first."""
    db = SessionLocal()
    try:
        run = db.get(KubernetesJobRun, uuid.UUID(job_run_id))
        if run is None:
            return {"ok": False, "reason": "not_found"}
        executor.reconcile_job(db, run, None, settings)
        return {"ok": True, "status": run.status}
    finally:
        db.close()


@celery_app.task(name="ml_platform.kubernetes_job_watch")
def kubernetes_job_watch(job_run_id: str, since_resource_version: str | None = None) -> dict:
    db = SessionLocal()
    try:
        run = db.get(KubernetesJobRun, uuid.UUID(job_run_id))
        if run is None:
            return {"claimed": False, "reason": "not_found"}
        return watch_job_run(
            db,
            run,
            None,
            settings,
            worker_id=f"celery-watch-{os.getpid()}",
            since_resource_version=since_resource_version,
        )
    finally:
        db.close()


@celery_app.task(name="ml_platform.kubernetes_jobs_reconcile")
def kubernetes_jobs_reconcile() -> dict:
    db = SessionLocal()
    try:
        statuses = reconcile_non_terminal_jobs(db, None, settings)
        swept = mark_timed_out_jobs(db)
        return {"reconciled": statuses, "timed_out": swept}
    finally:
        db.close()


@celery_app.task(name="ml_platform.kubernetes_jobs_gc")
def kubernetes_jobs_gc() -> dict:
    db = SessionLocal()
    try:
        return {"deleted": gc_finished_jobs(db, None, settings)}
    finally:
        db.close()


@celery_app.task(name="ml_platform.notebook_idle_sweep")
def notebook_idle_sweep() -> dict:
    from app.services import notebook_service

    db = SessionLocal()
    try:
        swept = notebook_service.sweep_idle_sessions(db, None, settings)
        return {"swept": swept}
    finally:
        db.close()
