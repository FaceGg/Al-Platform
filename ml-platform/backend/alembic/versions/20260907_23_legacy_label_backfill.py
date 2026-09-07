"""Backfill generic label history from transition snapshots."""

import uuid

from alembic import op
import sqlalchemy as sa

revision = "20260907_23"
down_revision = "20260907_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "generic_annotation_tasks" not in sa.inspect(bind).get_table_names():
        return
    metadata = sa.MetaData()
    tasks = sa.Table("generic_annotation_tasks", metadata, autoload_with=bind)
    schemas = sa.Table("label_schemas", metadata, autoload_with=bind)
    columns = sa.Table("label_columns", metadata, autoload_with=bind)
    bindings = sa.Table("annotation_task_labels", metadata, autoload_with=bind)
    current = sa.Table("annotation_sample_current", metadata, autoload_with=bind)
    revisions = sa.Table("annotation_revisions", metadata, autoload_with=bind)
    for task in bind.execute(sa.select(tasks)).mappings():
        snapshot = task.get("label_snapshot") or {}
        if not isinstance(snapshot, dict) or not snapshot.get("samples"):
            continue
        schema_id = task["label_schema_id"]
        if bind.execute(sa.select(schemas.c.id).where(schemas.c.id == schema_id)).first() is None:
            bind.execute(schemas.insert().values(
                id=schema_id, project_id=task["project_id"],
                name=f"legacy-{task.get('source_legacy_id') or task['id']}", version=1, status="active",
            ))
            bind.execute(columns.insert().values(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"label-column:{schema_id}:label"),
                schema_id=schema_id, machine_key="label", display_name="Label", ordinal=0,
                value_type="string", required=False, enum_values=[],
            ))
        if bind.execute(sa.select(bindings.c.id).where(bindings.c.task_id == task["id"])).first() is None:
            bind.execute(bindings.insert().values(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"task-label:{task['id']}"),
                task_id=task["id"], schema_id=schema_id,
                schema_snapshot={"legacy": True, "columns": [{"machine_key": "label", "value_type": "string"}]},
            ))
        by_sample = {}
        for item in snapshot.get("revisions") or []:
            by_sample.setdefault(str(item.get("sample_id")), []).append(item)
        for sample in snapshot.get("samples") or []:
            sample_id = str(sample.get("id"))
            sample_revisions = sorted(by_sample.get(sample_id, []), key=lambda item: str(item.get("created_at") or ""))
            revision_no = 0
            values = {}
            for item in sample_revisions:
                if item.get("label") is None or not item.get("author_id"):
                    continue
                revision_no += 1
                values = {"label": str(item["label"])}
                revision_id = uuid.UUID(str(item["id"]))
                if bind.execute(sa.select(revisions.c.id).where(revisions.c.id == revision_id)).first() is None:
                    bind.execute(revisions.insert().values(
                        id=revision_id, task_id=task["id"], sample_id=sample_id, schema_id=schema_id,
                        revision_no=revision_no, base_revision=revision_no - 1, values=values,
                        author_id=uuid.UUID(str(item["author_id"])), source="legacy",
                        action=str(item.get("action") or "edit"), provenance_ref=str(task.get("source_legacy_id") or ""),
                    ))
            if not values and sample.get("current_label") is not None:
                values = {"label": str(sample["current_label"])}
            if values and bind.execute(sa.select(current.c.id).where(current.c.task_id == task["id"], current.c.sample_id == sample_id)).first() is None:
                bind.execute(current.insert().values(
                    id=uuid.uuid5(uuid.NAMESPACE_URL, f"current-label:{task['id']}:{sample_id}"),
                    task_id=task["id"], sample_id=sample_id, schema_id=schema_id,
                    revision_no=revision_no, values=values,
                ))


def downgrade() -> None:
    # Backfill is data-preserving metadata; schema objects are removed by the
    # preceding structural migration during a full downgrade.
    return None
