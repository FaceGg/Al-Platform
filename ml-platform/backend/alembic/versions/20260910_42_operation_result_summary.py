"""Persist generic operation result summaries."""

from alembic import op
import sqlalchemy as sa


revision = "20260910_42"
down_revision = "20260910_41"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("durable_operations")}
    if "result_summary" not in columns:
        op.add_column("durable_operations", sa.Column("result_summary", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("durable_operations")}
    if "result_summary" in columns:
        op.drop_column("durable_operations", "result_summary")
