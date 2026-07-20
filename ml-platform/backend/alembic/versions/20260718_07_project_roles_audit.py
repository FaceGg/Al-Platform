"""Add project collaboration roles and append-only audit events."""

from alembic import op
import sqlalchemy as sa


revision = "20260718_07"
down_revision = "20260718_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "role IN ('editor', 'operator', 'viewer')",
            name="ck_project_members_role",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "user_id",
            name="uq_project_members_project_user",
        ),
    )
    op.create_index(
        "ix_project_members_user_project",
        "project_members",
        ["user_id", "project_id"],
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_username", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "result IN ('success', 'denied', 'failed')",
            name="ck_audit_events_result",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_project_created",
        "audit_events",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_audit_events_project_action_created",
        "audit_events",
        ["project_id", "action", "created_at"],
    )
    op.create_index(
        "ix_audit_events_project_actor_created",
        "audit_events",
        ["project_id", "actor_id", "created_at"],
    )
    op.create_index(
        "ix_audit_events_request_id",
        "audit_events",
        ["request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_request_id", table_name="audit_events")
    op.drop_index(
        "ix_audit_events_project_actor_created",
        table_name="audit_events",
    )
    op.drop_index(
        "ix_audit_events_project_action_created",
        table_name="audit_events",
    )
    op.drop_index("ix_audit_events_project_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(
        "ix_project_members_user_project",
        table_name="project_members",
    )
    op.drop_table("project_members")
