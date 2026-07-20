"""Project collaboration memberships and append-only audit events."""

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


PROJECT_MEMBER_ROLES = ("editor", "operator", "viewer")
AUDIT_RESULTS = ("success", "denied", "failed")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "user_id",
            name="uq_project_members_project_user",
        ),
        CheckConstraint(
            "role IN ('editor', 'operator', 'viewer')",
            name="ck_project_members_role",
        ),
        Index("ix_project_members_user_project", "user_id", "project_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(16), nullable=False)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "result IN ('success', 'denied', 'failed')",
            name="ck_audit_events_result",
        ),
        Index("ix_audit_events_project_created", "project_id", "created_at"),
        Index(
            "ix_audit_events_project_action_created",
            "project_id",
            "action",
            "created_at",
        ),
        Index(
            "ix_audit_events_project_actor_created",
            "project_id",
            "actor_id",
            "created_at",
        ),
        Index("ix_audit_events_request_id", "request_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
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
    changes = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
