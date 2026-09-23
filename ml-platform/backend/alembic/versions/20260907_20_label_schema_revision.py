"""Add generic label schemas and immutable annotation revisions."""

from alembic import op
import sqlalchemy as sa


revision = "20260907_20"
down_revision = "20260905_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "label_schemas" not in tables:
        op.create_table(
            "label_schemas",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "name", "version", name="uq_label_schema_project_name_version"),
        )
    if "label_columns" not in tables:
        op.create_table(
            "label_columns",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("schema_id", sa.Uuid(), nullable=False),
            sa.Column("machine_key", sa.String(128), nullable=False),
            sa.Column("display_name", sa.String(256), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("value_type", sa.String(16), nullable=False),
            sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("enum_values", sa.JSON(), nullable=False),
            sa.Column("min_value", sa.JSON(), nullable=True),
            sa.Column("max_value", sa.JSON(), nullable=True),
            sa.Column("max_length", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["schema_id"], ["label_schemas.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("schema_id", "machine_key", name="uq_label_column_schema_key"),
        )
    if "annotation_sample_current" not in tables:
        op.create_table(
            "annotation_sample_current",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("task_id", sa.Uuid(), nullable=False),
            sa.Column("sample_id", sa.String(256), nullable=False),
            sa.Column("schema_id", sa.Uuid(), nullable=False),
            sa.Column("revision_no", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("values", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["schema_id"], ["label_schemas.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id", "sample_id", name="uq_annotation_sample_current_task_sample"),
        )
    if "annotation_revisions" not in tables:
        op.create_table(
            "annotation_revisions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("task_id", sa.Uuid(), nullable=False),
            sa.Column("sample_id", sa.String(256), nullable=False),
            sa.Column("schema_id", sa.Uuid(), nullable=False),
            sa.Column("revision_no", sa.Integer(), nullable=False),
            sa.Column("base_revision", sa.Integer(), nullable=False),
            sa.Column("values", sa.JSON(), nullable=False),
            sa.Column("author_id", sa.Uuid(), nullable=False),
            sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
            sa.Column("action", sa.String(32), nullable=False, server_default="edit"),
            sa.Column("provenance_ref", sa.String(256), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["schema_id"], ["label_schemas.id"]),
            sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
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
    for table in ("annotation_revisions", "annotation_sample_current", "label_columns", "label_schemas"):
        if table in inspector.get_table_names():
            op.drop_table(table)
