"""Persist durable-operation ownership and annotation resource context."""

from alembic import op
import sqlalchemy as sa
import uuid


revision = "20260916_48"
down_revision = "20260916_47"
branch_labels = None
depends_on = None


def _columns(bind, table_name):
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _batches(bind, statement, key):
    marker = None
    while True:
        page = statement if marker is None else statement.where(key > marker)
        rows = bind.execute(page.order_by(key).limit(200)).mappings().all()
        if not rows:
            return
        yield from rows
        marker = rows[-1][key.name]


def _backfill_annotation_context(bind):
    # Historical SQLite UUID declarations do not round-trip through reflection.
    operations = sa.table(
        "durable_operations",
        *(sa.column(name, sa.Uuid()) for name in ("id", "project_id", "task_id", "preview_id")),
        sa.column("resource_key", sa.String()), sa.column("idempotency_key", sa.String()),
        sa.column("resource_type", sa.String()),
    )
    previews = sa.table(
        "annotation_task_previews",
        *(sa.column(name, sa.Uuid()) for name in ("id", "task_id", "operation_id")),
        sa.column("task_revision", sa.Integer()),
    )
    tasks = sa.table(
        "generic_annotation_tasks",
        sa.column("id", sa.Uuid()), sa.column("project_id", sa.Uuid()),
    )

    preview_rows = _batches(bind,
        sa.select(
            previews.c.operation_id,
            previews.c.id,
            previews.c.id.label("preview_id"),
            tasks.c.id.label("task_id"),
            tasks.c.project_id,
        ).select_from(previews.join(tasks, tasks.c.id == previews.c.task_id)),
        previews.c.id,
    )
    for row in preview_rows:
        bind.execute(
            operations.update().where(operations.c.id == row["operation_id"]).values(
                project_id=row["project_id"],
                task_id=row["task_id"],
                preview_id=row["preview_id"],
                resource_type="annotation_preview",
            )
        )

    execution_rows = _batches(bind,
        sa.select(operations.c.id, operations.c.resource_key, operations.c.idempotency_key).where(
            operations.c.resource_key.like("annotation-execution:%")
        ),
        operations.c.id,
    )
    for row in execution_rows:
        try:
            task_id = uuid.UUID(str(row["resource_key"]).split(":", 1)[1])
            revision_token, preview_token = str(row["idempotency_key"]).split(":", 1)
            preview_id = uuid.UUID(preview_token)
            task_revision = int(revision_token)
        except (AttributeError, IndexError, ValueError, TypeError):
            continue
        project_id = bind.execute(
            sa.select(tasks.c.project_id).select_from(
                tasks.join(previews, previews.c.task_id == tasks.c.id)
            ).where(
                tasks.c.id == task_id, previews.c.id == preview_id,
                previews.c.task_revision == task_revision,
            )
        ).scalar_one_or_none()
        if project_id is None:
            continue
        bind.execute(
            operations.update().where(operations.c.id == row["id"]).values(
                project_id=project_id,
                task_id=task_id,
                preview_id=preview_id,
                resource_type="annotation_execution",
            )
        )

    if not {"annotation_return_batches", "annotation_assignments"}.issubset(
        sa.inspect(bind).get_table_names()
    ):
        return
    assignments = sa.table(
        "annotation_assignments", sa.column("id", sa.Uuid()), sa.column("task_id", sa.Uuid()),
    )
    returns = sa.table(
        "annotation_return_batches",
        *(sa.column(name, sa.Uuid()) for name in ("id", "operation_id", "assignment_id")),
    )
    return_rows = _batches(bind,
        sa.select(
            returns.c.id,
            returns.c.operation_id,
            tasks.c.id.label("task_id"),
            tasks.c.project_id,
        ).select_from(
            returns.join(assignments, assignments.c.id == returns.c.assignment_id).join(
                tasks, tasks.c.id == assignments.c.task_id
            )
        ).where(returns.c.operation_id.is_not(None)),
        returns.c.id,
    )
    for row in return_rows:
        bind.execute(
            operations.update().where(operations.c.id == row["operation_id"]).values(
                project_id=row["project_id"],
                task_id=row["task_id"],
                resource_type="annotation_return",
            )
        )


def upgrade():
    bind = op.get_bind()
    columns = _columns(bind, "durable_operations")
    if not columns:
        return
    with op.batch_alter_table("durable_operations") as batch:
        if "project_id" not in columns:
            batch.add_column(sa.Column("project_id", sa.Uuid(), nullable=True))
            batch.create_foreign_key(
                "fk_durable_operations_project",
                "projects",
                ["project_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "task_id" not in columns:
            batch.add_column(sa.Column("task_id", sa.Uuid(), nullable=True))
            batch.create_foreign_key(
                "fk_durable_operations_task",
                "generic_annotation_tasks",
                ["task_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "preview_id" not in columns:
            batch.add_column(sa.Column("preview_id", sa.Uuid(), nullable=True))
            batch.create_foreign_key(
                "fk_durable_operations_preview",
                "annotation_task_previews",
                ["preview_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "resource_type" not in columns:
            batch.add_column(sa.Column("resource_type", sa.String(length=64), nullable=True))
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("durable_operations")}
        if "ix_durable_operations_project_created" not in indexes:
            batch.create_index(
                "ix_durable_operations_project_created",
                ["project_id", "created_at", "id"],
            )
        if "ix_durable_operations_task_created" not in indexes:
            batch.create_index(
                "ix_durable_operations_task_created",
                ["task_id", "created_at", "id"],
            )
    _backfill_annotation_context(bind)


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of durable operation context")
