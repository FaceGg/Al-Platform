"""Week 15 developer resources: Notebook sessions, the immutable image
catalog, build records and GPU resource classes."""

import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class NotebookSession(Base):
    __tablename__ = "notebook_sessions"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_notebook_sessions_operation"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_notebook_sessions_idempotency"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("kubernetes_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    namespace = Column(String(63), nullable=False)
    operation_id = Column(UUID(as_uuid=True), ForeignKey("durable_operations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    idempotency_key = Column(String(128), nullable=False)
    job_name = Column(String(128), nullable=False)
    image_ref = Column(String(512), nullable=False)
    resource_json = Column(JSON, nullable=False, default=dict)
    status = Column(String(24), nullable=False, default="starting")
    access_path = Column(String(255), nullable=True)
    idle_timeout_seconds = Column(Integer, nullable=False, default=3600)
    error_code = Column(String(64), nullable=True)
    last_activity_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    terminated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())


class ContainerImage(Base):
    __tablename__ = "container_images"
    __table_args__ = (
        UniqueConstraint("registry", "repository", "digest", name="uq_container_images_digest"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    registry = Column(String(255), nullable=False)
    repository = Column(String(255), nullable=False)
    digest = Column(String(71), nullable=False)
    visibility = Column(String(16), nullable=False, default="project")
    scan_status = Column(String(16), nullable=False, default="unknown")
    scan_report_ref = Column(String(255), nullable=True)
    source = Column(String(16), nullable=False, default="manual_registry")
    description = Column(String(255), nullable=True, default="")
    registered_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())


class ImageBuild(Base):
    __tablename__ = "image_builds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_artifact_id = Column(UUID(as_uuid=True), nullable=True)
    builder_image = Column(String(512), nullable=False)
    operation_id = Column(UUID(as_uuid=True), ForeignKey("durable_operations.id", ondelete="SET NULL"), nullable=True, unique=True, index=True)
    status = Column(String(24), nullable=False, default="queued")
    log_ref = Column(String(255), nullable=True)
    output_image_id = Column(UUID(as_uuid=True), ForeignKey("container_images.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())


class GpuResourceClass(Base):
    __tablename__ = "gpu_resource_classes"
    __table_args__ = (
        UniqueConstraint("cluster_id", "name", name="uq_gpu_resource_classes_cluster_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("kubernetes_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    resource_name = Column(String(64), nullable=False, default="nvidia.com/gpu")
    memory_gb = Column(Integer, nullable=True)
    vendor = Column(String(32), nullable=True)
    node_selector_json = Column(JSON, nullable=False, default=dict)
    tolerations_json = Column(JSON, nullable=False, default=list)
    max_per_session = Column(Integer, nullable=False, default=1)
    status = Column(String(24), nullable=False, default="active")
    allocatable_snapshot_json = Column(JSON, nullable=True)
    snapshotted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False, onupdate=func.now())
