"""Add immutable generic dataset versions and import metadata."""
from alembic import op
import sqlalchemy as sa

revision = "20260902_15"
down_revision = "20260829_14"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dataset_versions" not in inspector.get_table_names():
        op.create_table("dataset_versions", sa.Column("id", sa.UUID(), primary_key=True), sa.Column("project_id", sa.UUID(), nullable=False), sa.Column("operator_id", sa.UUID(), nullable=False), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("status", sa.String(24), nullable=False, server_default="ready"), sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("content_hash", sa.String(128), nullable=False), sa.Column("schema_hash", sa.String(128), nullable=False), sa.Column("parse_contract", sa.JSON(), nullable=False), sa.Column("original_artifact_id", sa.UUID()), sa.Column("normalized_artifact_id", sa.UUID()), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["operator_id"], ["users.id"]), sa.ForeignKeyConstraint(["original_artifact_id"], ["artifacts.id"]), sa.ForeignKeyConstraint(["normalized_artifact_id"], ["artifacts.id"]))
    for table, columns in {
        "dataset_schema_columns": [("id", sa.UUID(), False), ("dataset_version_id", sa.UUID(), False), ("name", sa.String(256), False), ("position", sa.Integer(), False), ("dtype", sa.String(64), False), ("nullable", sa.Boolean(), False)],
        "dataset_samples": [("id", sa.UUID(), False), ("dataset_version_id", sa.UUID(), False), ("sample_id", sa.String(256), False), ("row_index", sa.Integer(), False), ("values", sa.JSON(), False)],
        "dataset_imports": [("id", sa.UUID(), False), ("dataset_version_id", sa.UUID(), False), ("source_format", sa.String(32), False), ("parse_contract", sa.JSON(), False), ("content_hash", sa.String(128), False), ("schema_hash", sa.String(128), False), ("created_at", sa.DateTime(), False)],
    }.items():
        if table in inspector.get_table_names():
            continue
        cols = [sa.Column(name, typ, primary_key=(name == "id"), nullable=nullable, server_default=sa.func.now() if name == "created_at" else None) for name, typ, nullable in columns]
        cols.append(sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"], ondelete="CASCADE"))
        op.create_table(table, *cols)
    inspector = sa.inspect(bind)
    for table, column in (
        ("dataset_versions", "project_id"),
        ("dataset_schema_columns", "dataset_version_id"),
        ("dataset_samples", "dataset_version_id"),
        ("dataset_imports", "dataset_version_id"),
    ):
        index_name = f"ix_{table}_{column}"
        if table in inspector.get_table_names() and index_name not in {item["name"] for item in inspector.get_indexes(table)}:
            op.create_index(index_name, table, [column], unique=False)

def downgrade():
    raise RuntimeError("Refusing destructive downgrade of immutable dataset versions")
