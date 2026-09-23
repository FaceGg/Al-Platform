"""Idempotent scans for pending and stale workflow tasks."""

from datetime import timedelta
import uuid

from app.database import SessionLocal
from app.tasks.time_utils import _aware, utcnow
from app.tasks.celery_app import celery_app
from app.models.run import WorkflowRun
from app.models.operation import DurableOperation
from app.models.platform_models import AnnotationTaskPreview, GenericAnnotationTask
from app.models.labeling import AnnotationReturnBatch
from app.services.operation_lifecycle import claim_operation_dispatch, recover_expired_operations

# Test seams may replace this symbol; the real implementation is imported lazily
# inside the task to avoid the Celery include cycle.
enqueue_annotation_preview = None
enqueue_annotation_execution = None
enqueue_annotation_return = None


def recover_pending_runs(db, enqueue, limit: int = 100) -> int:
    runs = db.query(WorkflowRun).filter(
        WorkflowRun.status.in_(["pending", "queued"]),
        WorkflowRun.task_id.is_(None),
    ).limit(limit).all()
    count = 0
    for run in runs:
        task_id = enqueue(str(run.id))
        run.status = "queued"
        run.task_id = task_id
        db.commit()
        count += 1
    return count


def reconcile_stale_runs(db, active_task_ids: set[str], hard_timeout: timedelta) -> int:
    cutoff = utcnow() - hard_timeout
    runs = db.query(WorkflowRun).filter(
        WorkflowRun.status.in_(["running", "cancel_requested"]),
    ).all()
    count = 0
    for run in runs:
        if run.task_id in active_task_ids:
            continue
        heartbeat = _aware(run.heartbeat_at) if run.heartbeat_at else None
        if heartbeat is None or heartbeat < cutoff:
            if run.status == "cancel_requested":
                run.status = "cancelled"
                run.cancelled_at = utcnow()
                run.error_code = None
                run.error_message = None
            else:
                run.status = "failed"
                run.error_code = "TASK_HARD_TIMEOUT"
                run.error_message = "Workflow task exceeded the hard timeout"
            run.finished_at = utcnow()
            db.commit()
            count += 1
    return count


