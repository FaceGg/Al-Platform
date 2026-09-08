"""Add immutable generic annotation task snapshot."""

from alembic import op
import sqlalchemy as sa

revision = "20260908_26"
down_revision = "20260907_25"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("generic_annotation_tasks", sa.Column("task_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))


def downgrade():
    op.drop_column("generic_annotation_tasks", "task_snapshot")
