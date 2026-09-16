"""Move annotation execution aggregates out of operation summaries."""

import hashlib
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260916_49"
down_revision = "20260916_48"
branch_labels = None
depends_on = None


def _statistic_key(kind, payload):
    encoded = json.dumps(
        {"kind": kind, "payload": payload},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _sort_key(payload, statistic_key):
    display_key = str(payload.get("key", statistic_key))
    return display_key if len(display_key.encode("utf-8")) <= 256 else statistic_key


def _execution_operations(bind, operations):
    marker = None
    while True:
        query = sa.select(operations).where(
            operations.c.resource_type == "annotation_execution",
            operations.c.task_id.is_not(None),
            operations.c.result_summary.is_not(None),
        )
        if marker is not None:
            query = query.where(operations.c.id > marker)
        rows = bind.execute(query.order_by(operations.c.id).limit(50)).mappings().all()
        if not rows:
            return
        yield from rows
        marker = rows[-1]["id"]


def _backfill_statistics(bind):
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required = {
        "durable_operations",
        "annotation_task_execution_statistics",
    }
    if not required.issubset(tables):
        return
    operations = sa.table(
        "durable_operations",
        sa.column("id", sa.Uuid()), sa.column("task_id", sa.Uuid()),
        sa.column("resource_type", sa.String()), sa.column("result_summary", sa.JSON()),
    )
    statistics = sa.table(
        "annotation_task_execution_statistics",
        *(sa.column(name, sa.Uuid()) for name in ("id", "task_id", "operation_id")),
        sa.column("kind", sa.String()), sa.column("statistic_key", sa.String()),
        sa.column("sort_key", sa.String()), sa.column("payload", sa.JSON()),
        sa.column("count", sa.Integer()),
    )
    for operation in _execution_operations(bind, operations):
        summary = operation["result_summary"] or {}
        if isinstance(summary, str):
            try:
                summary = json.loads(summary)
            except json.JSONDecodeError:
                continue
        if not isinstance(summary, dict):
            continue
        stats = summary.get("stats")
        if not isinstance(stats, dict):
            continue
        task_id = operation["task_id"]
        if set(stats) - {"cluster", "rule", "final_label"}:
            raise ValueError("Unknown legacy execution statistics; original summary retained")
        for kind in ("cluster", "rule", "final_label"):
            entries = stats.get(kind, [])
            if not isinstance(entries, list):
                raise ValueError("Invalid legacy execution statistics; original summary retained")
            for item in entries:
                if not isinstance(item, dict) or not isinstance(item.get("key"), str):
                    raise ValueError("Invalid legacy statistic; original summary retained")
                count = item.get("count")
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise ValueError("Invalid legacy statistic count; original summary retained")
                payload = {key: value for key, value in item.items() if key != "count"}
                statistic_key = _statistic_key(kind, payload)
                existing = bind.execute(
                    sa.select(statistics.c.id, statistics.c.count).where(
                        statistics.c.operation_id == operation["id"],
                        statistics.c.kind == kind,
                        statistics.c.statistic_key == statistic_key,
                    )
                ).mappings().first()
                if existing is None:
                    bind.execute(
                        statistics.insert().values(
                            id=uuid.uuid4(),
                            task_id=task_id,
                            operation_id=operation["id"],
                            kind=kind,
                            statistic_key=statistic_key,
                            sort_key=_sort_key(payload, statistic_key),
                            payload=payload,
                            count=count,
                        )
                    )
                else:
                    bind.execute(
                        statistics.update().where(statistics.c.id == existing["id"]).values(
                            count=count
                        )
                    )
        summary = dict(summary)
        summary.pop("stats", None)
        bind.execute(
            operations.update().where(operations.c.id == operation["id"]).values(
                result_summary=summary
            )
        )


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "annotation_task_execution_statistics" not in inspector.get_table_names():
        op.create_table(
            "annotation_task_execution_statistics",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("task_id", sa.Uuid(), nullable=False),
            sa.Column("operation_id", sa.Uuid(), nullable=False),
            sa.Column("kind", sa.String(length=24), nullable=False),
            sa.Column("statistic_key", sa.String(length=71), nullable=False),
            sa.Column("sort_key", sa.String(length=256), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(
                ["task_id"],
                ["generic_annotation_tasks.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "operation_id",
                "kind",
                "statistic_key",
                name="uq_annotation_execution_statistic",
            ),
        )
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("annotation_task_execution_statistics")
    }
    if "ix_annotation_execution_statistics_page" not in indexes:
        op.create_index(
            "ix_annotation_execution_statistics_page",
            "annotation_task_execution_statistics",
            ["operation_id", "kind", "sort_key", "id"],
        )
    _backfill_statistics(bind)


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of annotation execution statistics")
