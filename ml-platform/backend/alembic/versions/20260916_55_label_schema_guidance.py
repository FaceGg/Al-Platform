"""Add schema purpose and column-level annotation guidance."""

from alembic import op
import sqlalchemy as sa


revision = "20260916_55"
down_revision = "20260916_54"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "label_schemas",
        sa.Column("purpose", sa.String(length=32), nullable=True),
    )
    op.execute("UPDATE label_schemas SET purpose = 'annotation' WHERE purpose IS NULL")
    with op.batch_alter_table("label_schemas") as batch:
        batch.alter_column("purpose", nullable=False, server_default="annotation")
    op.add_column(
        "label_columns",
        sa.Column("instruction", sa.Text(), nullable=True),
    )


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of label schema guidance")
