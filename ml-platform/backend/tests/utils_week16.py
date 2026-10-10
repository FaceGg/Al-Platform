"""Shared row factories for the Week 16 resource-governance test modules."""

import sys

sys.path.insert(0, ".")

from datetime import datetime, timezone  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.resource_governance import (  # noqa: E402
    ClusterRoutingPolicy,
    ResourceQuotaPolicy,
)

SCOPE_CPU_QUOTA = {"cpu_cores": 4, "memory_mb": 8192, "max_concurrent_jobs": 8}


def ensure_routing_policy(project_id, priority: int = 1, policy_json: dict | None = None):
    db = SessionLocal()
    try:
        policy = (
            db.query(ClusterRoutingPolicy)
            .filter(ClusterRoutingPolicy.project_id == project_id, ClusterRoutingPolicy.priority == priority)
            .first()
        )
        if policy is None:
            policy = ClusterRoutingPolicy(
                project_id=project_id,
                priority=priority,
                policy_json=policy_json or {},
                revision=1,
            )
            db.add(policy)
            db.commit()
            db.refresh(policy)
        return policy
    finally:
        db.close()


def ensure_quota_policy(scope: str, scope_id, quota_json: dict | None = None):
    db = SessionLocal()
    try:
        quota = (
            db.query(ResourceQuotaPolicy)
            .filter(ResourceQuotaPolicy.scope == scope, ResourceQuotaPolicy.scope_id == scope_id)
            .first()
        )
        if quota is None:
            quota = ResourceQuotaPolicy(
                scope=scope,
                scope_id=scope_id,
                quota_json=quota_json or dict(SCOPE_CPU_QUOTA),
                revision=1,
            )
            db.add(quota)
        else:
            # Force the requested values so tests never inherit stale quotas.
            quota.quota_json = quota_json or dict(SCOPE_CPU_QUOTA)
            quota.revision = 1
        db.commit()
        db.refresh(quota)
        return quota
    finally:
        db.close()


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_operation(op_id, project_id, state: str = "running"):
    """Create the durable operation row reservations hang off (FK target)."""
    from app.models.operation import DurableOperation

    db = SessionLocal()
    try:
        operation = db.get(DurableOperation, op_id)
        if operation is None:
            operation = DurableOperation(
                id=op_id,
                project_id=project_id,
                resource_type="kubernetes_job",
                resource_key=f"w16:{op_id}",
                idempotency_key=f"w16-op-{op_id}",
                state=state,
                stage=state,
            )
            db.add(operation)
            db.commit()
        return operation
    finally:
        db.close()


def cleanup_week16_rows() -> None:
    from app.models.operation import DurableOperation
    from app.models.resource_governance import (
        ClusterRoutingPolicy,
        ResourceQuotaPolicy,
        ResourceReservation,
        ResourceUsageSnapshot,
        StorageBinding,
    )

    db = SessionLocal()
    try:
        db.query(ResourceReservation).delete(synchronize_session=False)
        db.query(ResourceUsageSnapshot).delete(synchronize_session=False)
        db.query(StorageBinding).delete(synchronize_session=False)
        db.query(ClusterRoutingPolicy).delete(synchronize_session=False)
        db.query(ResourceQuotaPolicy).delete(synchronize_session=False)
        db.query(DurableOperation).filter(DurableOperation.resource_key.like("w16:%")).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
