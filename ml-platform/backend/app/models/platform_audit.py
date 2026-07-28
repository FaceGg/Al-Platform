"""Append-only platform security audit records."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class PlatformAuditEvent(Base):
    __tablename__ = "platform_audit_events"
    __table_args__ = (
        CheckConstraint(
            "result IN ('success', 'denied', 'failed')",
            name="ck_platform_audit_result",
        ),
        Index("ix_platform_audit_created", "created_at"),
        Index("ix_platform_audit_action_created", "action", "created_at"),
        Index("ix_platform_audit_actor_created", "actor_id", "created_at"),
        Index("ix_platform_audit_request_id", "request_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_username = Column(String(64), nullable=False)
    action = Column(String(128), nullable=False)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(128), nullable=True)
    result = Column(String(16), nullable=False)
    request_id = Column(UUID(as_uuid=True), nullable=False)
    source_ip = Column(String(64), nullable=True)
    changes = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
