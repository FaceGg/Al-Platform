"""Backfill label schema indexes for databases upgraded by 20260907_20."""

from alembic import op
import sqlalchemy as sa


revision = "20260907_21"
down_revision = "20260907_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, name, columns in (
        ("label_columns", "ix_label_columns_schema_ordinal", ["schema_id", "ordinal"]),
        ("annotation_sample_current", "ix_annotation_sample_current_task", ["task_id"]),
        ("annotation_revisions", "ix_annotation_revisions_sample_revision", ["task_id", "sample_id", "revision_no"]),
    ):
        if name not in {item["name"] for item in inspector.get_indexes(table)}:
            op.create_index(name, table, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, name in (("label_columns", "ix_label_columns_schema_ordinal"), ("annotation_sample_current", "ix_annotation_sample_current_task"), ("annotation_revisions", "ix_annotation_revisions_sample_revision")):
        if table in inspector.get_table_names() and name in {item["name"] for item in inspector.get_indexes(table)}:
            op.drop_index(name, table_name=table)
