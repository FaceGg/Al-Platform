"""Transactional notification configuration, outbox, and delivery models."""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


NOTIFICATION_ENDPOINT_KINDS = ("in_app", "wecom", "email", "webhook")
NOTIFICATION_SEVERITIES = ("info", "warning", "critical")
NOTIFICATION_OUTBOX_STATUSES = (
    "pending",
    "processing",
    "sent",
    "failed",
    "dead_letter",
)
NOTIFICATION_DELIVERY_STATUSES = (
    "pending",
    "processing",
    "sent",
    "retry",
    "failed",
    "dead_letter",
)


class NotificationEndpoint(Base):
    __tablename__ = "notification_endpoints"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('in_app', 'wecom', 'email', 'webhook')",
            name="ck_notification_endpoint_kind",
        ),
        UniqueConstraint(
            "project_id",
            "name",
            name="uq_notification_endpoint_project_name",
        ),
        Index(
            "ix_notification_endpoints_project_enabled",
            "project_id",
            "enabled",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(String(16), nullable=False)
    name = Column(String(128), nullable=False)
    destination_hint = Column(
        String(256),
        nullable=False,
        default="",
        server_default=text("''"),
    )
    encrypted_config = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    created_by_id = Column(
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


class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "minimum_severity IN ('info', 'warning', 'critical')",
            name="ck_notification_subscription_severity",
        ),
        Index(
            "ix_notification_subscription_project_enabled",
            "project_id",
            "enabled",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint_id = Column(
        UUID(as_uuid=True),
        ForeignKey("notification_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_types = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    minimum_severity = Column(
        String(16),
        nullable=False,
        default="info",
        server_default=text("'info'"),
    )
    recipient_roles = Column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    recipient_user_ids = Column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    created_by_id = Column(
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


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="ck_notification_outbox_severity",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'failed', 'dead_letter')",
            name="ck_notification_outbox_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_notification_outbox_attempts"),
        UniqueConstraint("event_id", name="uq_notification_outbox_event"),
        UniqueConstraint(
            "idempotency_key",
            name="uq_notification_outbox_idempotency",
        ),
        Index("ix_notification_outbox_due", "status", "next_attempt_at"),
        Index(
            "ix_notification_outbox_project_created",
            "project_id",
            "created_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), nullable=False)
    idempotency_key = Column(String(256), nullable=False)
    event_type = Column(String(128), nullable=False)
    severity = Column(String(16), nullable=False)
    occurred_at = Column(DateTime, nullable=False)
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
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(128), nullable=True)
    payload = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    status = Column(
        String(16),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    next_attempt_at = Column(DateTime, nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    last_error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'retry', 'failed', 'dead_letter')",
            name="ck_notification_delivery_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_notification_delivery_attempts"),
        UniqueConstraint(
            "idempotency_key",
            name="uq_notification_delivery_idempotency",
        ),
        Index("ix_notification_delivery_due", "status", "next_attempt_at"),
        Index("ix_notification_delivery_outbox", "outbox_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outbox_id = Column(
        UUID(as_uuid=True),
        ForeignKey("notification_outbox.id", ondelete="CASCADE"),
        nullable=False,
    )
    subscription_id = Column(
        UUID(as_uuid=True),
        ForeignKey("notification_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    endpoint_id = Column(
        UUID(as_uuid=True),
        ForeignKey("notification_endpoints.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key = Column(String(64), nullable=False)
    status = Column(
        String(16),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    next_attempt_at = Column(DateTime, nullable=True)
    claim_token = Column(String(36), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    provider_status = Column(Integer, nullable=True)
    provider_metadata = Column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    last_error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class InAppNotification(Base):
    __tablename__ = "in_app_notifications"
    __table_args__ = (
        UniqueConstraint(
            "deduplication_key",
            name="uq_in_app_notification_deduplication",
        ),
        CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="ck_in_app_notification_severity",
        ),
        Index(
            "ix_in_app_notification_recipient_created",
            "recipient_user_id",
            "created_at",
        ),
        Index("ix_in_app_notification_project_created", "project_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipient_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_id = Column(UUID(as_uuid=True), nullable=False)
    event_type = Column(String(128), nullable=False)
    deduplication_key = Column(String(64), nullable=True)
    severity = Column(String(16), nullable=False)
    title = Column(String(256), nullable=False)
    body = Column(Text, nullable=False)
    payload = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    read_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
