"""Create kubernetes_job_runs for the Week 14 batch execution closed loop."""

from alembic import op
import sqlalchemy as sa

revision = "20260928_63"
down_revision = "20260928_62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kubernetes_job_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column("namespace", sa.String(length=63), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("job_name", sa.String(length=128), nullable=False),
        sa.Column("image_ref", sa.String(length=512), nullable=False),
        sa.Column("command_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("args_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("env_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("resource_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("input_bindings_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("output_bindings_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cluster_id"], ["kubernetes_clusters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operation_id"], ["durable_operations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_kubernetes_job_run_idempotency"),
        sa.UniqueConstraint("operation_id", name="uq_kubernetes_job_run_operation"),
    )
    op.create_index("ix_kubernetes_job_runs_project_id", "kubernetes_job_runs", ["project_id"])
    op.create_index("ix_kubernetes_job_runs_cluster_id", "kubernetes_job_runs", ["cluster_id"])
    op.create_index("ix_kubernetes_job_runs_status", "kubernetes_job_runs", ["status"])


def downgrade() -> None:
    op.drop_table("kubernetes_job_runs")
