"""Week 16 resource governance services: quota CRUD helpers, storage binding
validation/mount injection and K8s Summary API usage snapshots.

Collection is advisory: failures collapse into a ``stale`` marker and never
propagate into submission paths. GPU utilization is only reported when the
cluster exposes device-plugin metrics; otherwise it is ``unavailable`` —
never faked from host-level nvidia-smi data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.cloud_resources import KubernetesCluster, KubernetesCredentialRef
from app.models.resource_governance import ResourceUsageSnapshot
from app.services.kubernetes_client import KubernetesClientError
from app.services.kubernetes_executor import KubeJobError

SNAPSHOT_SCOPES = ("cluster", "node", "pod", "gpu")
ALLOWED_BINDING_MODES = ("pvc", "object_prefix")
ALLOWED_BINDING_ACCESS = ("read_only", "read_write")


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---- storage bindings ----

def validate_binding(
    *,
    project_id,
    mode: str,
    pvc_name: str | None = None,
    object_prefix: str | None = None,
    access: str = "read_only",
    extra: dict | None = None,
) -> dict:
    """Server-side boundary check; hostPath can never be expressed."""
    if mode not in ALLOWED_BINDING_MODES:
        raise KubeJobError("STORAGE_BINDING_INVALID", f"binding mode {mode} is not allowed (hostPath is always illegal)", status=422)
    if access not in ALLOWED_BINDING_ACCESS:
        raise KubeJobError("STORAGE_BINDING_INVALID", f"access {access} is not allowed", status=422)
    if extra:
        raise KubeJobError("STORAGE_BINDING_INVALID", "unknown binding fields are not allowed", status=422)
    binding: dict = {"mode": mode, "access": access}
    if mode == "pvc":
        if not pvc_name or not isinstance(pvc_name, str):
            raise KubeJobError("STORAGE_BINDING_INVALID", "pvc mode requires pvc_name", status=422)
        binding["pvc_name"] = pvc_name
    else:
        controlled_prefix = f"projects/{project_id}/"
        if (
            not object_prefix
            or not isinstance(object_prefix, str)
            or not object_prefix.startswith(controlled_prefix)
            or ".." in object_prefix
        ):
            raise KubeJobError(
                "STORAGE_BINDING_INVALID",
                f"object_prefix must stay under {controlled_prefix}",
                status=422,
            )
        binding["object_prefix"] = object_prefix
    return binding


def build_mount_injection(binding: dict, *, mount_path: str) -> dict:
    """Compose pod volumes/volumeMounts from a validated binding."""
    if binding["mode"] != "pvc":
        raise KubeJobError("STORAGE_BINDING_INVALID", "mount injection requires a pvc binding", status=422)
    read_only = binding["access"] == "read_only"
    return {
        "mount_path": mount_path,
        "volumes": [
            {
                "name": "linkraft-binding",
                "persistentVolumeClaim": {"claimName": binding["pvc_name"], "readOnly": read_only},
            }
        ],
        "volume_mounts": [{"name": "linkraft-binding", "mountPath": mount_path, "readOnly": read_only}],
    }


# ---- quotas ----

def quota_bump_revision(quota_policy) -> int:
    quota_policy.revision = (quota_policy.revision or 0) + 1
    return quota_policy.revision


# ---- usage snapshots ----

def _client_for(cluster: KubernetesCluster, credential_ref, run_settings):
    from app.services.kubernetes_cluster import get_client_for_cluster

    return get_client_for_cluster(cluster, credential_ref, run_settings)


def collect_usage(db: Session, cluster: KubernetesCluster, credential_ref, run_settings, *, client=None) -> dict:
    """One collection round via the kubelet Summary API (zero install)."""
    try:
        target = client if client is not None else _client_for(cluster, credential_ref, run_settings)
        nodes = target.list_nodes()
    except KubernetesClientError:
        db.add(
            ResourceUsageSnapshot(
                cluster_id=cluster.id,
                scope="cluster",
                subject="collection",
                metrics_json={"status": "stale"},
                collected_at=_utcnow(),
            )
        )
        db.commit()
        return {"status": "stale", "collected": 0, "truncated": False}

    max_per_scope = run_settings.governance_usage_max_per_scope
    now = _utcnow()
    rows: list[ResourceUsageSnapshot] = []
    truncated = False

    def status_row(status: str) -> ResourceUsageSnapshot:
        return ResourceUsageSnapshot(
            cluster_id=cluster.id,
            scope="cluster",
            subject="collection",
            metrics_json={"status": status},
            collected_at=now,
        )

    gpu_allocatable_total = 0
    try:
        for node in nodes:
            try:
                summary = target.node_summary(node["hostname"])
            except KubernetesClientError:
                db.add(status_row("stale"))
                db.commit()
                return {"status": "stale", "collected": 0, "truncated": False}
            node_info = summary.get("node") or {}
            cpu_nano = ((node_info.get("cpu") or {}).get("usageNanoCores")) or 0
            mem_bytes = ((node_info.get("memory") or {}).get("workingSetBytes")) or 0
            rows.append(
                ResourceUsageSnapshot(
                    cluster_id=cluster.id,
                    scope="node",
                    subject=node["hostname"],
                    metrics_json={
                        "cpu_cores": round(float(cpu_nano) / 1e9, 4),
                        "memory_gb": round(float(mem_bytes) / 1024**3, 4),
                        "allocatable_cpu_cores": node.get("cpu_cores"),
                    },
                    collected_at=now,
                )
            )
            try:
                gpu_allocatable_total += int(node.get("gpu") or 0)
            except (TypeError, ValueError):
                pass

            pods = summary.get("pods") or []
            if len(pods) > max_per_scope:
                pods = pods[:max_per_scope]
                truncated = True
            for pod in pods:
                ref = pod.get("podRef") or {}
                rows.append(
                    ResourceUsageSnapshot(
                        cluster_id=cluster.id,
                        scope="pod",
                        subject=str(ref.get("name") or "unknown")[:255],
                        metrics_json={
                            "namespace": ref.get("namespace"),
                            "cpu_cores": round(float((pod.get("cpu") or {}).get("usageNanoCores") or 0) / 1e9, 4),
                            "memory_gb": round(float((pod.get("memory") or {}).get("workingSetBytes") or 0) / 1024**3, 4),
                        },
                        collected_at=now,
                    )
                )
    except KubernetesClientError:
        db.add(status_row("stale"))
        db.commit()
        return {"status": "stale", "collected": 0, "truncated": False}

    rows.append(
        ResourceUsageSnapshot(
            cluster_id=cluster.id,
            scope="gpu",
            subject="cluster",
            metrics_json={
                "allocatable": str(gpu_allocatable_total),
                # Never fake GPU utilization: without a device-plugin metrics
                # endpoint the platform reports unavailable.
                "utilization": "unavailable",
            },
            collected_at=now,
        )
    )
    rows.append(status_row("collected"))

    for row in rows:
        db.add(row)
    db.commit()
    return {"status": "collected", "collected": len(rows), "truncated": truncated}


def usage_is_stale(db: Session, cluster: KubernetesCluster, run_settings) -> bool:
    latest = (
        db.query(ResourceUsageSnapshot)
        .filter(ResourceUsageSnapshot.cluster_id == cluster.id, ResourceUsageSnapshot.scope == "cluster")
        .order_by(ResourceUsageSnapshot.collected_at.desc())
        .first()
    )
    if latest is None:
        return True
    if (latest.metrics_json or {}).get("status") == "stale":
        return True
    collected = latest.collected_at if latest.collected_at.tzinfo is None else latest.collected_at.replace(tzinfo=None)
    return (_utcnow() - collected) > timedelta(seconds=run_settings.governance_snapshot_stale_seconds)


def prune_snapshots(db: Session, *, now: datetime | None = None) -> int:
    from app.config import settings

    cutoff = (now or _utcnow()) - timedelta(seconds=settings.governance_snapshot_retention_seconds)
    deleted = (
        db.query(ResourceUsageSnapshot)
        .filter(ResourceUsageSnapshot.collected_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


def release_expired_reservations(db: Session) -> list[str]:
    """Beat sweep re-export: reservations whose operation already finished."""
    from app.services.cluster_scheduler import release_expired_reservations as _sweep

    return _sweep(db)
