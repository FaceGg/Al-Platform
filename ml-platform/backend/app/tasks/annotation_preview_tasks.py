"""Durable preview execution for generic annotation tasks."""

import uuid
import hashlib
import json
import threading
from types import SimpleNamespace

from sqlalchemy import and_, or_

from app.database import SessionLocal
from app.models.data_version import DatasetSample
from app.models.platform_models import AnnotationTaskPreview, AnnotationTaskPreviewSample, GenericAnnotationTask
from app.services.annotation_strategies import StrategyConfigError, apply_preview_annotation_strategy
from app.services.annotation_task_state import (
    current_annotation_task_snapshot,
    mark_preview_completed,
    record_annotation_preview_progress,
)
from app.services.operation_lifecycle import claim_operation, heartbeat_operation, complete_operation, fail_operation
from app.tasks.celery_app import celery_app
from app.config import settings


_PREVIEW_BATCH_SIZE = 500


def _chunks(values, size=_PREVIEW_BATCH_SIZE):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _dataset_sample_batches(db, dataset_version_id, sample_ids):
    for sample_id_batch in _chunks(sample_ids):
        if not sample_id_batch:
            continue
        yield db.query(DatasetSample).filter(
            DatasetSample.dataset_version_id == dataset_version_id,
            DatasetSample.sample_id.in_(sample_id_batch),
        ).order_by(
            DatasetSample.row_index.asc(),
            DatasetSample.id.asc(),
        ).limit(len(sample_id_batch)).all()


def _preview_sample_batches(db, preview_id):
    marker = None
    while True:
        query = db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview_id)
        if marker is not None:
            query = query.filter(or_(
                AnnotationTaskPreviewSample.sample_id > marker.sample_id,
                and_(
                    AnnotationTaskPreviewSample.sample_id == marker.sample_id,
                    AnnotationTaskPreviewSample.id > marker.id,
                ),
            ))
        rows = query.order_by(
            AnnotationTaskPreviewSample.sample_id.asc(),
            AnnotationTaskPreviewSample.id.asc(),
        ).limit(_PREVIEW_BATCH_SIZE).all()
        if not rows:
            return
        yield rows
        marker = rows[-1]


def enqueue_annotation_preview(task_id, preview_id, owner_id):
    """Dispatch through the same durable worker in local and Celery runtimes."""
    args = (str(task_id), str(preview_id), str(owner_id))
    if settings.task_backend == "celery":
        return execute_annotation_preview.delay(*args)
    threading.Thread(target=execute_annotation_preview.run, args=args, daemon=True).start()
    return SimpleNamespace(id=str(preview_id))


