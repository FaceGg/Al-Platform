"""Week 14 Kubernetes batch executor.

Owns deterministic Job naming, security-constrained manifest generation,
idempotent submission (database first, cluster second), the job state machine
with an immutable-terminal guard, bounded/redacted log reads and restart
reconciliation. All cluster calls go through the Week 13 client adapters so
tests inject :class:`FakeKubernetesClient` on the same code path.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.cloud_resources import KubernetesCluster, KubernetesCredentialRef
from app.models.operation import DurableOperation
from app.models.kubernetes_execution import KubernetesJobRun
from app.services.kubernetes_client import (
    CONNECTIVITY_FAILED,
    KubernetesClientError,
    _job_labels,
    build_job_manifest,
    redact_text,
)

TERMINAL_STATUSES = ("succeeded", "failed", "cancelled", "timed_out", "orphaned")
NON_TERMINAL_STATUSES = ("queued", "submitted", "running")
IMAGE_DIGEST_PATTERN = re.compile(r"^(?P<repo>[a-z0-9._/-]+(?:\:[0-9]+)?[a-z0-9._/-]*)@sha256:[a-f0-9]{64}$")
JOB_NAME_PATTERN = re.compile(r"^lr-[a-f0-9]{8}-job-[a-f0-9]{8}-[0-9]+$")
BINDINGS_UNSUPPORTED = "KUBE_JOB_BINDINGS_UNSUPPORTED"
JOB_NAME_COLLISION = "KUBE_JOB_NAME_COLLISION"


class KubeJobError(Exception):
    """Typed Week 14 error: ``code`` drives API responses, ``status`` the HTTP code."""

    def __init__(self, code: str, message: str = "", status: int = 422):
        super().__init__(message or code)
        self.code = code
        self.message = redact_text(message)
        self.status = status


def job_name_for(project_id, operation_id, revision: int) -> str:
    pid = str(project_id).replace("-", "")
    oid = str(operation_id).replace("-", "")
    return f"lr-{pid[:8]}-job-{oid[:8]}-{revision}"


def validate_image_ref(image_ref: str, approved_prefixes: list[str]) -> str:
    match = IMAGE_DIGEST_PATTERN.match(image_ref or "")
    if not match:
        raise KubeJobError("KUBE_JOB_IMAGE_INVALID", "image must reference an immutable digest (repo@sha256:...)")
    repo = match.group("repo")
    for prefix in approved_prefixes:
        if repo.startswith(prefix):
            return image_ref
    raise KubeJobError("KUBE_JOB_IMAGE_FORBIDDEN", "image repository is not in the approved prefix list")


def validate_env(env: dict, allowed_keys: list[str]) -> dict:
    cleaned = {}
    for key, value in (env or {}).items():
        if key not in allowed_keys:
            raise KubeJobError("KUBE_JOB_ENV_FORBIDDEN", f"environment key {key} is not allowlisted")
        if not isinstance(value, str):
            raise KubeJobError("KUBE_JOB_ENV_FORBIDDEN", f"environment value for {key} must be a string")
        cleaned[key] = value
    return cleaned


def validate_resources(resources: dict, settings) -> dict:
    cleaned = dict(resources or {})
    cpu = cleaned.get("cpu_cores", 1)
    memory = cleaned.get("memory_gb", 1)
    if not isinstance(cpu, (int, float)) or cpu <= 0 or cpu > settings.kubernetes_job_max_cpu_cores:
        raise KubeJobError("KUBE_JOB_RESOURCES_INVALID", f"cpu_cores must be within (0, {settings.kubernetes_job_max_cpu_cores}]")
    if not isinstance(memory, (int, float)) or memory <= 0 or memory > settings.kubernetes_job_max_memory_gb:
        raise KubeJobError("KUBE_JOB_RESOURCES_INVALID", f"memory_gb must be within (0, {settings.kubernetes_job_max_memory_gb}]")
    return {"cpu_cores": cpu, "memory_gb": memory}


def validate_timeout(timeout_seconds: int, settings) -> int:
    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0 or timeout_seconds > settings.kubernetes_job_max_timeout_seconds:
        raise KubeJobError("KUBE_JOB_TIMEOUT_INVALID", f"timeout_seconds must be within (0, {settings.kubernetes_job_max_timeout_seconds}]")
    return timeout_seconds


def validate_bindings(input_bindings, output_bindings) -> None:
    if input_bindings or output_bindings:
        raise KubeJobError(BINDINGS_UNSUPPORTED, "artifact bindings are not executable in week 14", status=422)


def validate_command(command, args) -> tuple[list[str], list[str]]:
    if not isinstance(command, list) or not all(isinstance(c, str) for c in command) or not command:
        raise KubeJobError("KUBE_JOB_COMMAND_INVALID", "command must be a non-empty list of strings")
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise KubeJobError("KUBE_JOB_COMMAND_INVALID", "args must be a list of strings")
    return list(command), list(args)


def _set_terminal(job_run: KubernetesJobRun, status: str, *, error_code: str | None, detail: str, exit_code: int | None = None) -> bool:
    """Guarded terminal write: late events can never reopen a settled state."""
    if job_run.status in TERMINAL_STATUSES:
        return False
    job_run.status = status
    job_run.error_code = error_code
    job_run.status_detail = redact_text(detail)[:500] if detail else None
    job_run.exit_code = exit_code
    job_run.finished_at = datetime.now(timezone.utc)
    return True


def submit_job(
    db: Session,
    *,
    project_id,
    cluster: KubernetesCluster,
    credential_ref,
    settings,
    image_ref: str,
    command: list[str],
    args: list[str],
    env: dict | None,
    resources: dict | None,
    timeout_seconds: int,
    idempotency_key: str,
    actor_id,
    task_id=None,
) -> tuple[KubernetesJobRun, bool]:
    """Idempotent submission: database rows commit before any cluster call."""
    validate_bindings([], [])
    existing = (
        db.query(KubernetesJobRun)
        .filter(KubernetesJobRun.project_id == project_id, KubernetesJobRun.idempotency_key == idempotency_key)
        .first()
    )
    if existing is not None:
        return existing, True

    clean_image = validate_image_ref(image_ref, list(settings.kubernetes_job_approved_image_prefixes))
    clean_env = validate_env(env or {}, list(settings.kubernetes_job_allowed_env_keys))
    clean_resources = validate_resources(resources or {}, settings)
    clean_timeout = validate_timeout(timeout_seconds, settings)
    clean_command, clean_args = validate_command(command, args)

    run = KubernetesJobRun(
        project_id=project_id,
        cluster_id=cluster.id,
        namespace=cluster.default_namespace or "default",
        task_id=task_id,
        idempotency_key=idempotency_key,
        image_ref=clean_image,
        command_json=clean_command,
        args_json=clean_args,
        env_json={k: len(v) for k, v in clean_env.items()},
        resource_json=clean_resources,
        timeout_seconds=clean_timeout,
        status="queued",
        created_by=actor_id,
    )
    db.add(run)
    db.flush()
    run.job_name = job_name_for(project_id, run.id, run.revision)
    operation = DurableOperation(
        project_id=project_id,
        task_id=task_id,
        resource_type="kubernetes_job",
        resource_key=f"kubernetes-job:{run.id}",
        idempotency_key=idempotency_key,
        state="queued",
        stage="queued",
    )
    db.add(operation)
    db.flush()
    run.operation_id = operation.id
    db.commit()

    client_error: str | None = None
    try:
        client = _client_for(cluster, credential_ref, settings)
        client.create_job(
            build_job_manifest(
                job_name=run.job_name,
                namespace=run.namespace,
                image_ref=clean_image,
                command=clean_command,
                args=clean_args,
                env=clean_env,
                resources=clean_resources,
                timeout_seconds=clean_timeout,
                labels=_job_labels(project_id, run.id, run.revision),
                ttl_seconds_finished=settings.kubernetes_job_ttl_seconds_finished,
            )
        )
        run.status = "submitted"
        run.submitted_at = datetime.now(timezone.utc)
    except KubernetesClientError as error:
        # Database-first contract: keep the durable row retryable for reconcile.
        client_error = error.code
        run.error_code = "KUBERNETES_SUBMIT_FAILED"
        run.status_detail = f"{error.code}: {error.message}"[:500]
    db.commit()
    return run, False


def _client_for(cluster: KubernetesCluster, credential_ref, settings):
    from app.services.kubernetes_cluster import get_client_for_cluster

    return get_client_for_cluster(cluster, credential_ref, settings)


def _map_condition(job: dict) -> tuple[str, str]:
    for condition in job.get("conditions") or []:
        if condition.get("type") == "Complete":
            return "succeeded", ""
        if condition.get("type") == "Failed":
            if condition.get("reason") == "DeadlineExceeded":
                return "timed_out", "activeDeadlineSeconds elapsed"
            return "failed", str(condition.get("message", ""))[:300]
    if job.get("succeeded"):
        return "succeeded", ""
    if job.get("failed"):
        return "failed", ""
    if job.get("active"):
        return "running", ""
    return "unknown", ""


def reconcile_job(db: Session, job_run: KubernetesJobRun, credential_ref, settings, client=None) -> KubernetesJobRun:
    """Read cluster truth once and converge the local state (idempotent)."""
    if job_run.status in TERMINAL_STATUSES:
        return job_run
    cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == job_run.cluster_id).first()
    if cluster is None:
        _set_terminal(job_run, "orphaned", error_code="KUBE_JOB_ORPHANED", detail="cluster registration missing")
        db.commit()
        return job_run

    try:
        if client is None:
            client = _client_for(cluster, credential_ref, settings)
        job = client.get_job(job_run.job_name)
    except KubernetesClientError as error:
        job_run.error_code = error.code
        job_run.status_detail = f"reconcile deferred: {error.code}"[:500]
        db.commit()
        return job_run

    if job is None:
        if job_run.status == "queued":
            # Submitted call crashed before cluster create: retry submission.
            try:
                client = client or _client_for(cluster, credential_ref, settings)
                client.create_job(
                    build_job_manifest(
                        job_name=job_run.job_name,
                        namespace=job_run.namespace,
                        image_ref=job_run.image_ref,
                        command=list(job_run.command_json),
                        args=list(job_run.args_json),
                        env={},
                        resources=dict(job_run.resource_json or {}),
                        timeout_seconds=job_run.timeout_seconds,
                        labels=_job_labels(job_run.project_id, job_run.id, job_run.revision),
                        ttl_seconds_finished=settings.kubernetes_job_ttl_seconds_finished,
                    )
                )
                job_run.status = "submitted"
                job_run.error_code = None
                job_run.status_detail = "reconciled: job created"
            except KubernetesClientError as error:
                job_run.error_code = error.code
        elif job_run.submitted_at is not None:
            _set_terminal(job_run, "orphaned", error_code="KUBE_JOB_ORPHANED", detail="job disappeared from cluster")
        db.commit()
        return job_run

    mapped, reason = _map_condition(job)
    if mapped == "running":
        if job_run.status in ("queued", "submitted"):
            job_run.status = "running"
            job_run.started_at = job_run.started_at or datetime.now(timezone.utc)
    elif mapped == "succeeded":
        _set_terminal(job_run, "succeeded", error_code=None, detail="", exit_code=0)
    elif mapped == "timed_out":
        _set_terminal(job_run, "timed_out", error_code="KUBE_JOB_TIMEOUT", detail=reason)
    elif mapped == "failed":
        _set_terminal(job_run, "failed", error_code="KUBE_JOB_FAILED", detail=reason)
    db.commit()
    return job_run


def cancel_job(db: Session, job_run: KubernetesJobRun, credential_ref, settings, *, reason: str) -> KubernetesJobRun:
    if job_run.status in TERMINAL_STATUSES:
        raise KubeJobError("KUBE_JOB_ALREADY_TERMINAL", f"job already {job_run.status}", status=409)
    cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == job_run.cluster_id).first()
    client = _client_for(cluster, credential_ref, settings)
    try:
        client.delete_job(job_run.job_name)
    except KubernetesClientError as error:
        raise KubeJobError(error.code, error.message, status=502)
    _set_terminal(job_run, "cancelled", error_code=None, detail=reason or "")
    db.commit()
    return job_run


def read_logs(cluster: KubernetesCluster, credential_ref, settings, job_run: KubernetesJobRun, *, cursor: int, limit_bytes: int | None = None) -> dict:
    limit = min(limit_bytes or settings.kubernetes_job_log_chunk_bytes, settings.kubernetes_job_log_chunk_bytes)
    client = _client_for(cluster, credential_ref, settings)
    pods = client.list_job_pods(job_run.job_name)
    chunk = ""
    for pod in pods:
        chunk += client.read_pod_log(pod["name"], cursor, limit)
        if len(chunk.encode("utf-8")) >= limit:
            break
    data = chunk.encode("utf-8")[:limit]
    text = redact_text(data.decode("utf-8", errors="replace"))
    job = client.get_job(job_run.job_name)
    terminal = bool(job and (job.get("succeeded") or job.get("failed") or job.get("deleted")))
    return {
        "text": text,
        "next_cursor": cursor + len(data),
        "end_of_stream": terminal and len(data) < limit,
    }
