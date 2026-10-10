"""Week 15 Notebook session service.

Sessions are Week 14 jobs wearing the ``linkraft.io/role=notebook`` label:
submission is database-first and idempotent, lifecycle transitions go through
the same guarded state machine, and the browser reaches the container only via
the platform's HMAC-tokened reverse proxy — cluster credentials never leave
the server side.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models.cloud_resources import KubernetesCluster, KubernetesCredentialRef
from app.models.developer_resources import ContainerImage, NotebookSession
from app.models.operation import DurableOperation
from app.services.kubernetes_client import (
    KubernetesClientError,
    _job_labels,
    build_job_manifest,
    redact_text,
)
from app.services.kubernetes_executor import (
    KubeJobError,
    _map_condition,
    validate_resources,
)

SESSION_TERMINAL_STATUSES = ("stopped", "failed", "terminated")
IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
ACCESS_TOKEN_VERSION = "w15nb"


class NotebookError(Exception):
    """Typed Week 15 error: ``code`` drives API responses, ``status`` the HTTP code."""

    def __init__(self, code: str, message: str = "", status: int = 422):
        super().__init__(message or code)
        self.code = code
        self.message = redact_text(message)
        self.status = status


def _client_for(cluster: KubernetesCluster, credential_ref, run_settings):
    from app.services.kubernetes_cluster import get_client_for_cluster

    return get_client_for_cluster(cluster, credential_ref, run_settings)


def resolve_catalog_image(db: Session, image_ref: str, project_id) -> ContainerImage:
    """The image must be registered in the catalog and not scan-failed."""
    match = re.match(r"^(?P<registry>[^/@\s]+)/?(?P<repository>[^@\s]+)@(?P<digest>sha256:[a-f0-9]{64})$", image_ref or "")
    if match:
        image = (
            db.query(ContainerImage)
            .filter(
                ContainerImage.registry == match.group("registry"),
                ContainerImage.repository == match.group("repository").lstrip("/"),
                ContainerImage.digest == match.group("digest"),
            )
            .first()
        )
        if image is not None:
            if image.scan_status == "failed":
                raise NotebookError("NOTEBOOK_IMAGE_SCAN_FAILED", "image scan_status=failed blocks references")
            if image.visibility == "platform" or image.project_id == project_id:
                return image
    raise NotebookError("NOTEBOOK_IMAGE_NOT_IN_CATALOG", "image is not registered in the approved catalog")


def job_name_for(session_id, revision: int = 1) -> str:
    return f"lr-notebook-{str(session_id).replace('-', '')[:12]}-{revision}"


def _build_notebook_manifest(
    *,
    job_name: str,
    namespace: str,
    image_ref: str,
    resources: dict,
    labels: dict,
    gpu_injection: dict | None,
) -> dict:
    container: dict = {
        "name": "linkraft-notebook",
        "image": image_ref,
        "resources": {
            "requests": {
                "cpu": str(resources.get("cpu_cores", 1)),
                "memory": f"{resources.get('memory_gb', 1)}Gi",
            }
        },
    }
    if gpu_injection:
        limits = dict(gpu_injection["resources"]["limits"])
        requests = dict(gpu_injection["resources"]["requests"])
        container["resources"]["limits"] = {**container["resources"].get("limits", {}), **limits}
        container["resources"]["requests"] = {**container["resources"].get("requests", {}), **requests}
    pod_spec: dict = {
        "restartPolicy": "Always",
        "automountServiceAccountToken": False,
        "containers": [container],
    }
    if gpu_injection:
        pod_spec["nodeSelector"] = dict(gpu_injection["node_selector"])
        pod_spec["tolerations"] = list(gpu_injection["tolerations"])
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name, "namespace": namespace, "labels": dict(labels)},
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 3600,
            "manualSelector": True,
            "selector": {"matchLabels": {"linkraft.io/operation-id": labels["linkraft.io/operation-id"]}},
            "template": {"metadata": {"labels": dict(labels)}, "spec": pod_spec},
        },
    }


def _create_service(client, job_name: str, namespace: str, labels: dict, port: int) -> None:
    client.create_service(
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": job_name, "namespace": namespace, "labels": dict(labels)},
            "spec": {
                "type": "ClusterIP",
                "selector": {"linkraft.io/operation-id": labels["linkraft.io/operation-id"]},
                "ports": [{"name": "http", "port": port, "targetPort": port, "protocol": "TCP"}],
            },
        }
    )


def start_session(
    db: Session,
    *,
    project_id,
    user_id,
    cluster: KubernetesCluster,
    credential_ref,
    run_settings,
    image_ref: str,
    resources: dict | None,
    gpu_class_name: str | None = None,
    gpu_count: int = 1,
    idle_timeout_seconds: int,
    idempotency_key: str,
    namespace: str | None = None,
    client=None,
) -> tuple[NotebookSession, bool]:
    existing = (
        db.query(NotebookSession)
        .filter(NotebookSession.project_id == project_id, NotebookSession.idempotency_key == idempotency_key)
        .first()
    )
    if existing is not None:
        return existing, True

    image = resolve_catalog_image(db, image_ref, project_id)
    clean_resources = validate_resources(resources or {}, run_settings)

    active_count = (
        db.query(NotebookSession)
        .filter(
            NotebookSession.user_id == user_id,
            NotebookSession.status.notin_(SESSION_TERMINAL_STATUSES),
        )
        .count()
    )
    if active_count >= run_settings.notebook_max_per_user:
        raise NotebookError("NOTEBOOK_CONCURRENCY_LIMIT", "too many active sessions for this user", status=429)

    gpu_injection = None
    if gpu_class_name:
        from app.services import gpu_scheduler

        gpu_class = gpu_scheduler.resolve_class(db, cluster.id, gpu_class_name)
        gpu_scheduler.verify_capacity(db, client if client is not None else _noop_client(cluster, credential_ref, run_settings), gpu_class, requested=gpu_count)
        gpu_injection = gpu_scheduler.build_injection(gpu_class, requested=gpu_count)

    session_id = uuid.uuid4()
    operation = DurableOperation(
        project_id=project_id,
        resource_type="notebook_session",
        resource_key=f"notebook-session:{session_id}",
        idempotency_key=idempotency_key,
        state="queued",
        stage="queued",
    )
    db.add(operation)
    db.flush()
    session = NotebookSession(
        id=session_id,
        project_id=project_id,
        user_id=user_id,
        cluster_id=cluster.id,
        namespace=namespace or cluster.default_namespace or "default",
        operation_id=operation.id,
        idempotency_key=idempotency_key,
        job_name=job_name_for(session_id),
        image_ref=image_ref,
        resource_json=clean_resources,
        status="starting",
        idle_timeout_seconds=idle_timeout_seconds,
        last_activity_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(session)
    db.commit()

    # Week 16 hook: reserve before any cluster call; QUOTA_EXCEEDED aborts the
    # submission and rolls the rows back (no policy = no-op, single-cluster
    # compatible).
    from app.services.cluster_scheduler import reserve

    try:
        reserve(
            db,
            project_id=project_id,
            cluster_id=cluster.id,
            operation_id=operation.id,
            reserved_json={
                "cpu_cores": clean_resources.get("cpu_cores", 1),
                "memory_mb": int(float(clean_resources.get("memory_gb", 1)) * 1024),
                "gpu_count": gpu_count if gpu_class_name else 0,
            },
        )
    except KubeJobError:
        db.delete(session)
        db.delete(operation)
        db.commit()
        raise

    labels = _job_labels(project_id, session.operation_id, 1)
    labels["linkraft.io/role"] = "notebook"
    try:
        target = client if client is not None else _client_for(cluster, credential_ref, run_settings)
        target.create_job(
            _build_notebook_manifest(
                job_name=session.job_name,
                namespace=session.namespace,
                image_ref=image_ref,
                resources=clean_resources,
                labels=labels,
                gpu_injection=gpu_injection,
            )
        )
        _create_service(
            target, session.job_name, session.namespace, labels, run_settings.notebook_container_port
        )
        session.status = "running"
        session.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    except KubernetesClientError as error:
        session.error_code = "NOTEBOOK_CLUSTER_CREATE_FAILED"
        session.status_detail = f"{error.code}: {error.message}"[:500] if hasattr(session, "status_detail") else None
        session.status = "failed"
        from app.services.operation_lifecycle import fail_operation

        try:
            fail_operation(db, session.operation_id, error.code)
        except ValueError:
            pass
    db.commit()
    return session, False


def _noop_client(cluster, credential_ref, run_settings):
    return None


def reconcile_session(
    db: Session,
    session: NotebookSession,
    credential_ref,
    run_settings,
    client=None,
) -> NotebookSession:
    if session.status in SESSION_TERMINAL_STATUSES:
        return session
    cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == session.cluster_id).first()
    if cluster is None:
        _terminate(db, session, "failed", "NOTEBOOK_CLUSTER_GONE")
        return session
    try:
        target = client if client is not None else _client_for(cluster, credential_ref, run_settings)
        job = target.get_job(session.job_name, session.namespace)
    except KubernetesClientError:
        return session
    if job is None:
        _terminate(db, session, "failed", "NOTEBOOK_JOB_GONE")
        return session
    mapped, _reason = _map_condition(job)
    if mapped == "failed":
        _terminate(db, session, "failed", "NOTEBOOK_JOB_FAILED")
    elif mapped == "succeeded" and session.status != "running":
        # A restartPolicy=Always notebook Job never succeeds; treat as anomaly.
        _terminate(db, session, "failed", "NOTEBOOK_JOB_EXITED")
    return session


def _terminate(db: Session, session: NotebookSession, status: str, error_code: str | None) -> None:
    if session.status in SESSION_TERMINAL_STATUSES:
        return
    from app.services.cluster_scheduler import release_reservation

    release_reservation(db, session.operation_id, "terminal")
    session.status = status
    session.error_code = error_code
    session.terminated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    from app.services.operation_lifecycle import fail_operation

    try:
        fail_operation(db, session.operation_id, error_code or "NOTEBOOK_TERMINATED")
    except ValueError:
        pass
    db.commit()


def stop_session(db: Session, session: NotebookSession, credential_ref, run_settings, *, reason: str, client=None, terminal_status: str = "stopped") -> NotebookSession:
    if session.status in SESSION_TERMINAL_STATUSES:
        return session
    session.status = "stopping"
    db.commit()
    cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == session.cluster_id).first()
    try:
        target = client if client is not None else _client_for(cluster, credential_ref, run_settings)
        target.delete_job(session.job_name, session.namespace)
        target.delete_service(session.job_name, session.namespace)
    except KubernetesClientError as error:
        _terminate(db, session, "failed", error.code)
        return session
    _terminate(db, session, terminal_status, None)
    return session


def sweep_idle_sessions(db: Session, credential_ref, run_settings, *, now=None, client=None) -> list[str]:
    """Idle reclamation: only ``running`` sessions past their idle timeout."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    swept: list[str] = []
    rows = db.query(NotebookSession).filter(NotebookSession.status == "running").all()
    for row in rows:
        last = row.last_activity_at or row.started_at
        if last is None:
            continue
        if last.tzinfo is not None:
            last = last.replace(tzinfo=None)
        if now - last <= timedelta(seconds=row.idle_timeout_seconds):
            continue
        stop_session(db, row, credential_ref, run_settings, reason="idle timeout", client=client)
        _audit_idle_timeout(db, row)
        swept.append(str(row.id))
    return swept


