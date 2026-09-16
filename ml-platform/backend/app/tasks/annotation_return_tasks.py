"""Durable dispatch and recovery worker for annotation return batches."""

from __future__ import annotations

import hashlib
import threading
from types import SimpleNamespace
import uuid

from app.config import settings
from app.database import SessionLocal
from app.models.labeling import AnnotationReturnBatch
from app.models.operation import DurableOperation
from app.services.operation_lifecycle import claim_operation, complete_operation, fail_operation
from app.tasks.celery_app import celery_app


def enqueue_annotation_return(batch_id, operation_id):
    args = (str(batch_id), str(operation_id))
    if settings.task_backend == "celery":
        return execute_annotation_return.delay(*args)
    threading.Thread(target=execute_annotation_return.run, args=args, daemon=True).start()
    return SimpleNamespace(id=str(operation_id))


@celery_app.task(bind=True, name="ml_platform.execute_annotation_return")
def execute_annotation_return(self, batch_id: str, operation_id: str):
    del self
    worker_id = f"annotation-return:{operation_id}"
    try:
        with SessionLocal() as db:
            return _execute_with_session(db, batch_id, operation_id, worker_id)
    except Exception:
        # The operation remains queued for the regular recovery scan when a
        # local worker starts against a stale database/schema.
        return {"status": "deferred", "operation_id": operation_id}


def _execute_with_session(db, batch_id: str, operation_id: str, worker_id: str):
    batch = db.get(AnnotationReturnBatch, uuid.UUID(batch_id))
    operation = db.get(DurableOperation, uuid.UUID(operation_id))
    if batch is None or operation is None or batch.operation_id != operation.id:
        if operation is not None and operation.state not in {"completed", "failed", "cancelled"}:
            fail_operation(db, operation.id, "ANNOTATION_RETURN_INVALID", {"message": "return binding not found"})
        return {"status": "invalid_request", "operation_id": operation_id}
    if operation.state in {"completed", "failed", "cancelled"}:
        return {"status": "not_claimed", "operation_id": operation_id}
    try:
        if not claim_operation(db, operation.id, worker_id, 300):
            return {"status": "not_claimed", "operation_id": operation_id}
        checksum = "sha256:" + hashlib.sha256(
            f"{batch.id}:{batch.task_revision}:{batch.scope_hash}".encode()
        ).hexdigest()
        complete_operation(db, operation.id, worker_id, batch.id, checksum)
        return {"status": "completed", "operation_id": operation_id, "return_batch_id": batch_id}
    except Exception as error:
        db.rollback()
        try:
            fail_operation(db, operation.id, "ANNOTATION_RETURN_FAILED", {"message": str(error)[:300]}, worker_id=worker_id)
        except ValueError:
            pass
        return {"status": "failed", "operation_id": operation_id}
