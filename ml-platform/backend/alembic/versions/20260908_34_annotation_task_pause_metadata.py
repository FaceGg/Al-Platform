"""Persist the generic annotation task pause restore state."""

from alembic import op
import sqlalchemy as sa


revision = "20260908_34"
down_revision = "20260908_33"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("generic_annotation_tasks")}
    if "paused_from_status" not in columns:
        with op.batch_alter_table("generic_annotation_tasks") as batch:
            batch.add_column(sa.Column("paused_from_status", sa.String(length=24), nullable=True))


def downgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("generic_annotation_tasks")}
    if "paused_from_status" in columns:
        with op.batch_alter_table("generic_annotation_tasks") as batch:
            batch.drop_column("paused_from_status")
