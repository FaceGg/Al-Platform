"""Durable workers for generic annotation task execution."""

from __future__ import annotations

import hashlib
import json
import threading
from types import SimpleNamespace
import uuid

from sqlalchemy import and_, or_, tuple_
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import settings
from app.database import SessionLocal
from app.models.operation import DurableOperation
from app.models.labeling import AnnotationRevision, AnnotationSampleCurrent
from app.models.platform_models import (
    AnnotationTaskExecutionResult,
    AnnotationTaskExecutionStatistic,
    AnnotationTaskPreview,
    AnnotationTaskPreviewSample,
    GenericAnnotationTask,
)
from app.services.annotation_strategies import label_schema_contract_from_snapshot
from app.services.label_schema import validate_label_values
from app.services.operation_lifecycle import claim_operation, complete_operation, fail_operation, heartbeat_operation
from app.tasks.celery_app import celery_app


class _ExecutionOutputError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def enqueue_annotation_execution(task_id, preview_id, operation_id, owner_id):
    """Dispatch an execution using Celery or the local worker path."""
    args = (str(task_id), str(preview_id), str(owner_id), str(operation_id))
    if settings.task_backend == "celery":
        return execute_annotation_task.delay(*args)
    # Local mode has no broker.  Use a daemon thread but keep the exact same
    # durable worker entrypoint so a restart/recovery can safely re-run it.
    threading.Thread(target=execute_annotation_task.run, args=args, daemon=True).start()
    return SimpleNamespace(id=str(operation_id))


def _statistic_key(kind, payload):
    encoded = json.dumps(
        {"kind": kind, "payload": payload},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _statistic_sort_key(display_key, statistic_key):
    encoded = display_key.encode("utf-8")
    return display_key if len(encoded) <= 256 else statistic_key


def _add_statistic(statistics, kind, payload):
    statistic_key = _statistic_key(kind, payload)
    current = statistics.get((kind, statistic_key))
    if current is None:
        statistics[(kind, statistic_key)] = {
            "kind": kind,
            "statistic_key": statistic_key,
            "sort_key": _statistic_sort_key(str(payload["key"]), statistic_key),
            "payload": payload,
            "count": 1,
        }
    else:
        current["count"] += 1


def _statistics_for_results(results):
    """Aggregate one bounded result batch without retaining task-wide values."""
    statistics = {}
    for item in results:
        provenance = item.provenance or {}
        cluster_id = provenance.get("cluster_id")
        if cluster_id is not None:
            key = str(cluster_id)
            _add_statistic(
                statistics,
                "cluster",
                {
                    "key": key,
                    "cluster_id": int(key) if key.lstrip("-").isdigit() else key,
                },
            )
        for rule_id in provenance.get("matched_rule_ids") or []:
            key = str(rule_id)
            _add_statistic(statistics, "rule", {"key": key, "rule_id": key})
        for label, value in (item.values or {}).items():
            rendered = (
                value
                if isinstance(value, (str, int, float, bool)) or value is None
                else json.dumps(value, ensure_ascii=True, sort_keys=True)
            )
            key = f"{label}={rendered}"
            _add_statistic(
                statistics,
                "final_label",
                {"key": key, "label": label, "value": value},
            )
    return tuple(statistics.values())


def _upsert_execution_statistics(db, task_id, operation_id, statistics):
    if not statistics:
        return
    table = AnnotationTaskExecutionStatistic.__table__
    values = [
        {
            "task_id": task_id,
            "operation_id": operation_id,
            **statistic,
        }
        for statistic in statistics
    ]
    dialect = db.get_bind().dialect.name
    insert_factory = {
        "postgresql": postgresql_insert,
        "sqlite": sqlite_insert,
    }.get(dialect)
    if insert_factory is None:
        for value in values:
            current = db.query(AnnotationTaskExecutionStatistic).filter_by(
                operation_id=operation_id,
                kind=value["kind"],
                statistic_key=value["statistic_key"],
            ).one_or_none()
            if current is None:
                db.add(AnnotationTaskExecutionStatistic(**value))
            else:
                current.count += value["count"]
        return
    statement = insert_factory(table)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.operation_id, table.c.kind, table.c.statistic_key],
        set_={"count": table.c.count + statement.excluded.count},
    )
    db.execute(statement, values)


