"""Bind annotation return batches to durable operations."""

from alembic import op
import sqlalchemy as sa


revision = "20260916_46"
down_revision = "20260916_45"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "annotation_return_batches" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("annotation_return_batches")}
    if "operation_id" not in columns:
        with op.batch_alter_table("annotation_return_batches") as batch:
            batch.add_column(sa.Column("operation_id", sa.Uuid(), nullable=True))
            batch.create_unique_constraint(
                "uq_annotation_return_batches_operation_id",
                ["operation_id"],
            )
            batch.create_foreign_key(
                "fk_annotation_return_batches_operation",
                "durable_operations",
                ["operation_id"],
                ["id"],
            )


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of annotation return operations")