@celery_app.task(name="ml_platform.recover_operations")
def recover_operations():
    """Re-dispatch queued or stale annotation previews without changing identity."""
    # Import lazily: annotation_preview_tasks imports celery_app to register its
    # task, while celery_app also includes this recovery module.
    dispatcher = enqueue_annotation_preview
    if dispatcher is None:
        from app.tasks.annotation_preview_tasks import enqueue_annotation_preview as dispatcher
    execution_dispatcher = enqueue_annotation_execution
    if execution_dispatcher is None:
        from app.tasks.annotation_execution_tasks import enqueue_annotation_execution as execution_dispatcher
    return_dispatcher = enqueue_annotation_return
    if return_dispatcher is None:
        from app.tasks.annotation_return_tasks import enqueue_annotation_return as return_dispatcher

    with SessionLocal() as db:
        stale_ids = recover_expired_operations(
            db,
            worker_id="durable-operation-recovery",
            lease_seconds=30,
        )
        candidates = db.query(DurableOperation).filter(
            DurableOperation.resource_key.like("annotation-preview:%"),
            DurableOperation.state == "queued",
        ).all()
        recovered = []
        for operation in candidates:
            if not claim_operation_dispatch(db, operation.id):
                continue
            preview_id = operation.resource_key.split(":", 1)[1]
            preview = db.query(AnnotationTaskPreview).filter(AnnotationTaskPreview.id == uuid.UUID(preview_id)).one_or_none()
            if preview is None:
                continue
            task = db.query(GenericAnnotationTask).filter(GenericAnnotationTask.id == preview.task_id).one_or_none()
            if task is None:
                continue
            dispatcher(task.id, preview.id, task.owner_id)
            recovered.append(str(operation.id))
        execution_candidates = db.query(DurableOperation).filter(
            DurableOperation.resource_key.like("annotation-execution:%"),
            DurableOperation.state == "queued",
        ).all()
        for operation in execution_candidates:
            if not claim_operation_dispatch(db, operation.id):
                continue
            task_id = uuid.UUID(operation.resource_key.split(":", 1)[1])
            task = db.query(GenericAnnotationTask).filter(GenericAnnotationTask.id == task_id).one_or_none()
            if task is None:
                continue
            try:
                _revision, preview_id = operation.idempotency_key.split(":", 1)
                preview = db.query(AnnotationTaskPreview).filter(
                    AnnotationTaskPreview.id == uuid.UUID(preview_id),
                    AnnotationTaskPreview.task_id == task.id,
                ).one_or_none()
            except (ValueError, TypeError):
                preview = None
            if preview is None:
                continue
            execution_dispatcher(task.id, preview.id, operation.id, task.owner_id)
            recovered.append(str(operation.id))
        return_candidates = db.query(DurableOperation).filter(
            DurableOperation.resource_key.like("annotation-return:%"),
            DurableOperation.state == "queued",
        ).all()
        for operation in return_candidates:
            if not claim_operation_dispatch(db, operation.id):
                continue
            batch_id = uuid.UUID(operation.resource_key.split(":", 1)[1])
            batch = db.query(AnnotationReturnBatch).filter(
                AnnotationReturnBatch.id == batch_id,
            ).one_or_none()
            if batch is None or batch.operation_id != operation.id:
                continue
            return_dispatcher(batch.id, operation.id)
            recovered.append(str(operation.id))
        # Expired claims are released before re-dispatch; the actual worker must
        # acquire the lease and retain the same operation identity.
        for operation_id in stale_ids:
            operation = db.get(DurableOperation, uuid.UUID(operation_id))
            if operation is None or not operation.resource_key.startswith("annotation-"):
                continue
            operation.state = "queued"; operation.stage = "queued"; operation.lease_owner = None; operation.lease_expires_at = None
            db.commit()
            if operation.resource_key.startswith("annotation-preview:"):
                preview_id = operation.resource_key.split(":", 1)[1]
                preview = db.query(AnnotationTaskPreview).filter(AnnotationTaskPreview.id == uuid.UUID(preview_id)).one_or_none()
                if preview is not None:
                    task = db.query(GenericAnnotationTask).filter(GenericAnnotationTask.id == preview.task_id).one_or_none()
                    if task is not None and claim_operation_dispatch(db, operation.id):
                        dispatcher(task.id, preview.id, task.owner_id)
                        recovered.append(operation_id)
            elif operation.resource_key.startswith("annotation-execution:"):
                task_id = uuid.UUID(operation.resource_key.split(":", 1)[1])
                task = db.query(GenericAnnotationTask).filter(GenericAnnotationTask.id == task_id).one_or_none()
                try:
                    _revision, preview_id = operation.idempotency_key.split(":", 1)
                    preview = db.query(AnnotationTaskPreview).filter(
                        AnnotationTaskPreview.id == uuid.UUID(preview_id),
                        AnnotationTaskPreview.task_id == task_id,
                    ).one_or_none()
                except (ValueError, TypeError):
                    preview = None
                if task is not None and preview is not None and claim_operation_dispatch(db, operation.id):
                    execution_dispatcher(task.id, preview.id, operation.id, task.owner_id)
                    recovered.append(operation_id)
            elif operation.resource_key.startswith("annotation-return:"):
                batch_id = uuid.UUID(operation.resource_key.split(":", 1)[1])
                batch = db.query(AnnotationReturnBatch).filter(
                    AnnotationReturnBatch.id == batch_id,
                ).one_or_none()
                if batch is not None and batch.operation_id == operation.id and claim_operation_dispatch(db, operation.id):
                    return_dispatcher(batch.id, operation.id)
                    recovered.append(operation_id)
    return {"recovered_operation_ids": recovered, "count": len(recovered)}
