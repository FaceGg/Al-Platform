"""Add reversible archive state to generic platform resources."""

from alembic import op
import sqlalchemy as sa


revision = "20260916_45"
down_revision = "20260915_44"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for table, column in (
        ("artifacts", "archived_at"),
        ("dataset_versions", "archived_at"),
        ("generic_annotation_tasks", "archived_at"),
    ):
        if table not in inspector.get_table_names():
            continue
        columns = {item["name"] for item in inspector.get_columns(table)}
        if column not in columns:
            op.add_column(table, sa.Column(column, sa.DateTime(), nullable=True))
        existing_indexes = {item["name"] for item in inspector.get_indexes(table)}
        if table == "artifacts" and "ix_artifacts_archived_at" not in existing_indexes:
            op.create_index("ix_artifacts_archived_at", table, ["archived_at"])
        elif table == "generic_annotation_tasks" and "ix_generic_annotation_tasks_archived_at" not in existing_indexes:
            op.create_index("ix_generic_annotation_tasks_archived_at", table, ["archived_at"])


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of archive state")