def _audit_idle_timeout(db: Session, session: NotebookSession) -> None:
    """Record the automatic reclamation; the owner is the audited actor."""
    from types import SimpleNamespace

    from app.models.user import User
    from app.services.audit import AuditIntent, AuditService
    from app.services.project_access import ProjectAccessService

    shim = SimpleNamespace(state=SimpleNamespace(request_id=None), client=None)
    owner = db.get(User, session.user_id)
    if owner is None:
        return
    try:
        access = ProjectAccessService().require(db, session.project_id, owner.id, "execution.operate")
        with AuditService(sessionmaker(bind=db.get_bind())).project_action(
            db,
            request=shim,
            actor=owner,
            access=access,
            permission="execution.operate",
            intent=AuditIntent(
                project_id=session.project_id,
                action="notebook.idle_timeout",
                resource_type="notebook_session",
                resource_id=str(session.id),
                changes={"idle_timeout_seconds": session.idle_timeout_seconds},
            ),
            allowed_changes={"idle_timeout_seconds"},
        ):
            pass
    except (ValueError, Exception):  # noqa: BLE001 - audit must not break reclamation
        pass


def touch_activity(db: Session, session: NotebookSession, *, now=None) -> None:
    session.last_activity_at = now or datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()


# ---- access tokens (HMAC, short-lived, stateless, revoked by session deletion) ----

