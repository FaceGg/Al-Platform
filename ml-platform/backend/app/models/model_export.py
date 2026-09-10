"""Persistent state for reproducible model export operations."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class ModelExport(Base):
    __tablename__ = "model_exports"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_scope",
            "idempotency_key",
            name="uq_model_exports_idempotency",
        ),
        Index(
            "ix_model_exports_model_version_status",
            "model_version_id",
            "status",
            "created_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_version_id = Column(UUID(as_uuid=True), ForeignKey("model_versions.id", ondelete="CASCADE"), nullable=False)
    annotation_task_id = Column(UUID(as_uuid=True), nullable=True)
    annotation_task_revision = Column(Integer, nullable=True)
    idempotency_scope = Column(String(256), nullable=False, default="model")
    include_runtime = Column(Boolean, nullable=False, default=True)
    idempotency_key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False, default="")
    operation_id = Column(UUID(as_uuid=True), nullable=True, unique=True)
    download_used_at = Column(DateTime, nullable=True)
    status = Column(String(24), nullable=False, default="queued")
    package_path = Column(String(1024), nullable=True)
    manifest_sha256 = Column(String(64), nullable=True)
    error = Column(JSON, nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
