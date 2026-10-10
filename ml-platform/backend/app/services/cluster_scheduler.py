"""Week 16 multi-cluster router and resource reservations.

Routing is deterministic and fail-closed: candidates are the project's active,
non-stale clusters; policies narrow and order them; every excluded cluster
carries an explicit reason. With no policy and a single eligible cluster the
router degrades to ``default_single_cluster`` — Week 13–15 behavior unchanged.

Reservations are the DB-side anti-oversell channel: one active row per durable
operation, aggregate ``SUM(active) + request <= quota`` inside the insert
transaction, and idempotent release from the executor's terminal paths or the
expired sweep.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.cloud_resources import KubernetesCluster
from app.models.resource_governance import (
    ClusterRoutingPolicy,
    ResourceQuotaPolicy,
    ResourceReservation,
)
from app.services.kubernetes_client import redact_text
from app.services.kubernetes_executor import KubeJobError

RESERVED_KEYS = ("cpu_cores", "memory_mb", "gpu_count")
ALLOWED_QUOTA_KEYS = (
    "cpu_cores",
    "memory_mb",
    "gpu_count",
    "storage_gb",
    "max_concurrent_jobs",
    "max_concurrent_notebooks",
    "notebook_idle_seconds",
)


@dataclass
class RoutingDecision:
    selected_cluster_id: uuid.UUID | None
    reason: str
    policy_revision: int | None
    candidates: list[dict] = field(default_factory=list)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _gpu_capacity(cluster: KubernetesCluster) -> int:
    capabilities = cluster.capabilities or {}
    try:
        return int(capabilities.get("gpu") or 0)
    except (TypeError, ValueError):
        return 0


def route(
    db: Session,
    project_id,
    *,
    cpu_cores: int | float = 1,
    gpu_count: int = 0,
    region: str | None = None,
    required_capabilities: list[str] | None = None,
    preview: bool = False,
) -> RoutingDecision:
    """Deterministic, explainable cluster selection for a project."""
    stale_before = _utcnow() - timedelta(seconds=300)
    clusters = (
        db.query(KubernetesCluster)
        .filter(
            KubernetesCluster.project_id == project_id,
            KubernetesCluster.archived_at.is_(None),
        )
        .order_by(KubernetesCluster.created_at, KubernetesCluster.id)
        .all()
    )
    candidates: list[dict] = []
    eligible: list[KubernetesCluster] = []
    for cluster in clusters:
        reason = None
        if cluster.status != "active":
            reason = "cluster_not_active"
        elif cluster.last_checked_at is None or cluster.last_checked_at < stale_before:
            reason = "stale_check"
        elif gpu_count > 0 and _gpu_capacity(cluster) < gpu_count:
            reason = "no_gpu_capacity"
        else:
            capabilities = cluster.capabilities or {}
            for required in required_capabilities or []:
                if not capabilities.get(required):
                    reason = f"capability_missing:{required}"
                    break
        if region is not None:
            capabilities = cluster.capabilities or {}
            if reason is None and capabilities.get("region") != region:
                reason = "region_mismatch"
        candidates.append(
            {
                "cluster_id": str(cluster.id),
                "name": cluster.name,
                "excluded": reason is not None,
                "reason": reason,
            }
        )
        if reason is None:
            eligible.append(cluster)

    policies = (
        db.query(ClusterRoutingPolicy)
        .filter(ClusterRoutingPolicy.project_id == project_id)
        .order_by(ClusterRoutingPolicy.priority)
        .all()
    )

    if not eligible:
        raise KubeJobError(
            "NO_ELIGIBLE_CLUSTER",
            "no healthy cluster satisfies the request",
            status=422,
        )

    if not policies:
        selected = eligible[0]
        reason = "default_single_cluster" if len(eligible) == 1 else "cost_min"
        return RoutingDecision(selected.id, reason, None, candidates)

    policy = policies[0]
    policy_json = policy.policy_json or {}
    wanted_region = region or policy_json.get("region")
    if wanted_region:
        regional = [
            cluster
            for cluster in eligible
            if (cluster.capabilities or {}).get("region") == wanted_region
        ]
        if regional:
            selected = regional[0]
            return RoutingDecision(selected.id, "region_match", policy.revision, candidates)

    if gpu_count > 0:
        gpu_clusters = [cluster for cluster in eligible if _gpu_capacity(cluster) >= gpu_count]
        if gpu_clusters:
            return RoutingDecision(gpu_clusters[0].id, "capability_match", policy.revision, candidates)

    def cost_key(cluster: KubernetesCluster):
        capabilities = cluster.capabilities or {}
        try:
            cost = float(policy_json.get("cost_weight", {}).get(cluster.name, 0) or 0)
        except (TypeError, ValueError, AttributeError):
            cost = 0
        return (cost, str(cluster.id))

    selected = sorted(eligible, key=cost_key)[0]
    return RoutingDecision(selected.id, "cost_min", policy.revision, candidates)


def validate_quota_json(quota_json: dict) -> dict:
    cleaned: dict = {}
    for key, value in (quota_json or {}).items():
        if key not in ALLOWED_QUOTA_KEYS:
            raise KubeJobError("QUOTA_KEY_INVALID", f"quota key {key} is not allowed", status=422)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise KubeJobError("QUOTA_VALUE_INVALID", f"quota value for {key} must be a non-negative number", status=422)
        cleaned[key] = value
    return cleaned


def _active_sum(db: Session, column, scope_filter) -> float:
    value = (
        db.query(func.coalesce(func.sum(ResourceReservation.reserved_json[column].as_float(), ), 0.0))
        .join(
            ResourceQuotaPolicy,
            ResourceQuotaPolicy.id == ResourceReservation.quota_policy_id,
        )
        .filter(
            ResourceReservation.state == "active",
            ResourceQuotaPolicy.scope == "project",
            *scope_filter,
        )
        .scalar()
    )
    return float(value or 0.0)


def reserve(
    db: Session,
    *,
    project_id,
    cluster_id,
    operation_id,
    reserved_json: dict,
) -> ResourceReservation:
    """Create the DB-side reservation; aggregate check guards the quota.

    Raises ``QUOTA_EXCEEDED`` when any quota key would be oversold. The
    unique ``operation_id`` constraint makes the "one active reservation per
    operation" rule hold under concurrency.
    """
    cleaned = {}
    for key in RESERVED_KEYS:
        value = reserved_json.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise KubeJobError("QUOTA_VALUE_INVALID", f"reserved {key} must be a non-negative number", status=422)
        cleaned[key] = value

    quota_policy = (
        db.query(ResourceQuotaPolicy)
        .filter(ResourceQuotaPolicy.scope == "project", ResourceQuotaPolicy.scope_id == project_id)
        .first()
    )
    if quota_policy is not None:
        # Serialize concurrent reserves on the quota row: SQLite takes a write
        # lock up front, PostgreSQL row-locks via FOR UPDATE.
        from sqlalchemy import text

        if db.bind is not None and db.bind.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        else:
            quota_policy = (
                db.query(ResourceQuotaPolicy)
                .filter(
                    ResourceQuotaPolicy.scope == "project",
                    ResourceQuotaPolicy.scope_id == project_id,
                )
                .with_for_update()
                .first()
            )
        quota = quota_policy.quota_json or {}
        for key in RESERVED_KEYS:
            limit = quota.get(key)
            if limit is None:
                continue
            active_sum = (
                db.query(
                    func.coalesce(
                        func.sum(cast_json_number(ResourceReservation.reserved_json, key)),
                        0.0,
                    )
                )
                .filter(
                    ResourceReservation.quota_policy_id == quota_policy.id,
                    ResourceReservation.state == "active",
                )
                .scalar()
            )
            if float(active_sum or 0) + float(cleaned[key]) > float(limit):
                db.rollback()
                raise KubeJobError(
                    "QUOTA_EXCEEDED",
                    f"project quota for {key} exceeded: {active_sum}+{cleaned[key]}/{limit}",
                    status=422,
                )
    try:
        reservation = ResourceReservation(
            project_id=project_id,
            cluster_id=cluster_id,
            operation_id=operation_id,
            quota_policy_id=quota_policy.id if quota_policy is not None else None,
            reserved_json=cleaned,
            state="active",
        )
        db.add(reservation)
        db.commit()
        db.refresh(reservation)
        return reservation
    except Exception as error:  # noqa: BLE001 - unique violation under race
        db.rollback()
        if "uq_resource_reservations_operation" in str(error).lower() or "unique" in str(error).lower():
            raise KubeJobError("RESERVATION_DUPLICATE", "operation already holds a reservation", status=409) from error
        raise


def cast_json_number(json_column, key: str):
    """SQLite/PostgreSQL portable JSON number extraction as float."""
    from sqlalchemy import cast, Float, type_coerce

    return cast(json_column[key], Float)


def release_reservation(db: Session, operation_id, reason: str) -> bool:
    """Idempotent release; repeated calls keep the first terminal write."""
    if reason not in ("terminal", "orphaned", "expired", "manual"):
        raise ValueError("RESERVATION_REASON_INVALID")
    reservation = (
        db.query(ResourceReservation)
        .filter(ResourceReservation.operation_id == operation_id, ResourceReservation.state == "active")
        .first()
    )
    if reservation is None:
        return False
    reservation.state = "released"
    reservation.release_reason = reason
    reservation.released_at = _utcnow()
    db.commit()
    return True


def release_expired_reservations(db: Session) -> list[str]:
    """Beat sweep: release reservations whose operation already reached a
    terminal state (crash window between terminal write and release)."""
    from app.models.operation import DurableOperation

    rows = (
        db.query(ResourceReservation, DurableOperation.state)
        .join(DurableOperation, DurableOperation.id == ResourceReservation.operation_id)
        .filter(ResourceReservation.state == "active", DurableOperation.state.in_(("completed", "failed", "cancelled")))
        .all()
    )
    swept: list[str] = []
    for reservation, _state in rows:
        reservation.state = "expired"
        reservation.release_reason = "expired"
        reservation.released_at = _utcnow()
        swept.append(str(reservation.operation_id))
    if swept:
        db.commit()
    return swept


def redact_reservation(reservation: ResourceReservation) -> dict:
    return {
        "id": str(reservation.id),
        "project_id": str(reservation.project_id),
        "cluster_id": str(reservation.cluster_id),
        "operation_id": str(reservation.operation_id),
        "reserved_json": reservation.reserved_json,
        "state": reservation.state,
        "release_reason": reservation.release_reason,
    }
