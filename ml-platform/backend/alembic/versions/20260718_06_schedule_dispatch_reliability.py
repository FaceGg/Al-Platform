"""Add durable schedule retry and workflow timeout metadata."""

from alembic import op
import sqlalchemy as sa


revision = "20260718_06"
down_revision = "20260718_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pipeline_schedule_runs",
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_pipeline_schedule_runs_retry",
        "pipeline_schedule_runs",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pipeline_schedule_runs_retry",
        table_name="pipeline_schedule_runs",
    )
    op.drop_column("pipeline_schedule_runs", "next_attempt_at")
    op.drop_column("workflow_runs", "timeout_seconds")
