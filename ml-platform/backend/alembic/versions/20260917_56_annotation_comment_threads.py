"""Add annotation comment threads and resolution state."""

from alembic import op
import sqlalchemy as sa

revision = "20260917_56"
down_revision = "20260916_55"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("annotation_comments", sa.Column("parent_id", sa.Uuid(), nullable=True))
    op.add_column("annotation_comments", sa.Column("status", sa.String(length=24), nullable=True))
    op.add_column("annotation_comments", sa.Column("resolved_by", sa.Uuid(), nullable=True))
    op.add_column("annotation_comments", sa.Column("resolved_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE annotation_comments SET status = 'open' WHERE status IS NULL")
    with op.batch_alter_table("annotation_comments") as batch:
        batch.alter_column("status", nullable=False, server_default="open")
        batch.create_foreign_key("fk_annotation_comments_parent", "annotation_comments", ["parent_id"], ["id"])
        batch.create_foreign_key("fk_annotation_comments_resolved_by", "users", ["resolved_by"], ["id"])


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of annotation comment threads")
