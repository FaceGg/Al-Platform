"""Create the transition-safe generic annotation task boundary."""

from alembic import op
import sqlalchemy as sa


revision = "20260903_15"
down_revision = "20260829_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "generic_annotation_tasks" not in inspector.get_table_names():
        op.create_table(
            "generic_annotation_tasks",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("project_id", sa.UUID(), nullable=False),
            sa.Column("dataset_version_id", sa.UUID(), nullable=False),
            sa.Column("label_schema_id", sa.UUID(), nullable=False),
            sa.Column("owner_id", sa.UUID(), nullable=False),
            sa.Column("mode", sa.String(length=16), nullable=False, server_default="manual"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column("sample_scope", sa.JSON(), nullable=False),
            sa.Column("label_snapshot", sa.JSON(), nullable=False),
            sa.Column("source_legacy_id", sa.String(length=64), nullable=True),
            sa.Column("idempotency_key", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_legacy_id", name="uq_generic_annotation_task_source_legacy_id"),
            sa.UniqueConstraint("idempotency_key", name="uq_generic_annotation_task_idempotency_key"),
        )
    else:
        # Development databases may have been created by ``Base.metadata``
        # before this revision existed. Bring those partial tables forward
        # without dropping rows or requiring a destructive rebuild.
        existing_columns = {column["name"] for column in inspector.get_columns("generic_annotation_tasks")}
        missing_columns = {
            "dataset_version_id": sa.Column("dataset_version_id", sa.UUID(), nullable=True),
            "label_schema_id": sa.Column("label_schema_id", sa.UUID(), nullable=True),
            "source_legacy_id": sa.Column("source_legacy_id", sa.String(length=64), nullable=True),
            "idempotency_key": sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        }
        with op.batch_alter_table("generic_annotation_tasks") as batch_op:
            for name, column in missing_columns.items():
                if name not in existing_columns:
                    batch_op.add_column(column)
        inspector = sa.inspect(bind)

    existing_unique = {
        item.get("name") for item in inspector.get_unique_constraints("generic_annotation_tasks")
    }
    with op.batch_alter_table("generic_annotation_tasks") as batch_op:
        if "uq_generic_annotation_task_source_legacy_id" not in existing_unique:
            batch_op.create_unique_constraint(
                "uq_generic_annotation_task_source_legacy_id", ["source_legacy_id"]
            )
        if "uq_generic_annotation_task_idempotency_key" not in existing_unique:
            batch_op.create_unique_constraint(
                "uq_generic_annotation_task_idempotency_key", ["idempotency_key"]
            )

    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("generic_annotation_tasks")}
    for name, columns in {
        "ix_generic_annotation_tasks_project_id": ["project_id"],
        "ix_generic_annotation_tasks_dataset_version_id": ["dataset_version_id"],
        "ix_generic_annotation_tasks_label_schema_id": ["label_schema_id"],
        "ix_generic_annotation_tasks_owner_id": ["owner_id"],
        "ix_generic_annotation_tasks_source_legacy_id": ["source_legacy_id"],
        "ix_generic_annotation_tasks_idempotency_key": ["idempotency_key"],
    }.items():
        if name not in existing_indexes:
            op.create_index(name, "generic_annotation_tasks", columns, unique=False)


def downgrade() -> None:
    op.drop_table("generic_annotation_tasks")
