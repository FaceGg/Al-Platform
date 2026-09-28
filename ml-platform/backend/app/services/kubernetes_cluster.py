"""Domain service for Week 13 Kubernetes foundation.

Owns input validation, the connectivity state machine (pending / active /
connectivity_failed / disabled), check-result persistence that never mutates
credential material, and namespace ensure. The client factory is a module
variable so tests inject :class:`FakeKubernetesClient` on the same code path.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from app.models.cloud_resources import (
    KubernetesCluster,
    KubernetesCredentialRef,
    KubernetesNamespace,
)
from app.services.kubernetes_client import (
    CLIENT_UNAVAILABLE,
    NAMESPACE_INVALID,
    QUOTA_INVALID,
    KubernetesClientError,
    FakeKubernetesClient,
    build_kubernetes_client,
    validate_endpoint,
)

CLUSTER_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
NAMESPACE_NAME_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
ALLOWED_QUOTA_KEYS = {"cpu_cores", "memory_mb", "max_pods"}
STALE_STATUSES = ("active", "connectivity_failed", "pending")

client_factory = None  # type: ignore[assignment]


def get_client_for_cluster(cluster, credential_ref, settings):
    """Resolve the client for a cluster; tests override ``client_factory``."""
    factory = client_factory
    if factory is None:
        return build_kubernetes_client(
            cluster,
            credential_ref,
            connect_timeout_seconds=settings.kubernetes_connect_timeout_seconds,
            read_timeout_seconds=settings.kubernetes_read_timeout_seconds,
        )
    return factory(cluster, credential_ref)


def validate_cluster_name(name: str) -> str:
    if not name or not CLUSTER_NAME_PATTERN.match(name):
        raise KubernetesClientError("KUBERNETES_ENDPOINT_INVALID", "cluster name must match [a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")
    return name


def validate_namespace_name(name: str) -> str:
    if not name or not NAMESPACE_NAME_PATTERN.match(name) or len(name) > 63:
        raise KubernetesClientError(NAMESPACE_INVALID, "namespace must be an RFC 1123 label (lowercase, <=63 chars)")
    return name


def validate_quota_json(quota_json: dict | None) -> dict | None:
    if quota_json is None:
        return None
    if not isinstance(quota_json, dict):
        raise KubernetesClientError(QUOTA_INVALID, "quota must be an object")
    cleaned: dict = {}
    for key, value in quota_json.items():
        if key not in ALLOWED_QUOTA_KEYS:
            raise KubernetesClientError(QUOTA_INVALID, f"quota key {key} is not allowed")
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise KubernetesClientError(QUOTA_INVALID, f"quota value for {key} must be a positive integer")
        cleaned[key] = value
    return cleaned or None


def validate_registration(
    *,
    name: str,
    api_server_url: str,
    secret_ref: str,
    insecure_tls: bool,
    settings,
) -> tuple[str, str, str]:
    """Validate a registration payload; returns (name, normalized_url, secret_ref)."""
    validate_cluster_name(name)
    normalized_url = validate_endpoint(
        api_server_url,
        allowlist=list(settings.kubernetes_endpoint_allowlist),
        allow_insecure=settings.kubernetes_allow_insecure_endpoints,
        insecure_tls=insecure_tls,
    )
    # Parse (raises on bad refs) without resolving the material here.
    from app.services.kubernetes_client import parse_secret_ref

    parse_secret_ref(secret_ref)
    return name, normalized_url, secret_ref


def record_check_result(
    cluster: KubernetesCluster,
    *,
    ok: bool,
    error_code: str | None,
    message: str,
    latency_ms: int | None,
    kubernetes_version: str | None,
) -> None:
    """Persist a connectivity check; failures never touch registration fields."""
    cluster.last_check_status = "ok" if ok else "failed"
    cluster.last_check_error_code = None if ok else error_code
    cluster.last_check_message = None if ok else (message or error_code or "")[:500]
    cluster.last_checked_at = datetime.now(timezone.utc)
    cluster.last_check_latency_ms = latency_ms
    if ok:
        cluster.status = "active"
        if kubernetes_version:
            cluster.kubernetes_version = kubernetes_version[:32]
    elif cluster.status in ("pending", "active"):
        cluster.status = "connectivity_failed"


def is_stale(cluster: KubernetesCluster, settings) -> bool:
    if cluster.last_checked_at is None:
        return True
    checked_at = cluster.last_checked_at
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    threshold = timedelta(seconds=settings.kubernetes_stale_after_seconds)
    return datetime.now(timezone.utc) - checked_at > threshold


def run_connectivity_check(cluster: KubernetesCluster, credential_ref, settings) -> dict:
    """Synchronous, bounded connectivity check; persists the outcome.

    Cluster-specific failures (unreachable, bad credentials, TLS, timeouts) are
    recorded as recoverable check failures. A missing ``kubernetes`` dependency
    is an environment problem and re-raised for the API to map to 503.
    """
    started = datetime.now(timezone.utc)
    try:
        client = get_client_for_cluster(cluster, credential_ref, settings)
        result = client.check_connectivity()
    except KubernetesClientError as error:
        if error.code == CLIENT_UNAVAILABLE:
            raise
        latency = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        record_check_result(
            cluster,
            ok=False,
            error_code=error.code,
            message=error.message,
            latency_ms=latency,
            kubernetes_version=None,
        )
        return {
            "check_status": "failed",
            "error_code": error.code,
            "latency_ms": latency,
            "checked_at": cluster.last_checked_at,
        }
    latency = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    record_check_result(
        cluster,
        ok=True,
        error_code=None,
        message="",
        latency_ms=latency,
        kubernetes_version=result.get("kubernetes_version"),
    )
    return {
        "check_status": "ok",
        "error_code": None,
        "latency_ms": latency,
        "checked_at": cluster.last_checked_at,
        "kubernetes_version": cluster.kubernetes_version,
    }


def ensure_namespace(
    cluster: KubernetesCluster,
    credential_ref,
    settings,
    *,
    name: str,
    quota_json: dict | None,
):
    """Idempotent namespace ensure: validate, apply on cluster, upsert DB row."""
    validate_namespace_name(name)
    clean_quota = validate_quota_json(quota_json)
    client = get_client_for_cluster(cluster, credential_ref, settings)
    result = client.ensure_namespace(name, clean_quota)
    return name, clean_quota, result


def upsert_namespace_row(db, cluster: KubernetesCluster, name: str, quota_json: dict | None):
    row = (
        db.query(KubernetesNamespace)
        .filter(KubernetesNamespace.cluster_id == cluster.id, KubernetesNamespace.name == name)
        .first()
    )
    if row is None:
        row = KubernetesNamespace(
            cluster_id=cluster.id,
            project_id=cluster.project_id,
            name=name,
        )
        db.add(row)
    row.status = "active"
    row.quota_json = quota_json
    row.quota_cpu_millicores = int(quota_json.get("cpu_cores", 0) * 1000) if quota_json and "cpu_cores" in quota_json else None
    row.quota_memory_mb = int(quota_json["memory_mb"]) if quota_json and "memory_mb" in quota_json else None
    row.last_synced_at = datetime.now(timezone.utc)
    db.flush()
    return row


def make_fake_client(**kwargs) -> FakeKubernetesClient:
    return FakeKubernetesClient(**kwargs)
