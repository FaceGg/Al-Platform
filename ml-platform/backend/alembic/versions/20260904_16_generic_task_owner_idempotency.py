"""Scope generic task idempotency keys to their owning subject."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_16"
down_revision = "20260903_15"
branch_labels = None
depends_on = None


TABLE = "generic_annotation_tasks"
OLD_CONSTRAINT = "uq_generic_annotation_task_idempotency_key"
NEW_CONSTRAINT = "uq_generic_annotation_task_owner_idempotency"
OLD_INDEX = "ix_generic_annotation_tasks_idempotency_key"
NEW_INDEX = "ix_generic_annotation_tasks_owner_idempotency"


def _duplicate_owner_keys(bind) -> list[tuple[object, str, int]]:
    rows = bind.execute(
        sa.text(
            "SELECT owner_id, idempotency_key, COUNT(*) AS count "
            "FROM generic_annotation_tasks "
            "WHERE idempotency_key IS NOT NULL "
            "GROUP BY owner_id, idempotency_key HAVING COUNT(*) > 1"
        )
    ).all()
    return [(row[0], row[1], int(row[2])) for row in rows]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return

    duplicates = _duplicate_owner_keys(bind)
    if duplicates:
        raise RuntimeError(
            "Cannot scope generic task idempotency keys while duplicate owner/key rows exist"
        )

    unique_constraints = {
        item.get("name"): tuple(item.get("column_names") or [])
        for item in inspector.get_unique_constraints(TABLE)
    }
    indexes = {item["name"] for item in inspector.get_indexes(TABLE)}
    dialect = bind.dialect.name

    if dialect == "sqlite":
        with op.batch_alter_table(TABLE, recreate="always") as batch_op:
            if OLD_CONSTRAINT in unique_constraints:
                batch_op.drop_constraint(OLD_CONSTRAINT, type_="unique")
            if NEW_CONSTRAINT not in unique_constraints:
                batch_op.create_unique_constraint(
                    NEW_CONSTRAINT, ["owner_id", "idempotency_key"]
                )
        inspector = sa.inspect(bind)
        indexes = {item["name"] for item in inspector.get_indexes(TABLE)}
    else:
        if OLD_CONSTRAINT in unique_constraints:
            op.drop_constraint(OLD_CONSTRAINT, TABLE, type_="unique")
        if NEW_CONSTRAINT not in unique_constraints:
            op.create_unique_constraint(
                NEW_CONSTRAINT, TABLE, ["owner_id", "idempotency_key"]
            )

    if OLD_INDEX in indexes and OLD_INDEX != NEW_INDEX:
        op.drop_index(OLD_INDEX, table_name=TABLE)
    if NEW_INDEX not in indexes:
        op.create_index(
            NEW_INDEX,
            TABLE,
            ["owner_id", "idempotency_key"],
            unique=False,
        )


def downgrade() -> None:
    raise RuntimeError(
        "Refusing to restore global generic task idempotency uniqueness; preserve owner-scoped semantics"
    )
