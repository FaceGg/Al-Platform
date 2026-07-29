"""Add platform security audit and transactional notification persistence."""

from alembic import op
import sqlalchemy as sa


revision = "20260720_10_security_notifications"
down_revision = "20260720_09_production_inference"
branch_labels = None
depends_on = None


def _set_alembic_version_column_length(*, existing_length: int, length: int) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("alembic_version") as batch_op:
            batch_op.alter_column(
                "version_num",
                existing_type=sa.String(length=existing_length),
                type_=sa.String(length=length),
                existing_nullable=False,
            )
        return

    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=existing_length),
        type_=sa.String(length=length),
        existing_nullable=False,
    )


def _restore_alembic_version_column_after_downgrade(*, ctx, step, heads, run_args) -> None:
    if (
        step.is_upgrade
        or step.up_revision_id != revision
        or step.down_revision_ids != (down_revision,)
        or set(heads) != {down_revision}
    ):
        return
    _set_alembic_version_column_length(existing_length=64, length=32)


def upgrade() -> None:
    # Alembic creates this table with VARCHAR(32), but this revision is 34 chars.
    _set_alembic_version_column_length(existing_length=32, length=64)

    op.create_table(
        "platform_audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_username", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "result IN ('success', 'denied', 'failed')",
            name="ck_platform_audit_result",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_platform_audit_created", "platform_audit_events", ["created_at"])
    op.create_index(
        "ix_platform_audit_action_created",
        "platform_audit_events",
        ["action", "created_at"],
    )
    op.create_index(
        "ix_platform_audit_actor_created",
        "platform_audit_events",
        ["actor_id", "created_at"],
    )
    op.create_index(
        "ix_platform_audit_request_id",
        "platform_audit_events",
        ["request_id"],
    )

    op.create_table(
        "notification_endpoints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "destination_hint",
            sa.String(length=256),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("encrypted_config", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "kind IN ('in_app', 'wecom', 'email', 'webhook')",
            name="ck_notification_endpoint_kind",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "name",
            name="uq_notification_endpoint_project_name",
        ),
    )
    op.create_index(
        "ix_notification_endpoints_project_enabled",
        "notification_endpoints",
        ["project_id", "enabled"],
    )

    op.create_table(
        "notification_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("endpoint_id", sa.UUID(), nullable=False),
        sa.Column("event_types", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "minimum_severity",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'info'"),
        ),
        sa.Column(
            "recipient_roles",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "recipient_user_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "minimum_severity IN ('info', 'warning', 'critical')",
            name="ck_notification_subscription_severity",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["notification_endpoints.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notification_subscription_project_enabled",
        "notification_subscriptions",
        ["project_id", "enabled"],
    )

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="ck_notification_outbox_severity",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'failed', 'dead_letter')",
            name="ck_notification_outbox_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_notification_outbox_attempts"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_notification_outbox_event"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_notification_outbox_idempotency",
        ),
    )
    op.create_index(
        "ix_notification_outbox_due",
        "notification_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_notification_outbox_project_created",
        "notification_outbox",
        ["project_id", "created_at"],
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("outbox_id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column("endpoint_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claim_token", sa.String(length=36), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("provider_status", sa.Integer(), nullable=True),
        sa.Column(
            "provider_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'retry', 'failed', 'dead_letter')",
            name="ck_notification_delivery_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_notification_delivery_attempts"),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["notification_endpoints.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["outbox_id"],
            ["notification_outbox.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["notification_subscriptions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_notification_delivery_idempotency",
        ),
    )
    op.create_index(
        "ix_notification_delivery_due",
        "notification_deliveries",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_notification_delivery_outbox",
        "notification_deliveries",
        ["outbox_id"],
    )

    op.create_table(
        "in_app_notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recipient_user_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("deduplication_key", sa.String(length=64), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="ck_in_app_notification_severity",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "deduplication_key",
            name="uq_in_app_notification_deduplication",
        ),
    )
    op.create_index(
        "ix_in_app_notification_recipient_created",
        "in_app_notifications",
        ["recipient_user_id", "created_at"],
    )
    op.create_index(
        "ix_in_app_notification_project_created",
        "in_app_notifications",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_in_app_notification_project_created",
        table_name="in_app_notifications",
    )
    op.drop_index(
        "ix_in_app_notification_recipient_created",
        table_name="in_app_notifications",
    )
    op.drop_table("in_app_notifications")
    op.drop_index("ix_notification_delivery_outbox", table_name="notification_deliveries")
    op.drop_index("ix_notification_delivery_due", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_index(
        "ix_notification_outbox_project_created",
        table_name="notification_outbox",
    )
    op.drop_index("ix_notification_outbox_due", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    op.drop_index(
        "ix_notification_subscription_project_enabled",
        table_name="notification_subscriptions",
    )
    op.drop_table("notification_subscriptions")
    op.drop_index(
        "ix_notification_endpoints_project_enabled",
        table_name="notification_endpoints",
    )
    op.drop_table("notification_endpoints")
    op.drop_index("ix_platform_audit_request_id", table_name="platform_audit_events")
    op.drop_index(
        "ix_platform_audit_actor_created",
        table_name="platform_audit_events",
    )
    op.drop_index(
        "ix_platform_audit_action_created",
        table_name="platform_audit_events",
    )
    op.drop_index("ix_platform_audit_created", table_name="platform_audit_events")
    op.drop_table("platform_audit_events")

    migration_context = op.get_context()
    callbacks = list(migration_context.on_version_apply_callbacks)
    callbacks.append(_restore_alembic_version_column_after_downgrade)
    migration_context.on_version_apply_callbacks = callbacks
