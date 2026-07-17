"""Add durable workflow task metadata."""

from alembic import op
import sqlalchemy as sa

revision = "20260715_03"
down_revision = "20260715_02"
branch_labels = None
depends_on = None


def upgrade():
    for name, length in (("task_id", 128), ("queue_name", 64), ("worker_id", 128)):
        op.add_column("workflow_runs", sa.Column(name, sa.String(length), nullable=True))
    op.add_column("workflow_runs", sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
    op.create_index("ix_workflow_runs_task_id", "workflow_runs", ["task_id"], unique=False)


def downgrade():
    op.drop_index("ix_workflow_runs_task_id", table_name="workflow_runs")
    op.drop_column("workflow_runs", "heartbeat_at")
    op.drop_column("workflow_runs", "worker_id")
    op.drop_column("workflow_runs", "queue_name")
    op.drop_column("workflow_runs", "task_id")
