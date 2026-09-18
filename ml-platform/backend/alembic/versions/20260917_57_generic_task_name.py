"""Add a human-readable name to generic annotation tasks."""

from alembic import op
import sqlalchemy as sa

revision = "20260917_57"
down_revision = "20260917_56"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("generic_annotation_tasks", sa.Column("name", sa.String(length=200), nullable=False, server_default=""))


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of generic task names")
