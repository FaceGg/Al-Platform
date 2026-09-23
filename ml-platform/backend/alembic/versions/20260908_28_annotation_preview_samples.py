"""Persist preview sample rows."""

from alembic import op
import sqlalchemy as sa

revision = "20260908_28"
down_revision = "20260908_27"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("annotation_task_preview_samples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("preview_id", sa.Uuid(), nullable=False),
        sa.Column("sample_id", sa.String(length=256), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["preview_id"], ["annotation_task_previews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("preview_id", "sample_id", name="uq_annotation_preview_sample"),
    )
    op.create_index("ix_annotation_preview_samples_preview", "annotation_task_preview_samples", ["preview_id", "row_index"])


def downgrade():
    op.drop_index("ix_annotation_preview_samples_preview", table_name="annotation_task_preview_samples")
    op.drop_table("annotation_task_preview_samples")
