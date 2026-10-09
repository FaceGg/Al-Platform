"""Week 15 GPU scheduler: closed mapping from GPU requests to verified
capacity. Every failure mode is an explicit typed error; environments without
GPU report ``skipped`` semantics instead of fake success."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.cloud_resources import KubernetesCluster
from app.models.developer_resources import GpuResourceClass
from app.services.kubernetes_client import KubernetesClientError
from app.services.kubernetes_executor import KubeJobError

GPU_RESOURCE_NAME = "nvidia.com/gpu"
ALLOWED_SELECTOR_KEY_PREFIXES = ("linkraft.io/", "app.kubernetes.io/")
ALLOWED_TOLERATION_EFFECTS = ("NoSchedule", "PreferNoSchedule", "NoExecute")
ALLOWED_TOLERATION_OPERATORS = ("Exists", "Equal")


def resolve_class(db: Session, cluster_id, name: str) -> GpuResourceClass:
    gpu_class = (
        db.query(GpuResourceClass)
        .filter(GpuResourceClass.cluster_id == cluster_id, GpuResourceClass.name == name)
        .first()
    )
    if gpu_class is None or gpu_class.status != "active":
        raise KubeJobError("GPU_CLASS_UNAVAILABLE", f"GPU class {name} is missing or not active", status=422)
    return gpu_class


def _gpu_allocatable(client) -> int:
    total = 0
    for node in client.list_nodes():
        value = str(node.get("gpu", "0"))
        try:
            total += int(value)
        except (TypeError, ValueError):
            continue
    return total


def verify_capacity(db: Session, client, gpu_class: GpuResourceClass, *, requested: int) -> int:
    """Re-verify allocatable capacity; refreshes a stale snapshot first."""
    if requested > gpu_class.max_per_session:
        raise KubeJobError(
            "GPU_PER_SESSION_LIMIT",
            f"requested {requested} GPUs exceeds per-session cap {gpu_class.max_per_session}",
            status=422,
        )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    snapshotted = gpu_class.snapshotted_at
    if snapshotted is not None and snapshotted.tzinfo is not None:
        snapshotted = snapshotted.replace(tzinfo=None)
    stale = snapshotted is None or (now - snapshotted) > timedelta(seconds=30)
    try:
        allocatable = _gpu_allocatable(client)
    except KubernetesClientError as error:
        raise KubeJobError(error.code, error.message, status=502) from error
    if stale:
        gpu_class.allocatable_snapshot_json = {"allocatable": allocatable}
        gpu_class.snapshotted_at = now
        db.commit()
    if allocatable <= 0 or allocatable < requested:
        raise KubeJobError(
            "GPU_CAPACITY_EXCEEDED",
            f"cluster reports {allocatable} allocatable GPUs, requested {requested}",
            status=422,
        )
    return allocatable


def validate_selector(selector: dict) -> dict:
    cleaned: dict = {}
    for key, value in (selector or {}).items():
        if not isinstance(key, str) or not (
            key.startswith(ALLOWED_SELECTOR_KEY_PREFIXES)
        ):
            raise KubeJobError(
                "GPU_SELECTOR_FORBIDDEN",
                f"node selector key {key} is not a platform-controlled value",
                status=422,
            )
        if not isinstance(value, str) or not value:
            raise KubeJobError("GPU_SELECTOR_FORBIDDEN", "node selector values must be non-empty strings", status=422)
        cleaned[key] = value
    return cleaned


def validate_tolerations(tolerations: list) -> list:
    cleaned = []
    for item in (tolerations or []):
        if not isinstance(item, dict):
            raise KubeJobError("GPU_TOLERATION_FORBIDDEN", "tolerations must be objects", status=422)
        effect = item.get("effect")
        operator = item.get("operator", "Exists")
        if effect not in ALLOWED_TOLERATION_EFFECTS or operator not in ALLOWED_TOLERATION_OPERATORS:
            raise KubeJobError(
                "GPU_TOLERATION_FORBIDDEN",
                f"toleration effect/operator {(effect, operator)} is not platform-controlled",
                status=422,
            )
        cleaned.append(
            {
                "key": str(item.get("key", "")),
                "operator": operator,
                "effect": effect,
                **({"value": str(item["value"])} if item.get("value") is not None else {}),
            }
        )
    return cleaned


def build_injection(gpu_class: GpuResourceClass, *, requested: int) -> dict:
    """Compose the pod-level GPU injection from a verified resource class."""
    selector = validate_selector(dict(gpu_class.node_selector_json or {}))
    tolerations = validate_tolerations(list(gpu_class.tolerations_json or []))
    return {
        "resources": {
            "limits": {gpu_class.resource_name: requested},
            "requests": {gpu_class.resource_name: requested},
        },
        "node_selector": selector,
        "tolerations": tolerations,
    }


def probe_gpu_nodes(client) -> dict:
    """Skipped-semantics probe: never fakes availability."""
    try:
        allocatable = _gpu_allocatable(client)
    except KubernetesClientError as error:
        return {"available": False, "semantics": "skipped", "reason": error.code, "allocatable": 0}
    if allocatable <= 0:
        return {
            "available": False,
            "semantics": "skipped",
            "reason": "no NVIDIA device plugin / GPU nodes in cluster",
            "allocatable": 0,
        }
    return {"available": True, "semantics": "available", "reason": None, "allocatable": allocatable}
