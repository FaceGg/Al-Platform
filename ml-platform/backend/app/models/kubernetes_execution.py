"""Week 14 Kubernetes batch execution models (Job/Pod closed loop)."""

import uuid

from sqlalchemy import (
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
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class KubernetesJobRun(Base):
    __tablename__ = "kubernetes_job_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_kubernetes_job_run_idempotency"),
        Index("ix_kubernetes_job_runs_status", "status"),
        Index("ix_kubernetes_job_runs_cluster_created", "cluster_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("kubernetes_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    namespace = Column(String(63), nullable=False)
    operation_id = Column(UUID(as_uuid=True), ForeignKey("durable_operations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    task_id = Column(UUID(as_uuid=True), nullable=True)
    idempotency_key = Column(String(128), nullable=False)
    job_name = Column(String(128), nullable=False)
    image_ref = Column(String(512), nullable=False)
    command_json = Column(JSON, nullable=False, default=list)
    args_json = Column(JSON, nullable=False, default=list)
    env_json = Column(JSON, nullable=False, default=dict)
    resource_json = Column(JSON, nullable=False, default=dict)
    input_bindings_json = Column(JSON, nullable=False, default=list)
    output_bindings_json = Column(JSON, nullable=False, default=list)
    status = Column(String(24), nullable=False, default="queued")
    status_detail = Column(Text, nullable=True)
    error_code = Column(String(64), nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    timeout_seconds = Column(Integer, nullable=False)
    exit_code = Column(Integer, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())
