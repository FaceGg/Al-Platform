"""Create demo_loop_configs and demo_loop_events for the closed-loop demo."""

from alembic import op
import sqlalchemy as sa

revision = "20261001_64"
down_revision = "20260928_63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_loop_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False, server_default="闭环演示"),
        sa.Column("deployment_id", sa.Uuid(), nullable=True),
        sa.Column("error_classes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("preprocess_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("alert_threshold_rows", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("require_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("review_annotator_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("retrain_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("retrain_threshold_rows", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("retrain_dataset_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("retrain_target_column", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("retrain_max_trials", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("error_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("alert_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("review_task_id", sa.Uuid(), nullable=True),
        sa.Column("retrain_job_id", sa.Uuid(), nullable=True),
        sa.Column("retrain_status", sa.String(length=24), nullable=False, server_default="idle"),
        sa.Column("swapped_model_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("alert_threshold_rows >= 1", name="ck_demo_loop_alert_threshold"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deployment_id"], ["inference_deployments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["retrain_dataset_artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_demo_loop_configs_project_id", "demo_loop_configs", ["project_id"])
    op.create_index("ix_demo_loop_configs_error_artifact_id", "demo_loop_configs", ["error_artifact_id"])

    op.create_table(
        "demo_loop_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("config_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["config_id"], ["demo_loop_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_demo_loop_events_config_created", "demo_loop_events", ["config_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_demo_loop_events_config_created", table_name="demo_loop_events")
    op.drop_table("demo_loop_events")
    op.drop_index("ix_demo_loop_configs_error_artifact_id", table_name="demo_loop_configs")
    op.drop_index("ix_demo_loop_configs_project_id", table_name="demo_loop_configs")
    op.drop_table("demo_loop_configs")
