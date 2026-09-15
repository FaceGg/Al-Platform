"""Durable workers for generic annotation task execution."""

from __future__ import annotations

import hashlib
import json
import threading
from types import SimpleNamespace
import uuid

from app.config import settings
from app.database import SessionLocal
from app.models.operation import DurableOperation
from app.models.platform_models import (
    AnnotationTaskExecutionResult,
    AnnotationTaskPreview,
    AnnotationTaskPreviewSample,
    GenericAnnotationTask,
)
from app.services.operation_lifecycle import claim_operation, complete_operation, fail_operation, heartbeat_operation
from app.tasks.celery_app import celery_app


def enqueue_annotation_execution(task_id, preview_id, operation_id, owner_id):
    """Dispatch an execution using Celery or the local worker path."""
    args = (str(task_id), str(preview_id), str(owner_id), str(operation_id))
    if settings.task_backend == "celery":
        return execute_annotation_task.delay(*args)
    # Local mode has no broker.  Use a daemon thread but keep the exact same
    # durable worker entrypoint so a restart/recovery can safely re-run it.
    threading.Thread(target=execute_annotation_task.run, args=args, daemon=True).start()
    return SimpleNamespace(id=str(operation_id))


def _execution_summary(results):
    cluster_counts = {}
    rule_counts = {}
    final_label_counts = {}
    for item in results:
        provenance = item.provenance or {}
        cluster_id = provenance.get("cluster_id")
        if cluster_id is not None:
            key = str(cluster_id)
            cluster_counts[key] = cluster_counts.get(key, 0) + 1
        for rule_id in provenance.get("matched_rule_ids") or []:
            key = str(rule_id)
            rule_counts[key] = rule_counts.get(key, 0) + 1
        for label, value in (item.values or {}).items():
            rendered = value if isinstance(value, (str, int, float, bool)) or value is None else json.dumps(value, ensure_ascii=True, sort_keys=True)
            key = f"{label}={rendered}"
            final_label_counts.setdefault(key, {"label": label, "value": value, "count": 0})
            final_label_counts[key]["count"] += 1
    return {
        "sample_count": len(results),
        "stats": {
            "cluster": [
                {"key": key, "cluster_id": int(key) if key.lstrip("-").isdigit() else key, "count": cluster_counts[key]}
                for key in sorted(cluster_counts)
            ],
            "rule": [{"key": key, "rule_id": key, "count": rule_counts[key]} for key in sorted(rule_counts)],
            "final_label": [final_label_counts[key] | {"key": key} for key in sorted(final_label_counts)],
        },
    }


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
            samples = db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview_uuid).order_by(
                AnnotationTaskPreviewSample.row_index.asc(), AnnotationTaskPreviewSample.id.asc()
            ).all()
            existing = {
                item.sample_id
                for item in db.query(AnnotationTaskExecutionResult).filter_by(operation_id=operation_uuid).all()
            }
            for item in samples:
                if item.sample_id in existing:
                    continue
                raw_values = dict(item.values or {})
                decision = raw_values.get("annotation_decision")
                if isinstance(decision, dict) and isinstance(decision.get("values"), dict):
                    values = dict(decision["values"])
                    provenance = {
                        "status": decision.get("status"),
                        "provenance": decision.get("provenance"),
                        "model_output": decision.get("model_output"),
                        "cluster_id": decision.get("cluster_id"),
                        "matched_rule_ids": list(decision.get("matched_rule_ids") or []),
                    }
                    result_status = str(decision.get("status") or "ready")
                else:
                    values = raw_values
                    provenance = {}
                    result_status = "ready"
                db.add(AnnotationTaskExecutionResult(
                    task_id=task_uuid,
                    operation_id=operation_uuid,
                    preview_id=preview_uuid,
                    task_revision=preview.task_revision,
                    sample_id=item.sample_id,
                    row_index=item.row_index,
                    values=values,
                    provenance=provenance,
                    status=result_status,
                ))
            db.flush()
            operation = db.get(DurableOperation, operation_uuid)
            operation.stage = "persisting"
            operation.progress = 90
            heartbeat_operation(db, operation_uuid, worker_id, 300)
            persisted = db.query(AnnotationTaskExecutionResult).filter_by(operation_id=operation_uuid).order_by(
                AnnotationTaskExecutionResult.row_index.asc(), AnnotationTaskExecutionResult.sample_id.asc()
            ).all()
            checksum_payload = {
                "task_id": task_id,
                "preview_id": preview_id,
                "task_revision": preview.task_revision,
                "results": [
                    {"sample_id": item.sample_id, "row_index": item.row_index, "values": item.values or {}, "provenance": item.provenance or {}}
                    for item in persisted
                ],
            }
            checksum = "sha256:" + hashlib.sha256(
                json.dumps(checksum_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            ).hexdigest()
            summary = _execution_summary(persisted)
            needs_review_count = sum(item.status == "needs_review" for item in persisted)
            summary["needs_review_count"] = needs_review_count
            if task.status == "executing" and task.task_revision == preview.task_revision:
                task.status = "needs_review" if needs_review_count else "awaiting_annotation"
            complete_operation(db, operation_uuid, worker_id, None, checksum, result_summary=summary)
            return {"status": "completed", "operation_id": operation_id, "result_count": len(persisted)}
        except Exception as error:
            db.rollback()
            try:
                fail_operation(db, operation_uuid, "ANNOTATION_EXECUTION_FAILED", {"message": str(error)[:300]}, worker_id=worker_id)
                failed_task = db.query(GenericAnnotationTask).filter_by(id=task_uuid, owner_id=owner_uuid).one_or_none()
                if failed_task is not None and failed_task.status == "executing":
                    failed_task.status = "failed"
                    db.commit()
            except ValueError:
                pass
            return {"status": "failed", "operation_id": operation_id, "error": {"code": "ANNOTATION_EXECUTION_FAILED", "message": str(error)[:500]}}
    finally:
        if context_exit is not None:
            context_exit(None, None, None)
        elif close_db:
            db.close()
