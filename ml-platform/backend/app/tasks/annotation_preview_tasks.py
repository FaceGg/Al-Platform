"""Durable preview execution for generic annotation tasks."""

import uuid
import hashlib
import json
import threading
from types import SimpleNamespace

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
        operation_id = preview.operation_id
        worker_id = f"annotation-preview:{getattr(getattr(self, 'request', None), 'id', None) or preview_id}"
        if operation_id is None or not claim_operation(db, operation_id, worker_id, 300):
            return {"status": "not_claimed", "preview_id": preview_id, "operation_id": str(operation_id) if operation_id else None}
        try:
            snapshot = current_annotation_task_snapshot(db, task)
            record_annotation_preview_progress(db, task_uuid, preview_uuid, owner_uuid, status="running", progress=10, summary={"sample_scope": snapshot.get("sample_ids", []), "visible_columns": snapshot.get("visible_columns", [])})
            sample_ids = [str(sample_id) for sample_id in snapshot.get("sample_ids", [])]
            source_rows = db.query(DatasetSample).filter(
                DatasetSample.dataset_version_id == task.dataset_version_id,
                DatasetSample.sample_id.in_(sample_ids),
            ).all() if sample_ids else []
            rows_by_id = {row.sample_id: row for row in source_rows}
            visible_columns = list(snapshot.get("visible_columns", []))
            summary = {
                "sample_count": len(sample_ids),
                "visible_columns": snapshot.get("visible_columns", []),
                "label_columns": [column.get("machine_key") for column in snapshot.get("label_schema", {}).get("columns", [])],
                "source_rows_found": len(source_rows),
            }
            automatic_decisions = {}
            strategy_artifact = None
            if task.mode == "automatic":
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
                summary["needs_review_count"] = strategy_artifact.artifact.get("review_count", 0)
            existing_ids = {item.sample_id for item in db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview_uuid).all()}
            for row_index, sample_id in enumerate(sample_ids):
                if sample_id not in existing_ids:
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
                    db.add(AnnotationTaskPreviewSample(preview_id=preview_uuid, sample_id=sample_id, row_index=row_index, values=values))
            db.commit()
            heartbeat_operation(db, operation_id, worker_id, 300)
            record_annotation_preview_progress(db, task_uuid, preview_uuid, owner_uuid, status="completed", progress=100, summary=summary)
            mark_preview_completed(db, task_uuid, preview_uuid, owner_uuid)
            checksum_payload = {"preview_id": preview_id, "summary": summary, "samples": sorted((str(item.sample_id), item.values or {}) for item in db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview_uuid).all())}
            checksum = "sha256:" + hashlib.sha256(json.dumps(checksum_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
            complete_operation(db, operation_id, worker_id, preview_uuid, checksum)
            return {"status": "completed", "preview_id": preview_id, "operation_id": str(preview.operation_id)}
        except Exception as error:
            db.rollback()
            current = db.query(AnnotationTaskPreview).filter_by(id=preview_uuid, task_id=task_uuid).one_or_none()
            if current is not None:
                current.status = "failed"
                current.progress = max(int(current.progress or 0), 10)
                current.error = {"code": "PREVIEW_EXECUTION_FAILED", "message": str(error)[:500]}
                failed_task = db.query(GenericAnnotationTask).filter_by(id=task_uuid, owner_id=owner_uuid).one_or_none()
                if failed_task is not None and failed_task.status == "previewing":
                    failed_task.status = "failed"
                db.commit()
            if operation_id is not None:
                try:
                    fail_operation(
                        db,
                        operation_id,
                        "PREVIEW_EXECUTION_FAILED",
                        {"message": str(error)[:300]},
                        worker_id=worker_id,
                    )
                except ValueError:
                    pass
            return {"status": "failed", "preview_id": preview_id, "error": current.error if current is not None else None}
    finally:
        if context_exit is not None:
            context_exit(None, None, None)
        elif close_db:
            db.close()
