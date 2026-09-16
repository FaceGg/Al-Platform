"""Freeze the complete label set for each annotation return batch."""

from alembic import op
import sqlalchemy as sa


revision = "20260916_53"
down_revision = "20260916_52"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "annotation_return_batch_samples" in inspector.get_table_names():
        return
    op.create_table(
        "annotation_return_batch_samples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("return_batch_id", sa.Uuid(), nullable=False),
        sa.Column("sample_id", sa.String(length=256), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["return_batch_id"],
            ["annotation_return_batches.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "return_batch_id",
            "sample_id",
            name="uq_annotation_return_batch_sample",
        ),
    )
    op.create_index(
        "ix_annotation_return_batch_samples_page",
        "annotation_return_batch_samples",
        ["return_batch_id", "sample_id", "id"],
    )


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of frozen annotation return samples")
