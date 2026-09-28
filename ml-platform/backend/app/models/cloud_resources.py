"""Kubernetes control-plane resources registered per project (Week 13 foundation).

Cluster credentials are stored as references only (``env:NAME`` / ``file:/path``);
no token, kubeconfig or certificate material is ever persisted in these tables.
"""
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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

_ACTIVE_NAME_CLAUSE = text("archived_at IS NULL")


class KubernetesCluster(Base):
    __tablename__ = "kubernetes_clusters"
    __table_args__ = (
        Index(
            "uq_kubernetes_cluster_active_name",
            "project_id",
            "name",
            unique=True,
            sqlite_where=_ACTIVE_NAME_CLAUSE,
            postgresql_where=_ACTIVE_NAME_CLAUSE,
        ),
        Index("ix_kubernetes_clusters_status", "status"),
        Index("ix_kubernetes_clusters_last_checked_at", "last_checked_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    display_name = Column(String(128), nullable=False, default="")
    api_server_url = Column(Text, nullable=False)
    insecure_tls = Column(Boolean, nullable=False, default=False)
    provider = Column(String(32), nullable=False, default="generic")
    kubernetes_version = Column(String(32), nullable=True)
    capabilities = Column(JSON, nullable=True)
    default_namespace = Column(String(63), nullable=True)
    status = Column(String(24), nullable=False, default="pending")
    last_check_status = Column(String(24), nullable=True)
    last_check_error_code = Column(String(64), nullable=True)
    last_check_message = Column(Text, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_check_latency_ms = Column(Integer, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())
    archived_at = Column(DateTime, nullable=True)


class KubernetesCredentialRef(Base):
    __tablename__ = "kubernetes_credential_refs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("kubernetes_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    secret_ref = Column(String(255), nullable=False)
    ref_namespace = Column(String(63), nullable=True)
    allowed_use = Column(String(32), nullable=False, default="connectivity")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())


class KubernetesNamespace(Base):
    __tablename__ = "kubernetes_namespaces"
    __table_args__ = (
        UniqueConstraint("cluster_id", "name", name="uq_kubernetes_namespace_cluster_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("kubernetes_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(63), nullable=False)
    status = Column(String(24), nullable=False, default="pending")
    quota_cpu_millicores = Column(Integer, nullable=True)
    quota_memory_mb = Column(Integer, nullable=True)
    quota_json = Column(JSON, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())


class KubernetesResourceGroup(Base):
    __tablename__ = "kubernetes_resource_groups"
    __table_args__ = (
        UniqueConstraint("cluster_id", "project_id", "name", name="uq_kubernetes_resource_group_unique"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("kubernetes_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    description = Column(String(255), nullable=False, default="")
    scheduling_policy_json = Column(JSON, nullable=False, default=dict)
    quota_json = Column(JSON, nullable=False, default=dict)
    status = Column(String(24), nullable=False, default="active")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())
