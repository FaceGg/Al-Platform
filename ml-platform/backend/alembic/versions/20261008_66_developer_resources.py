"""Create Week 15 developer-resource tables (notebooks, images, builds, GPU classes)."""

from alembic import op
import sqlalchemy as sa

revision = "20261008_66"
down_revision = "20261006_65"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notebook_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column("namespace", sa.String(length=63), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("job_name", sa.String(length=128), nullable=False),
        sa.Column("image_ref", sa.String(length=512), nullable=False),
        sa.Column("resource_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="starting"),
        sa.Column("access_path", sa.String(length=255), nullable=True),
        sa.Column("idle_timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("3600")),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("terminated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["cluster_id"], ["kubernetes_clusters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operation_id"], ["durable_operations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", name="uq_notebook_sessions_operation"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_notebook_sessions_idempotency"),
    )
    op.create_index("ix_notebook_sessions_project_id", "notebook_sessions", ["project_id"])
    op.create_index("ix_notebook_sessions_user_id", "notebook_sessions", ["user_id"])
    op.create_index("ix_notebook_sessions_cluster_id", "notebook_sessions", ["cluster_id"])
    op.create_index("ix_notebook_sessions_operation_id", "notebook_sessions", ["operation_id"], unique=True)

    op.create_table(
        "container_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("registry", sa.String(length=255), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("digest", sa.String(length=71), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="project"),
        sa.Column("scan_status", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("scan_report_ref", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="manual_registry"),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("registered_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["registered_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registry", "repository", "digest", name="uq_container_images_digest"),
    )
    op.create_index("ix_container_images_project_id", "container_images", ["project_id"])

    op.create_table(
        "image_builds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("builder_image", sa.String(length=512), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("log_ref", sa.String(length=255), nullable=True),
        sa.Column("output_image_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operation_id"], ["durable_operations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["output_image_id"], ["container_images.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_image_builds_project_id", "image_builds", ["project_id"])
    op.create_index("ix_image_builds_operation_id", "image_builds", ["operation_id"], unique=True)

    op.create_table(
        "gpu_resource_classes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("resource_name", sa.String(length=64), nullable=False, server_default="nvidia.com/gpu"),
        sa.Column("memory_gb", sa.Integer(), nullable=True),
        sa.Column("vendor", sa.String(length=32), nullable=True),
        sa.Column("node_selector_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("tolerations_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("max_per_session", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("allocatable_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("snapshotted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["kubernetes_clusters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_id", "name", name="uq_gpu_resource_classes_cluster_name"),
    )
    op.create_index("ix_gpu_resource_classes_cluster_id", "gpu_resource_classes", ["cluster_id"])


def downgrade() -> None:
    op.drop_index("ix_gpu_resource_classes_cluster_id", table_name="gpu_resource_classes")
    op.drop_table("gpu_resource_classes")
    op.drop_table("image_builds")
    op.drop_table("container_images")
    op.drop_table("notebook_sessions")