@celery_app.task(bind=True, name="ml_platform.execute_annotation_preview")
def execute_annotation_preview(self, task_id: str, preview_id: str, owner_id: str):
    task_uuid = uuid.UUID(task_id)
    preview_uuid = uuid.UUID(preview_id)
    owner_uuid = uuid.UUID(owner_id)
    session_factory = SessionLocal
    session_resource = session_factory()
    context_exit = None
    if not hasattr(session_resource, "query") and hasattr(session_resource, "__enter__"):
        db = session_resource.__enter__()
        context_exit = session_resource.__exit__
    else:
        db = session_resource
    # Tests inject a shared Session through a lambda; do not close that caller-owned
    # session. The production sessionmaker is always closed in the finally block.
    close_db = hasattr(session_factory, "kw")
    try:
        task = db.query(GenericAnnotationTask).filter_by(id=task_uuid, owner_id=owner_uuid).one_or_none()
        preview = db.query(AnnotationTaskPreview).filter_by(id=preview_uuid, task_id=task_uuid).one_or_none()
        if task is None or preview is None:
            return {"status": "not_found", "preview_id": preview_id}
        if preview.task_revision != task.task_revision:
            return {"status": "invalid_request", "preview_id": preview_id, "error": "PREVIEW_STALE"}
        operation_id = preview.operation_id
        worker_id = f"annotation-preview:{getattr(getattr(self, 'request', None), 'id', None) or preview_id}"
        try:
            if operation_id is None:
                raise ValueError("OPERATION_NOT_FOUND")
            if not claim_operation(db, operation_id, worker_id, 300):
                return {"status": "not_claimed", "preview_id": preview_id, "operation_id": str(operation_id) if operation_id else None}
            snapshot = current_annotation_task_snapshot(db, task)
            record_annotation_preview_progress(
                db,
                task_uuid,
                preview_uuid,
                owner_uuid,
                status="running",
                progress=10,
                summary={
                    "sample_scope_count": len(snapshot.get("sample_ids", [])),
                    "visible_columns": snapshot.get("visible_columns", []),
                },
            )
            sample_ids = [str(sample_id) for sample_id in snapshot.get("sample_ids", [])]
            visible_columns = list(snapshot.get("visible_columns", []))
            summary = {
                "sample_count": len(sample_ids),
                "visible_columns": snapshot.get("visible_columns", []),
                "label_columns": [column.get("machine_key") for column in snapshot.get("label_schema", {}).get("columns", [])],
                "source_rows_found": 0,
            }
            automatic_decisions = {}
            strategy_artifact = None
            if task.mode == "automatic":
                source_rows = [
                    row
                    for batch in _dataset_sample_batches(db, task.dataset_version_id, sample_ids)
                    for row in batch
                ]
                rows_by_id = {row.sample_id: row for row in source_rows}
                summary["source_rows_found"] = len(source_rows)
                rows = {
                    sample_id: dict(rows_by_id.get(sample_id).values or {}) if rows_by_id.get(sample_id) is not None else {}
                    for sample_id in sample_ids
                }
                strategy_result = apply_preview_annotation_strategy(
                    db,
                    task_id=task.id,
                    task_revision=preview.task_revision,
                    config_hash=preview.config_hash,
                    actor_id=owner_uuid,
                    project_id=task.project_id,
                    schema_snapshot=snapshot.get("label_schema", {}),
                    configuration=snapshot.get("configuration", {}),
                    rows=rows,
                )
                automatic_decisions = strategy_result.decisions
                strategy_artifact = strategy_result.artifact
                summary["strategy"] = strategy_artifact.strategy
                summary["strategy_artifact_id"] = str(strategy_artifact.id)
                strategy_payload = dict(strategy_artifact.artifact or {})
                summary["needs_review_count"] = strategy_payload.get("review_count", 0)
                summary["configuration_complete"] = strategy_payload.get("configuration_complete", True)
                summary["clusters"] = strategy_payload.get("clusters", [])
                summary["model_version_id"] = strategy_payload.get("model_version_id")
                heartbeat_operation(db, operation_id, worker_id, 300)
                existing_ids = set()
                for sample_id_batch in _chunks(sample_ids):
                    existing_ids.update(
                        item.sample_id
                        for item in db.query(AnnotationTaskPreviewSample).filter(
                            AnnotationTaskPreviewSample.preview_id == preview_uuid,
                            AnnotationTaskPreviewSample.sample_id.in_(sample_id_batch),
                        ).limit(len(sample_id_batch)).all()
                    )
                for batch_start in range(0, len(sample_ids), _PREVIEW_BATCH_SIZE):
                    sample_id_batch = sample_ids[batch_start:batch_start + _PREVIEW_BATCH_SIZE]
                    for offset, sample_id in enumerate(sample_id_batch):
                        if sample_id in existing_ids:
                            continue
                        source_row = rows_by_id.get(sample_id)
                        source_values = dict(source_row.values or {}) if source_row is not None else {}
                        values = {column: source_values.get(column) for column in visible_columns} if visible_columns else source_values
                        decision = automatic_decisions.get(sample_id)
                        if decision is not None:
                            values["annotation_decision"] = {
                                "status": decision.status,
                                "values": decision.values,
                                "provenance": decision.provenance,
                                "model_output": decision.model_output,
                                "cluster_id": decision.cluster_id,
                                "matched_rule_ids": list(decision.matched_rule_ids),
                            }
                        db.add(AnnotationTaskPreviewSample(
                            preview_id=preview_uuid,
                            sample_id=sample_id,
                            row_index=batch_start + offset,
                            values=values,
                        ))
                    db.flush()
            else:
                # Manual previews do not need a task-wide in-memory row map.
                # Read one source batch, materialize it, and release it before
                # loading the next batch.
                heartbeat_operation(db, operation_id, worker_id, 300)
                for batch_start in range(0, len(sample_ids), _PREVIEW_BATCH_SIZE):
                    sample_id_batch = sample_ids[batch_start:batch_start + _PREVIEW_BATCH_SIZE]
                    source_rows = [
                        row
                        for batch in _dataset_sample_batches(db, task.dataset_version_id, sample_id_batch)
                        for row in batch
                    ]
                    summary["source_rows_found"] += len(source_rows)
                    rows_by_id = {row.sample_id: row for row in source_rows}
                    existing_ids = {
                        item.sample_id
                        for item in db.query(AnnotationTaskPreviewSample).filter(
                            AnnotationTaskPreviewSample.preview_id == preview_uuid,
                            AnnotationTaskPreviewSample.sample_id.in_(sample_id_batch),
                        ).limit(len(sample_id_batch)).all()
                    }
                    for offset, sample_id in enumerate(sample_id_batch):
                        if sample_id in existing_ids:
                            continue
                        source_row = rows_by_id.get(sample_id)
                        source_values = dict(source_row.values or {}) if source_row is not None else {}
                        values = {column: source_values.get(column) for column in visible_columns} if visible_columns else source_values
                        db.add(AnnotationTaskPreviewSample(
                            preview_id=preview_uuid,
                            sample_id=sample_id,
                            row_index=batch_start + offset,
                            values=values,
                        ))
                    db.flush()
            digest = hashlib.sha256(json.dumps(
                {"preview_id": preview_id, "summary": summary},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode())
            for batch in _preview_sample_batches(db, preview_uuid):
                for item in batch:
                    digest.update(b"\n")
                    digest.update(json.dumps(
                        (str(item.sample_id), item.values or {}),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ).encode())
            checksum = "sha256:" + digest.hexdigest()
            record_annotation_preview_progress(
                db,
                task_uuid,
                preview_uuid,
                owner_uuid,
                status="completed",
                progress=100,
                summary=summary,
                commit=False,
            )
            mark_preview_completed(db, task_uuid, preview_uuid, owner_uuid, commit=False)
            complete_operation(db, operation_id, worker_id, preview_uuid, checksum)
            return {"status": "completed", "preview_id": preview_id, "operation_id": str(preview.operation_id)}
        except Exception as error:
            db.rollback()
            current = db.query(AnnotationTaskPreview).filter_by(id=preview_uuid, task_id=task_uuid).one_or_none()
            failed_task = db.query(GenericAnnotationTask).filter_by(id=task_uuid, owner_id=owner_uuid).one_or_none()
            lease_owned = True
            if current is not None and failed_task is not None and current.task_revision == failed_task.task_revision:
                try:
                    error_code = error.code if isinstance(error, StrategyConfigError) else "PREVIEW_EXECUTION_FAILED"
                    if operation_id is not None:
                        fail_operation(
                            db,
                            operation_id,
                            error_code,
                            {"message": str(error)[:300]},
                            worker_id=worker_id,
                        )
                except ValueError:
                    lease_owned = False
                if lease_owned or str(error) == "OPERATION_NOT_FOUND":
                    current.status = "failed"
                    current.progress = (
                        int(current.progress or 0)
                        if str(error) == "OPERATION_NOT_FOUND"
                        else max(int(current.progress or 0), 10)
                    )
                    current.error = {"code": error_code, "message": str(error)[:500]}
                    if failed_task.status == "previewing":
                        failed_task.status = "failed"
                    db.commit()
            return {"status": "failed", "preview_id": preview_id, "error": current.error if current is not None else None}
    finally:
        if context_exit is not None:
            context_exit(None, None, None)
        elif close_db:
            db.close()
