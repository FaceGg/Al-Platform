"""Add durable dataset import workflow state for schema confirmation."""

from alembic import op
import sqlalchemy as sa


revision = "20260915_44"
down_revision = "20260910_43"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dataset_import_processes" in inspector.get_table_names():
        return
    op.create_table(
        "dataset_import_processes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("confirmation_operation_id", sa.Uuid(), nullable=True),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("source_name", sa.String(length=512), nullable=False),
        sa.Column("source_format", sa.String(length=32), nullable=False),
        sa.Column("parse_options", sa.JSON(), nullable=False),
        sa.Column("parse_contract", sa.JSON(), nullable=True),
        sa.Column("inferred_schema", sa.JSON(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("schema_hash", sa.String(length=128), nullable=True),
        sa.Column("original_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["operation_id"], ["durable_operations.id"]),
        sa.ForeignKeyConstraint(["confirmation_operation_id"], ["durable_operations.id"]),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"]),
        sa.ForeignKeyConstraint(["original_artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["normalized_artifact_id"], ["artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", name="uq_dataset_import_process_operation"),
        sa.UniqueConstraint("confirmation_operation_id", name="uq_dataset_import_process_confirmation_operation"),
        sa.UniqueConstraint("dataset_version_id", name="uq_dataset_import_process_dataset_version"),
    )
    op.create_index(
        "ix_dataset_import_processes_project_id",
        "dataset_import_processes",
        ["project_id"],
    )
    op.create_index(
        "ix_dataset_import_processes_status",
        "dataset_import_processes",
        ["status"],
    )


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of dataset import processes")
