"""Create Week 16 resource-governance tables (routing, bindings, quotas,
reservations, usage snapshots)."""

from alembic import op
import sqlalchemy as sa

revision = "20261010_67"
down_revision = "20261008_66"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cluster_routing_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "priority", name="uq_cluster_routing_policies_project_priority"),
    )
    op.create_index("ix_cluster_routing_policies_project_id", "cluster_routing_policies", ["project_id"])

    op.create_table(
        "storage_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("pvc_name", sa.String(length=255), nullable=True),
        sa.Column("object_prefix", sa.String(length=255), nullable=True),
        sa.Column("access", sa.String(length=16), nullable=False, server_default="read_only"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cluster_id"], ["kubernetes_clusters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_storage_bindings_project_id", "storage_bindings", ["project_id"])
    op.create_index("ix_storage_bindings_cluster_id", "storage_bindings", ["cluster_id"])

    op.create_table(
        "resource_quota_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("quota_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "scope_id", name="uq_resource_quota_policies_scope"),
    )

    op.create_table(
        "resource_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("quota_policy_id", sa.Uuid(), nullable=True),
        sa.Column("reserved_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("release_reason", sa.String(length=16), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cluster_id"], ["kubernetes_clusters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operation_id"], ["durable_operations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quota_policy_id"], ["resource_quota_policies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", name="uq_resource_reservations_operation"),
    )
    op.create_index("ix_resource_reservations_project_id", "resource_reservations", ["project_id"])
    op.create_index("ix_resource_reservations_cluster_id", "resource_reservations", ["cluster_id"])
    op.create_index("ix_resource_reservations_operation_id", "resource_reservations", ["operation_id"], unique=True)
    op.create_index("ix_resource_reservations_state", "resource_reservations", ["state"])

    op.create_table(
        "resource_usage_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("collected_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["kubernetes_clusters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_resource_usage_snapshots_cluster_scope",
        "resource_usage_snapshots",
        ["cluster_id", "scope", "collected_at"],
    )
    op.create_index("ix_resource_usage_snapshots_cluster_id", "resource_usage_snapshots", ["cluster_id"])


def downgrade() -> None:
    op.drop_index("ix_resource_usage_snapshots_cluster_id", table_name="resource_usage_snapshots")
    op.drop_table("resource_usage_snapshots")
    op.drop_table("resource_reservations")
    op.drop_table("resource_quota_policies")
    op.drop_table("storage_bindings")
    op.drop_table("cluster_routing_policies")