def _preview_sample_batches(db, preview_id, *, batch_size=500):
    marker = None
    while True:
        query = db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview_id)
        if marker is not None:
            query = query.filter(or_(
                AnnotationTaskPreviewSample.row_index > marker.row_index,
                and_(
                    AnnotationTaskPreviewSample.row_index == marker.row_index,
                    AnnotationTaskPreviewSample.id > marker.id,
                ),
            ))
        rows = query.order_by(
            AnnotationTaskPreviewSample.row_index.asc(),
            AnnotationTaskPreviewSample.id.asc(),
        ).limit(batch_size).all()
        if not rows:
            return
        yield rows
        marker = rows[-1]


def _execution_result_batches(db, operation_id, *, batch_size=500):
    marker = None
    while True:
        query = db.query(AnnotationTaskExecutionResult).filter_by(operation_id=operation_id)
        if marker is not None:
            query = query.filter(or_(
                AnnotationTaskExecutionResult.row_index > marker.row_index,
                and_(
                    AnnotationTaskExecutionResult.row_index == marker.row_index,
                    AnnotationTaskExecutionResult.sample_id > marker.sample_id,
                ),
            ))
        rows = query.order_by(
            AnnotationTaskExecutionResult.row_index.asc(),
            AnnotationTaskExecutionResult.sample_id.asc(),
        ).limit(batch_size).all()
        if not rows:
            return
        yield rows
        marker = rows[-1]


def _preview_result_fields(item):
    raw_values = dict(item.values or {})
    decision = raw_values.get("annotation_decision")
    if isinstance(decision, dict) and isinstance(decision.get("values"), dict):
        return (
            dict(decision["values"]),
            {
                "status": decision.get("status"),
                "provenance": decision.get("provenance"),
                "model_output": decision.get("model_output"),
                "cluster_id": decision.get("cluster_id"),
                "matched_rule_ids": list(decision.get("matched_rule_ids") or []),
            },
            str(decision.get("status") or "ready"),
        )
    return raw_values, {}, "ready"


def _publish_execution_label_state(db, task, operation_id, results):
    """Atomically publish automatic results as editable label state.

    Execution results retain per-label provenance internally.  The editable
    current-value table intentionally stores only validated final labels, while
    the initial immutable revision points back to the execution operation.
    """
    if task.mode != "automatic":
        return
    schema_snapshot = (task.task_snapshot or {}).get("label_schema") or task.label_snapshot or {}
    schema = label_schema_contract_from_snapshot(schema_snapshot)
    sample_ids = [item.sample_id for item in results]
    existing = {
        row.sample_id: row
        for row in db.query(AnnotationSampleCurrent).filter(
            AnnotationSampleCurrent.task_id == task.id,
            AnnotationSampleCurrent.sample_id.in_(sample_ids),
        ).limit(len(sample_ids)).all()
    }
    current_pairs = [(row.sample_id, row.revision_no) for row in existing.values()]
    revisions = {
        (row.sample_id, row.revision_no): row
        for row in db.query(AnnotationRevision).filter(
            AnnotationRevision.task_id == task.id,
            tuple_(AnnotationRevision.sample_id, AnnotationRevision.revision_no).in_(current_pairs),
        ).limit(len(current_pairs)).all()
    } if current_pairs else {}
    for item in results:
        values = validate_label_values(schema, dict(item.values or {}), allow_partial=False)
        current = existing.get(item.sample_id)
        if current is None:
            revision_no = 0
            base_revision = 0
            db.add(AnnotationSampleCurrent(
                task_id=task.id,
                sample_id=item.sample_id,
                schema_id=task.label_schema_id,
                revision_no=revision_no,
                values=values,
            ))
        else:
            latest = revisions.get((item.sample_id, current.revision_no))
            if latest is None or latest.source != "automatic" or latest.action != "initialize":
                raise ValueError("ANNOTATION_LABEL_STATE_CONFLICT")
            revision_no = current.revision_no + 1
            base_revision = current.revision_no
            current.schema_id = task.label_schema_id
            current.revision_no = revision_no
            current.values = values
        db.add(AnnotationRevision(
            task_id=task.id,
            sample_id=item.sample_id,
            schema_id=task.label_schema_id,
            revision_no=revision_no,
            base_revision=base_revision,
            values=values,
            author_id=task.owner_id,
            source="automatic",
            action="initialize",
            provenance_ref=f"annotation-execution:{operation_id}",
        ))


