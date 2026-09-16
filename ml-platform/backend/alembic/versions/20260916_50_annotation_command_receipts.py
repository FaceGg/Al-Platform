"""Persist annotation command fingerprints and assignment pause origins."""

from alembic import op
import sqlalchemy as sa


revision = "20260916_50"
down_revision = "20260916_49"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "durable_operations" in tables:
        columns = {item["name"] for item in inspector.get_columns("durable_operations")}
        if "request_fingerprint" not in columns:
            with op.batch_alter_table("durable_operations") as batch:
                batch.add_column(sa.Column("request_fingerprint", sa.String(length=64), nullable=True))

    if "annotation_assignments" in tables:
        columns = {item["name"] for item in inspector.get_columns("annotation_assignments")}
        if "paused_from_state" not in columns:
            with op.batch_alter_table("annotation_assignments") as batch:
                batch.add_column(sa.Column("paused_from_state", sa.String(length=32), nullable=True))


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of annotation command receipts")
