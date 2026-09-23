"""Add preview progress fields."""

from alembic import op
import sqlalchemy as sa

revision = "20260908_27"
down_revision = "20260908_26"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("annotation_task_previews", sa.Column("progress", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("annotation_task_previews", sa.Column("error", sa.JSON(), nullable=True))
    op.add_column("annotation_task_previews", sa.Column("completed_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("annotation_task_previews", "completed_at")
    op.drop_column("annotation_task_previews", "error")
    op.drop_column("annotation_task_previews", "progress")
