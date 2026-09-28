"""Create Kubernetes control-plane resource tables for Week 13.

Four project-scoped tables: cluster registrations (credential references only,
never credential material), credential refs, namespaces and resource groups.
SQLite does not enforce VARCHAR widths or partial semantics used here, so the
migration is intentionally dialect-neutral.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260928_62"
down_revision = "20260926_61"
branch_labels = None
depends_on = None

CLUSTER_TABLES = (
    "kubernetes_resource_groups",
    "kubernetes_namespaces",
    "kubernetes_credential_refs",
    "kubernetes_clusters",
)


def upgrade() -> None:
    op.create_table(
        "kubernetes_clusters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("api_server_url", sa.Text(), nullable=False),
        sa.Column("insecure_tls", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="generic"),
        sa.Column("kubernetes_version", sa.String(length=32), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("default_namespace", sa.String(length=63), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("last_check_status", sa.String(length=24), nullable=True),
        sa.Column("last_check_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_check_message", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_check_latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Soft-deleted (archived) clusters release their name: uniqueness applies to
    # active rows only, enforced by a partial index in both dialects.
    op.create_index(
        "uq_kubernetes_cluster_active_name",
        "kubernetes_clusters",
        ["project_id", "name"],
        unique=True,
        sqlite_where=sa.text("archived_at IS NULL"),
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index("ix_kubernetes_clusters_project_id", "kubernetes_clusters", ["project_id"])
    op.create_index("ix_kubernetes_clusters_status", "kubernetes_clusters", ["status"])
    op.create_index("ix_kubernetes_clusters_last_checked_at", "kubernetes_clusters", ["last_checked_at"])

    op.create_table(
        "kubernetes_credential_refs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column("secret_ref", sa.String(length=255), nullable=False),
        sa.Column("ref_namespace", sa.String(length=63), nullable=True),
        sa.Column("allowed_use", sa.String(length=32), nullable=False, server_default="connectivity"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["kubernetes_clusters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kubernetes_credential_refs_cluster_id", "kubernetes_credential_refs", ["cluster_id"])

    op.create_table(
        "kubernetes_namespaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("quota_cpu_millicores", sa.Integer(), nullable=True),
        sa.Column("quota_memory_mb", sa.Integer(), nullable=True),
        sa.Column("quota_json", sa.JSON(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["kubernetes_clusters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_id", "name", name="uq_kubernetes_namespace_cluster_name"),
    )
    op.create_index("ix_kubernetes_namespaces_cluster_id", "kubernetes_namespaces", ["cluster_id"])
    op.create_index("ix_kubernetes_namespaces_project_id", "kubernetes_namespaces", ["project_id"])

    op.create_table(
        "kubernetes_resource_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("scheduling_policy_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("quota_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["kubernetes_clusters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_id", "project_id", "name", name="uq_kubernetes_resource_group_unique"),
    )
    op.create_index("ix_kubernetes_resource_groups_cluster_id", "kubernetes_resource_groups", ["cluster_id"])
    op.create_index("ix_kubernetes_resource_groups_project_id", "kubernetes_resource_groups", ["project_id"])


def downgrade() -> None:
    for table in CLUSTER_TABLES:
        op.drop_table(table)
