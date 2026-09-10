"""Bind model exports to durable operations and one-time download state."""
from alembic import op
import sqlalchemy as sa

revision = "20260909_39"
down_revision = "20260909_38"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "model_exports" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("model_exports")}
    with op.batch_alter_table("model_exports") as batch:
        if "operation_id" not in columns:
            batch.add_column(sa.Column("operation_id", sa.Uuid(), nullable=True))
        if "download_used_at" not in columns:
            batch.add_column(sa.Column("download_used_at", sa.DateTime(), nullable=True))
        try:
            batch.create_unique_constraint("uq_model_exports_operation_id", ["operation_id"])
        except Exception:
            pass

def downgrade():
    pass
