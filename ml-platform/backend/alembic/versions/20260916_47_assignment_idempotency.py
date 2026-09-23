"""Persist idempotency keys for generic annotation assignments."""

from alembic import op
import sqlalchemy as sa


revision = "20260916_47"
down_revision = "20260916_46"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "annotation_assignments" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("annotation_assignments")}
    if "idempotency_key" not in columns:
        with op.batch_alter_table("annotation_assignments") as batch:
            batch.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
            batch.create_unique_constraint(
                "uq_annotation_assignment_idempotency",
                ["task_id", "created_by", "idempotency_key"],
            )


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of assignment idempotency")
