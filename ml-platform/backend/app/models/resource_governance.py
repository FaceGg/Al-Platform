"""Week 16 resource governance: multi-cluster routing policies, storage
bindings, quota policies, reservations and usage snapshots."""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class ClusterRoutingPolicy(Base):
    __tablename__ = "cluster_routing_policies"
    __table_args__ = (
        UniqueConstraint("project_id", "priority", name="uq_cluster_routing_policies_project_priority"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    priority = Column(Integer, nullable=False)
    policy_json = Column(JSON, nullable=False, default=dict)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())


class StorageBinding(Base):
    __tablename__ = "storage_bindings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("kubernetes_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    mode = Column(String(16), nullable=False)  # pvc | object_prefix
    pvc_name = Column(String(255), nullable=True)
    object_prefix = Column(String(255), nullable=True)
    access = Column(String(16), nullable=False, default="read_only")  # read_only | read_write
    status = Column(String(24), nullable=False, default="active")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())


class ResourceQuotaPolicy(Base):
    __tablename__ = "resource_quota_policies"
    __table_args__ = (
        UniqueConstraint("scope", "scope_id", name="uq_resource_quota_policies_scope"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope = Column(String(16), nullable=False)  # project | resource_group
    scope_id = Column(UUID(as_uuid=True), nullable=False)
    quota_json = Column(JSON, nullable=False, default=dict)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())


class ResourceReservation(Base):
    __tablename__ = "resource_reservations"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_resource_reservations_operation"),
        Index("ix_resource_reservations_state", "state"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("kubernetes_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_id = Column(UUID(as_uuid=True), ForeignKey("durable_operations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    quota_policy_id = Column(UUID(as_uuid=True), ForeignKey("resource_quota_policies.id", ondelete="SET NULL"), nullable=True)
    reserved_json = Column(JSON, nullable=False, default=dict)
    state = Column(String(16), nullable=False, default="active")  # active | released | expired
    release_reason = Column(String(16), nullable=True)  # terminal | orphaned | expired | manual
    released_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())


class ResourceUsageSnapshot(Base):
    __tablename__ = "resource_usage_snapshots"
    __table_args__ = (
        Index("ix_resource_usage_snapshots_cluster_scope", "cluster_id", "scope", "collected_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("kubernetes_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    scope = Column(String(16), nullable=False)  # cluster | node | pod | gpu
    subject = Column(String(255), nullable=False)
    metrics_json = Column(JSON, nullable=False, default=dict)
    truncated = Column(Boolean, nullable=False, default=False)
    collected_at = Column(DateTime, server_default=func.now(), nullable=False)
