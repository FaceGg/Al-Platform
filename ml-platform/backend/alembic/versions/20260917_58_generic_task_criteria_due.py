"""Add completion criteria and due date to generic annotation tasks.

Revision ID: 20260917_58
Revises: 20260917_57
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa

revision = "20260917_58"
down_revision = "20260917_57"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "generic_annotation_tasks",
        sa.Column("completion_criteria", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "generic_annotation_tasks",
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of generic task criteria and due dates")
