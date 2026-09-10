"""Durable execution requests for generic annotation tasks."""

from __future__ import annotations

from dataclasses import dataclass
import uuid
from sqlalchemy.exc import IntegrityError

from app.models.operation import DurableOperation
from app.models.platform_models import AnnotationTaskPreview, GenericAnnotationTask


@dataclass(frozen=True)
class AnnotationExecutionRequest:
    task_id: uuid.UUID
    preview_id: uuid.UUID
    operation_id: uuid.UUID
    task_revision: int
    status: str


def request_annotation_execution(db, task_id, preview_id, actor_id) -> AnnotationExecutionRequest:
    """Create or reuse one execution operation for a completed preview.

    The operation is keyed by the task and preview revision.  This makes a
    repeated request safe while preventing an older preview from being used
    after a task revision changed.
    """
    task = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.id == task_id,
        GenericAnnotationTask.owner_id == actor_id,
    ).one_or_none()
    if task is None:
        raise ValueError("TASK_NOT_FOUND")
    preview = db.query(AnnotationTaskPreview).filter(
        AnnotationTaskPreview.id == preview_id,
        AnnotationTaskPreview.task_id == task.id,
    ).one_or_none()
    if preview is None:
        raise ValueError("PREVIEW_STALE")
    if preview.task_revision != task.task_revision:
        raise ValueError("PREVIEW_STALE")
    if preview.status != "completed":
        raise ValueError("PREVIEW_NOT_COMPLETED")
    resource_key = f"annotation-execution:{task.id}"
    idempotency_key = f"{task.task_revision}:{preview.id}"
    operation = db.query(DurableOperation).filter(
        DurableOperation.resource_key == resource_key,
        DurableOperation.idempotency_key == idempotency_key,
    ).one_or_none()
    if task.status not in {"preview_ready", "ready", "executing"}:
        raise ValueError("TASK_STATE_INVALID")
    if operation is None:
        operation = DurableOperation(
            resource_key=resource_key,
            idempotency_key=idempotency_key,
            state="queued",
            stage="queued",
            progress=0,
            attempt=0,
        )
        db.add(operation)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            operation = db.query(DurableOperation).filter(
                DurableOperation.resource_key == resource_key,
                DurableOperation.idempotency_key == idempotency_key,
            ).one_or_none()
            if operation is None:
                raise
    if task.status in {"preview_ready", "ready", "paused"}:
        task.status = "executing"
    db.commit()
    db.refresh(operation)
    db.refresh(task)
    return AnnotationExecutionRequest(
        task_id=task.id,
        preview_id=preview.id,
        operation_id=operation.id,
        task_revision=task.task_revision,
        status=task.status,
    )
