"""Allow annotation comments that apply to an entire task."""

from alembic import op
import sqlalchemy as sa


revision = "20260909_40"
down_revision = "20260909_39"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "annotation_comments" not in sa.inspect(bind).get_table_names():
        return
    with op.batch_alter_table("annotation_comments") as batch:
        batch.alter_column(
            "sample_id",
            existing_type=sa.String(length=256),
            nullable=True,
        )


def downgrade():
    bind = op.get_bind()
    if "annotation_comments" not in sa.inspect(bind).get_table_names():
        return
    null_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM annotation_comments WHERE sample_id IS NULL")
    ).scalar_one()
    if null_count:
        raise RuntimeError("TASK_LEVEL_COMMENTS_PRESENT")
    with op.batch_alter_table("annotation_comments") as batch:
        batch.alter_column(
            "sample_id",
            existing_type=sa.String(length=256),
            nullable=False,
        )
