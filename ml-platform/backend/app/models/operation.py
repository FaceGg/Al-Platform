"""Durable, generic worker-operation state for long-running platform work."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class DurableOperation(Base):
    __tablename__ = "durable_operations"
    __table_args__ = (
        UniqueConstraint("resource_key", "idempotency_key", name="uq_durable_operations_resource_idempotency"),
        Index("ix_durable_operations_lease", "state", "lease_expires_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_key = Column(String(256), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    state = Column(String(24), nullable=False, default="queued")
    stage = Column(String(64), nullable=False, default="queued")
    progress = Column(Integer, nullable=False, default=0)
    attempt = Column(Integer, nullable=False, default=0)
    lease_owner = Column(String(128), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    result_artifact_id = Column(UUID(as_uuid=True), nullable=True)
    checksum = Column(String(71), nullable=True)
    result_summary = Column(JSON, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None), server_default=func.now(), nullable=False)