def mint_access_token(run_settings, session_id, user_id, *, ttl_seconds: int | None = None, now: datetime | None = None) -> str:
    """Signed, self-contained proxy token: payload is visible, signature is not."""
    ttl = run_settings.notebook_access_token_ttl_seconds if ttl_seconds is None else ttl_seconds
    now = now or datetime.now(timezone.utc)
    expires = int((now + timedelta(seconds=ttl)).timestamp())
    payload = f"{ACCESS_TOKEN_VERSION}:{session_id}:{user_id}:{expires}"
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    digest = hmac.new(
        run_settings.secret_key.get_secret_value().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}:{digest}"


def verify_access_token(run_settings, token: str, session_id, *, now: datetime | None = None) -> uuid.UUID | None:
    """Return the user_id bound to a valid, unexpired token; None otherwise."""
    try:
        encoded, digest = (token or "").split(":", 1)
        payload = base64.urlsafe_b64decode((encoded + "=" * (-len(encoded) % 4)).encode("ascii")).decode("utf-8")
        version, token_session, token_user, expires_raw = payload.split(":")
        expires = int(expires_raw)
    except (ValueError, AttributeError, UnicodeDecodeError):
        return None
    now = now or datetime.now(timezone.utc)
    if version != ACCESS_TOKEN_VERSION or str(session_id) != token_session:
        return None
    if now.timestamp() > expires:
        return None
    expected = hmac.new(
        run_settings.secret_key.get_secret_value().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(digest, expected):
        return None
    try:
        return uuid.UUID(token_user)
    except (ValueError, AttributeError):
        return None