@celery_app.task(bind=True, name="ml_platform.execute_annotation_task")
def execute_annotation_task(self, task_id: str, preview_id: str, owner_id: str, operation_id: str):
    task_uuid = uuid.UUID(str(task_id))
    preview_uuid = uuid.UUID(str(preview_id))
    owner_uuid = uuid.UUID(str(owner_id))
    operation_uuid = uuid.UUID(str(operation_id))
    session_factory = SessionLocal
    session_resource = session_factory()
    context_exit = None
    if not hasattr(session_resource, "query") and hasattr(session_resource, "__enter__"):
        db = session_resource.__enter__()
        context_exit = session_resource.__exit__
    else:
        db = session_resource
    close_db = hasattr(session_factory, "kw")
    worker_id = f"annotation-execution:{getattr(getattr(self, 'request', None), 'id', None) or operation_id}"
    try:
        task = db.query(GenericAnnotationTask).filter_by(id=task_uuid, owner_id=owner_uuid).one_or_none()
        preview = db.query(AnnotationTaskPreview).filter_by(id=preview_uuid, task_id=task_uuid).one_or_none()
        operation = db.get(DurableOperation, operation_uuid)
        if operation is None:
            return {"status": "not_found", "operation_id": operation_id}
        if task is None or preview is None:
            if operation.state not in {"completed", "failed", "cancelled"}:
                fail_operation(db, operation_uuid, "ANNOTATION_EXECUTION_INVALID", {"message": "execution binding not found"})
            return {"status": "invalid_request", "operation_id": operation_id}
        if operation.state in {"completed", "failed", "cancelled"}:
            return {"status": "not_claimed", "operation_id": operation_id}
        if preview.status != "completed":
            if task.status == "paused":
                return {"status": "paused", "operation_id": operation_id}
            if task.status == "executing":
                task.status = "failed"
                db.commit()
            fail_operation(db, operation_uuid, "ANNOTATION_EXECUTION_INVALID", {"message": "preview is not completed"})
            return {"status": "invalid_request", "operation_id": operation_id}
        if task.status == "paused":
            return {"status": "paused", "operation_id": operation_id}
        if (
            operation.resource_key != f"annotation-execution:{task.id}"
            or operation.idempotency_key != f"{preview.task_revision}:{preview.id}"
        ):
            fail_operation(db, operation_uuid, "ANNOTATION_EXECUTION_INVALID", {"message": "execution binding mismatch"})
            return {"status": "invalid_request", "operation_id": operation_id}
        if task.status != "executing" or task.task_revision != preview.task_revision:
            fail_operation(db, operation_uuid, "ANNOTATION_EXECUTION_STALE", {"message": "task revision or state changed"})
            return {"status": "invalid_request", "operation_id": operation_id}
        if not claim_operation(db, operation_uuid, worker_id, 300):
            return {"status": "not_claimed", "operation_id": operation_id}
        try:
            operation = db.get(DurableOperation, operation_uuid)
            task = db.query(GenericAnnotationTask).filter_by(id=task_uuid, owner_id=owner_uuid).one_or_none()
            preview = db.query(AnnotationTaskPreview).filter_by(id=preview_uuid, task_id=task_uuid).one_or_none()
            if task is None or preview is None or task.status not in {"executing", "paused"} or task.task_revision != preview.task_revision:
                if task is not None and task.status == "paused":
                    return {"status": "paused", "operation_id": operation_id}
                fail_operation(db, operation_uuid, "ANNOTATION_EXECUTION_STALE", {"message": "task revision or state changed"}, worker_id=worker_id)
                return {"status": "invalid_request", "operation_id": operation_id}
            operation.stage = "materializing"
            operation.progress = 10
            # Persist the lease refresh before adding execution rows.  A later
            # validation failure must be able to roll every result back rather
            # than have a heartbeat commit a partially materialized output.
            heartbeat_operation(db, operation_uuid, worker_id, 300)
            for samples in _preview_sample_batches(db, preview_uuid):
                sample_ids = [item.sample_id for item in samples]
                existing = {
                    sample_id
                    for (sample_id,) in db.query(AnnotationTaskExecutionResult.sample_id).filter(
                        AnnotationTaskExecutionResult.operation_id == operation_uuid,
                        AnnotationTaskExecutionResult.sample_id.in_(sample_ids),
                    ).limit(len(sample_ids)).all()
                }
                inserted = []
                for item in samples:
                    if item.sample_id in existing:
                        continue
                    values, provenance, result_status = _preview_result_fields(item)
                    result = AnnotationTaskExecutionResult(
                        task_id=task_uuid,
                        operation_id=operation_uuid,
                        preview_id=preview_uuid,
                        task_revision=preview.task_revision,
                        sample_id=item.sample_id,
                        row_index=item.row_index,
                        values=values,
                        provenance=provenance,
                        status=result_status,
                    )
                    db.add(result)
                    inserted.append(result)
                db.flush()
            db.flush()
            operation = db.get(DurableOperation, operation_uuid)
            operation.stage = "persisting"
            operation.progress = 90
            checksum_payload = {
                "task_id": task_id,
                "preview_id": preview_id,
                "task_revision": preview.task_revision,
            }
            digest = hashlib.sha256(
                json.dumps(checksum_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            )
            db.query(AnnotationTaskExecutionStatistic).filter_by(operation_id=operation_uuid).delete(
                synchronize_session=False
            )
            needs_review_count = 0
            invalid_count = 0
            invalid_sample_ids = []
            result_count = 0
            for persisted in _execution_result_batches(db, operation_uuid):
                _upsert_execution_statistics(
                    db,
                    task_uuid,
                    operation_uuid,
                    _statistics_for_results(persisted),
                )
                for item in persisted:
                    digest.update(b"\n")
                    digest.update(json.dumps(
                        {
                            "sample_id": item.sample_id,
                            "row_index": item.row_index,
                            "values": item.values or {},
                            "provenance": item.provenance or {},
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ).encode("utf-8"))
                    result_count += 1
                    if item.status == "needs_review":
                        needs_review_count += 1
                    elif item.status != "ready":
                        invalid_count += 1
                        if len(invalid_sample_ids) < 100:
                            invalid_sample_ids.append(item.sample_id)
            checksum = "sha256:" + digest.hexdigest()
            summary = {
                "sample_count": result_count,
                "needs_review_count": needs_review_count,
            }
            if invalid_count:
                raise _ExecutionOutputError(
                    "ANNOTATION_EXECUTION_RESULT_INVALID",
                    "execution output is not ready for publication",
                    {
                        "affected_sample_count": invalid_count,
                        "sample_ids": invalid_sample_ids,
                    },
                )
            if not needs_review_count:
                for persisted in _execution_result_batches(db, operation_uuid):
                    _publish_execution_label_state(db, task, operation_uuid, persisted)
                    db.flush()
                task = db.query(GenericAnnotationTask).filter_by(id=task_uuid, owner_id=owner_uuid).one_or_none()
                preview = db.query(AnnotationTaskPreview).filter_by(id=preview_uuid, task_id=task_uuid).one_or_none()
            if task.status == "executing" and task.task_revision == preview.task_revision:
                task.status = "needs_review" if needs_review_count else "awaiting_annotation"
            complete_operation(db, operation_uuid, worker_id, None, checksum, result_summary=summary)
            return {"status": "completed", "operation_id": operation_id, "result_count": result_count}
        except Exception as error:
            db.rollback()
            try:
                error_code = getattr(error, "code", "ANNOTATION_EXECUTION_FAILED")
                error_details = {"message": str(error)[:300], **getattr(error, "details", {})}
                fail_operation(db, operation_uuid, error_code, error_details, worker_id=worker_id)
                failed_task = db.query(GenericAnnotationTask).filter_by(id=task_uuid, owner_id=owner_uuid).one_or_none()
                if failed_task is not None and failed_task.status == "executing":
                    failed_task.status = "failed"
                    db.commit()
            except ValueError:
                pass
            return {"status": "failed", "operation_id": operation_id, "error": {"code": getattr(error, "code", "ANNOTATION_EXECUTION_FAILED"), "message": str(error)[:500]}}
    finally:
        if context_exit is not None:
            context_exit(None, None, None)
        elif close_db:
            db.close()
