"""State transitions and preview operations for generic annotation tasks."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import and_, or_

from app.models.access import AuditEvent
from app.models.operation import DurableOperation
from app.models.platform_models import AnnotationTaskExecutionResult, AnnotationTaskPreview, AnnotationTaskPreviewSample, AnnotationTaskRevisionSnapshot, GenericAnnotationTask
from app.schemas.annotation_tasks import TaskAction

_TRANSITIONS = {
    "draft": {TaskAction.cancel: "cancelled"},
    "preview_ready": {
        TaskAction.publish: "awaiting_annotation",
        TaskAction.execute: "executing",
        TaskAction.pause: "paused",
        TaskAction.cancel: "cancelled",
    },
    "executing": {
        TaskAction.pause: "paused",
        TaskAction.cancel: "cancelled",
    },
    "awaiting_annotation": {
        TaskAction.pause: "paused",
        TaskAction.cancel: "cancelled",
    },
    "in_progress": {
        TaskAction.pause: "paused",
        TaskAction.cancel: "cancelled",
    },
    "awaiting_return": {
        TaskAction.return_: "returned_pending_acceptance",
        TaskAction.pause: "paused",
        TaskAction.cancel: "cancelled",
    },
    "returned_pending_acceptance": {TaskAction.accept: "accepted"},
    "accepted": {TaskAction.complete: "completed", TaskAction.archive: "archived"},
    "completed": {TaskAction.archive: "archived", TaskAction.reopen: "in_progress"},
    "paused": {TaskAction.resume: "__restore__", TaskAction.cancel: "cancelled"},
    "cancelled": {TaskAction.archive: "archived"},
    "archived": {TaskAction.restore: "completed"},
    "failed": {TaskAction.cancel: "cancelled"},
    "needs_review": {TaskAction.cancel: "cancelled"},
}


def _task_or_error(db, task_id, owner_id=None):
    query = db.query(GenericAnnotationTask).filter(GenericAnnotationTask.id == task_id)
    if owner_id is not None:
        query = query.filter(GenericAnnotationTask.owner_id == owner_id)
    task = query.one_or_none()
    if task is None:
        raise ValueError("TASK_NOT_FOUND")
    return task


def create_annotation_preview(db, task_id, task_revision: int, config_hash: str, actor_id):
    task = _task_or_error(db, task_id, actor_id)
    if task.task_revision != task_revision:
        raise ValueError("TASK_REVISION_CONFLICT")
    existing = db.query(AnnotationTaskPreview).filter_by(task_id=task.id, task_revision=task_revision, config_hash=config_hash).one_or_none()
    if existing is not None:
        existing._created_now = False
        return existing
    previous_status = task.status
    if task.status in {"pending", "draft", "failed", "preview_ready"}:
        task.status = "previewing"
    elif task.status != "previewing":
        raise ValueError("TASK_STATE_INVALID")
    preview = AnnotationTaskPreview(task_id=task.id, task_revision=task_revision, config_hash=config_hash, created_by=actor_id, status="queued", summary={"sample_scope": task.sample_scope or {}})
    db.add(preview)
    db.flush()
    db.add(
        DurableOperation(
            id=preview.operation_id,
            resource_key=f"annotation-preview:{preview.id}",
            idempotency_key=config_hash,
            state="queued",
            stage="queued",
            progress=0,
            attempt=0,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    if previous_status != task.status:
        db.add(AuditEvent(
            project_id=task.project_id,
            actor_id=actor_id,
            actor_username=getattr(getattr(task, "owner", None), "username", str(actor_id)),
            action="annotation_task.preview_requested",
            resource_type="annotation_task",
            resource_id=str(task.id),
            result="success",
            request_id=uuid.uuid4(),
            changes={"from_status": previous_status, "to_status": task.status, "task_revision": task.task_revision},
        ))
    db.commit()
    db.refresh(preview)
    preview._created_now = True
    return preview


def transition_annotation_task(db, task_id, expected_revision: int, action: TaskAction, actor_id, preview_id=None):
    task = _task_or_error(db, task_id, actor_id)
    if task.task_revision != expected_revision:
        raise ValueError("TASK_REVISION_CONFLICT")
    if action == TaskAction.execute:
        preview = db.query(AnnotationTaskPreview).filter_by(id=preview_id, task_id=task.id).one_or_none()
        if preview is None or preview.task_revision != expected_revision or preview.status != "completed":
            raise ValueError("PREVIEW_STALE")
        preview_summary = dict(preview.summary or {})
        if preview_summary.get("configuration_complete") is False:
            raise ValueError("PREVIEW_CONFIGURATION_INCOMPLETE")
        if int(preview_summary.get("needs_review_count", 0) or 0) > 0:
            raise ValueError("PREVIEW_NEEDS_REVIEW")
        # Execution has its own durable operation. Keep the preview revision
        # stable while the operation runs so retries resolve to the same
        # operation and workers can validate the immutable binding.
        from app.services.annotation_task_execution import request_annotation_execution
        execution = request_annotation_execution(db, task.id, preview.id, actor_id)
        previous_status = task.status
        db.add(AuditEvent(
            project_id=task.project_id,
            actor_id=actor_id,
            actor_username=getattr(getattr(task, "owner", None), "username", str(actor_id)),
            action="annotation_task.execute_requested",
            resource_type="annotation_task",
            resource_id=str(task.id),
            result="success",
            request_id=uuid.uuid4(),
            changes={
                "from_status": previous_status,
                "to_status": task.status,
                "task_revision": task.task_revision,
                "preview_id": str(preview.id),
                "operation_id": str(execution.operation_id),
            },
        ))
        db.commit()
        db.refresh(task)
        task._execution_operation_id = execution.operation_id
        task._execution_preview_id = preview.id
        return task
    next_status = _TRANSITIONS.get(task.status, {}).get(action)
    if next_status is None:
        raise ValueError("TASK_STATE_INVALID")
    previous_status = task.status
    if next_status == "__restore__":
        next_status = str(task.paused_from_status or "")
        if next_status not in {"preview_ready", "executing", "awaiting_annotation", "in_progress", "awaiting_return"}:
            raise ValueError("TASK_STATE_INVALID")
    if action == TaskAction.pause:
        task.paused_from_status = previous_status
    elif action == TaskAction.resume:
        task.paused_from_status = None
    task.status = next_status
    # Pause/resume changes execution availability, not the frozen task
    # configuration.  Incrementing the revision here would invalidate the
    # preview that the paused operation is explicitly meant to resume.
    if action not in {TaskAction.pause, TaskAction.resume}:
        task.task_revision += 1
    db.add(AuditEvent(
        project_id=task.project_id,
        actor_id=actor_id,
        actor_username=getattr(getattr(task, "owner", None), "username", str(actor_id)),
        action="annotation_task.transition",
        resource_type="annotation_task",
        resource_id=str(task.id),
        result="success",
        request_id=uuid.uuid4(),
        changes={"action": action.value, "from_status": previous_status, "to_status": next_status, "task_revision": task.task_revision},
    ))
    db.commit()
    db.refresh(task)
    return task


def serialize_annotation_preview(preview):
    if preview is None:
        return None
    return {
        "id": str(preview.id),
        "operation_id": str(preview.operation_id),
        "task_revision": preview.task_revision,
        "config_hash": preview.config_hash,
        "status": preview.status,
        "progress": preview.progress,
        "summary": preview.summary or {},
        "error": preview.error,
        "completed_at": preview.completed_at.isoformat() if preview.completed_at else None,
    }


def current_annotation_task_snapshot(db, task):
    revision = db.query(AnnotationTaskRevisionSnapshot).filter_by(
        task_id=task.id,
        task_revision=task.task_revision,
    ).one_or_none()
    return revision.snapshot if revision is not None else (task.task_snapshot or {})


def current_annotation_task_preview(db, task):
    """Return the preview that remains actionable after a task-list refresh."""
    candidates = db.query(AnnotationTaskPreview).filter(
        AnnotationTaskPreview.task_id == task.id,
        AnnotationTaskPreview.task_revision == task.task_revision,
    ).order_by(AnnotationTaskPreview.created_at.desc(), AnnotationTaskPreview.id.desc()).all()
    if not candidates:
        return None
    expected_hash = str(current_annotation_task_snapshot(db, task).get("config_hash") or "")
    if expected_hash:
        configured = next((item for item in candidates if item.config_hash == expected_hash), None)
        if configured is not None:
            return configured
    completed = next((item for item in candidates if item.status == "completed"), None)
    return completed or candidates[0]


def serialize_annotation_task(task, preview=None, snapshot=None):
    payload = {
        "id": str(task.id),
        "project_id": str(task.project_id),
        "dataset_version_id": str(task.dataset_version_id),
        "label_schema_id": str(task.label_schema_id),
        "mode": task.mode,
        "status": task.status,
        "task_revision": task.task_revision,
        "sample_scope": task.sample_scope or {},
        "task_snapshot": snapshot if snapshot is not None else task.task_snapshot or {},
        "source_legacy_id": task.source_legacy_id,
        "preview": serialize_annotation_preview(preview),
    }
    operation_id = getattr(task, "_execution_operation_id", None)
    if operation_id is not None:
        payload["operation_id"] = str(operation_id)
    return payload


def list_annotation_tasks(db, project_id, owner_id, cursor=None, limit=50):
    limit = max(1, min(int(limit), 200))
    base_query = db.query(GenericAnnotationTask).filter(GenericAnnotationTask.owner_id == owner_id)
    if project_id is not None:
        base_query = base_query.filter(GenericAnnotationTask.project_id == project_id)
    query = base_query.order_by(GenericAnnotationTask.created_at.desc(), GenericAnnotationTask.id.desc())
    all_items = query.all()
    total = len(all_items)
    start = 0
    if cursor:
        try:
            marker_id = uuid.UUID(cursor)
        except (ValueError, AttributeError) as error:
            raise ValueError("INVALID_CURSOR") from error
        marker_index = next((index for index, item in enumerate(all_items) if item.id == marker_id), None)
        if marker_index is None:
            raise ValueError("INVALID_CURSOR")
        start = marker_index + 1
    items = all_items[start:start + limit + 1]
    has_next = len(items) > limit
    items = items[:limit]
    return {
        "items": [
            serialize_annotation_task(item, current_annotation_task_preview(db, item), current_annotation_task_snapshot(db, item))
            for item in items
        ],
        "total": total,
        "next_cursor": str(items[-1].id) if has_next and items else None,
    }


def mark_preview_completed(db, task_id, preview_id, owner_id):
    preview = get_annotation_preview(db, task_id, preview_id, owner_id)
    task = _task_or_error(db, task_id, owner_id)
    if preview.status != "completed":
        raise ValueError("PREVIEW_NOT_COMPLETED")
    if preview.task_revision != task.task_revision:
        raise ValueError("TASK_REVISION_CONFLICT")
    if task.status == "previewing":
        summary = dict(preview.summary or {})
        if summary.get("configuration_complete") is False or int(summary.get("needs_review_count", 0) or 0) > 0:
            task.status = "needs_review"
        else:
            task.status = "preview_ready"
        db.add(AuditEvent(
            project_id=task.project_id,
            actor_id=owner_id,
            actor_username=getattr(getattr(task, "owner", None), "username", str(owner_id)),
            action="annotation_task.preview_completed",
            resource_type="annotation_task",
            resource_id=str(task.id),
            result="success",
            request_id=uuid.uuid4(),
            changes={"from_status": "previewing", "to_status": task.status, "task_revision": task.task_revision},
        ))
        db.commit()
        db.refresh(task)
    return task


def list_annotation_previews(db, task_id, owner_id, cursor=None, limit=50):
    _task_or_error(db, task_id, owner_id)
    limit = max(1, min(int(limit), 200))
    query = db.query(AnnotationTaskPreview).filter(AnnotationTaskPreview.task_id == task_id).order_by(AnnotationTaskPreview.created_at.desc(), AnnotationTaskPreview.id.desc())
    all_items = query.all()
    start = 0
    if cursor:
        try:
            marker_id = uuid.UUID(cursor)
        except (ValueError, AttributeError) as error:
            raise ValueError("INVALID_CURSOR") from error
        marker_index = next((index for index, item in enumerate(all_items) if item.id == marker_id), None)
        if marker_index is None:
            raise ValueError("INVALID_CURSOR")
        start = marker_index + 1
    items = all_items[start:start + limit + 1]
    has_next = len(items) > limit
    items = items[:limit]
    return {
        "items": [serialize_annotation_preview(item) for item in items],
        "total": len(all_items),
        "next_cursor": str(items[-1].id) if has_next and items else None,
    }


def get_annotation_preview(db, task_id, preview_id, owner_id):
    _task_or_error(db, task_id, owner_id)
    preview = db.query(AnnotationTaskPreview).filter_by(id=preview_id, task_id=task_id).one_or_none()
    if preview is None:
        raise ValueError("PREVIEW_NOT_FOUND")
    return preview


def record_annotation_preview_progress(db, task_id, preview_id, owner_id, *, status, progress, summary=None, error=None):
    preview = get_annotation_preview(db, task_id, preview_id, owner_id)
    progress = int(progress)
    if progress < preview.progress:
        raise ValueError("PREVIEW_PROGRESS_REGRESSION")
    if progress < 0 or progress > 100:
        raise ValueError("PREVIEW_PROGRESS_INVALID")
    preview.progress = progress
    preview.status = status
    if summary is not None:
        preview.summary = summary
    preview.error = error
    if status == "completed":
        preview.progress = 100
        preview.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(preview)
    return preview


def list_annotation_preview_samples(db, task_id, preview_id, owner_id, cursor=None, limit=50):
    get_annotation_preview(db, task_id, preview_id, owner_id)
    limit = max(1, min(int(limit), 200))
    query = db.query(AnnotationTaskPreviewSample).filter_by(preview_id=preview_id).order_by(AnnotationTaskPreviewSample.row_index.asc(), AnnotationTaskPreviewSample.id.asc())
    all_items = query.all()
    start = 0
    if cursor:
        try:
            marker_id = uuid.UUID(cursor)
        except (ValueError, AttributeError) as error:
            raise ValueError("INVALID_CURSOR") from error
        marker_index = next((index for index, item in enumerate(all_items) if item.id == marker_id), None)
        if marker_index is None:
            raise ValueError("INVALID_CURSOR")
        start = marker_index + 1
    items = all_items[start:start + limit + 1]
    has_next = len(items) > limit
    items = items[:limit]
    return {"items": [{"id": str(item.id), "sample_id": item.sample_id, "row_index": item.row_index, "values": item.values or {}} for item in items], "total": len(all_items), "next_cursor": str(items[-1].id) if has_next and items else None}


def _execution_operation_or_error(db, task_id, operation_id, owner_id):
    task = _task_or_error(db, task_id, owner_id)
    operation = db.query(DurableOperation).filter_by(id=operation_id).one_or_none()
    if operation is None or operation.resource_key != f"annotation-execution:{task.id}":
        raise ValueError("OPERATION_NOT_FOUND")
    try:
        revision_token, preview_token = operation.idempotency_key.split(":", 1)
        revision = int(revision_token)
        preview_id = uuid.UUID(preview_token)
    except (ValueError, TypeError):
        raise ValueError("OPERATION_NOT_FOUND")
    preview = db.query(AnnotationTaskPreview).filter_by(id=preview_id, task_id=task.id).one_or_none()
    if preview is None or preview.task_revision != revision:
        raise ValueError("OPERATION_NOT_FOUND")
    return task, operation


def list_annotation_execution_results(db, task_id, operation_id, owner_id, cursor=None, limit=50):
    _task, operation = _execution_operation_or_error(db, task_id, operation_id, owner_id)
    limit = max(1, min(int(limit), 200))
    query = db.query(AnnotationTaskExecutionResult).filter_by(task_id=task_id, operation_id=operation.id).order_by(
        AnnotationTaskExecutionResult.row_index.asc(), AnnotationTaskExecutionResult.id.asc()
    )
    total = query.count()
    if cursor:
        try:
            marker_id = uuid.UUID(cursor)
        except (ValueError, AttributeError) as error:
            raise ValueError("INVALID_CURSOR") from error
        marker = query.filter(AnnotationTaskExecutionResult.id == marker_id).one_or_none()
        if marker is None:
            raise ValueError("INVALID_CURSOR")
        query = query.filter(or_(
            AnnotationTaskExecutionResult.row_index > marker.row_index,
            and_(AnnotationTaskExecutionResult.row_index == marker.row_index, AnnotationTaskExecutionResult.id > marker.id),
        ))
    items = query.limit(limit + 1).all()
    has_next = len(items) > limit
    items = items[:limit]
    return {
        "items": [
            {"id": str(item.id), "sample_id": item.sample_id, "row_index": item.row_index, "task_revision": item.task_revision, "values": item.values or {}, "provenance": item.provenance or {}, "status": item.status}
            for item in items
        ],
        "total": total,
        "next_cursor": str(items[-1].id) if has_next and items else None,
    }


def list_annotation_execution_stats(db, task_id, operation_id, owner_id, *, kind="sample", cursor=None, limit=50):
    _task, operation = _execution_operation_or_error(db, task_id, operation_id, owner_id)
    if kind not in {"sample", "cluster", "rule", "final_label"}:
        raise ValueError("INVALID_STATS_KIND")
    limit = max(1, min(int(limit), 200))
    if kind == "sample":
        query = db.query(AnnotationTaskExecutionResult).filter_by(task_id=task_id, operation_id=operation.id).order_by(
            AnnotationTaskExecutionResult.row_index.asc(), AnnotationTaskExecutionResult.id.asc()
        )
        total = query.count()
        if cursor:
            try:
                marker_id = uuid.UUID(cursor)
            except (ValueError, AttributeError) as error:
                raise ValueError("INVALID_CURSOR") from error
            marker = query.filter(AnnotationTaskExecutionResult.id == marker_id).one_or_none()
            if marker is None:
                raise ValueError("INVALID_CURSOR")
            query = query.filter(or_(
                AnnotationTaskExecutionResult.row_index > marker.row_index,
                and_(AnnotationTaskExecutionResult.row_index == marker.row_index, AnnotationTaskExecutionResult.id > marker.id),
            ))
        page = query.limit(limit + 1).all()
        has_next = len(page) > limit
        page = page[:limit]
        items = [{"key": str(item.id), "sample_id": item.sample_id, "row_index": item.row_index, "status": item.status} for item in page]
        next_cursor = str(page[-1].id) if has_next and page else None
    else:
        items = list((operation.result_summary or {}).get("stats", {}).get(kind, []))
        start = 0
        if cursor:
            marker_index = next((index for index, item in enumerate(items) if str(item.get("key")) == str(cursor)), None)
            if marker_index is None:
                raise ValueError("INVALID_CURSOR")
            start = marker_index + 1
        page = items[start:start + limit + 1]
        has_next = len(page) > limit
        page = page[:limit]
        items = page
        next_cursor = str(page[-1].get("key")) if has_next and page else None
    return {"items": items, "total": total if kind == "sample" else len((operation.result_summary or {}).get("stats", {}).get(kind, [])), "next_cursor": next_cursor}


def list_annotation_operations(db, project_id, owner_id, cursor=None, limit=50):
    limit = max(1, min(int(limit), 200))
    task_ids = [task_id for (task_id,) in db.query(GenericAnnotationTask.id).filter(
        GenericAnnotationTask.project_id == project_id,
        GenericAnnotationTask.owner_id == owner_id,
    ).all()]
    if not task_ids:
        return {"items": [], "total": 0, "next_cursor": None}
    preview_rows = db.query(AnnotationTaskPreview.operation_id).filter(AnnotationTaskPreview.task_id.in_(task_ids)).all()
    preview_operation_ids = [operation_id for (operation_id,) in preview_rows]
    execution_keys = [f"annotation-execution:{task_id}" for task_id in task_ids]
    query = db.query(DurableOperation).filter(or_(
        DurableOperation.id.in_(preview_operation_ids) if preview_operation_ids else False,
        DurableOperation.resource_key.in_(execution_keys),
    ))
    query = query.order_by(DurableOperation.created_at.desc(), DurableOperation.id.desc())
    all_operations = query.all()
    total = len(all_operations)
    start = 0
    if cursor:
        try:
            marker_id = uuid.UUID(cursor)
        except (ValueError, TypeError) as error:
            raise ValueError("INVALID_CURSOR") from error
        marker_index = next((index for index, operation in enumerate(all_operations) if operation.id == marker_id), None)
        if marker_index is None:
            raise ValueError("INVALID_CURSOR")
        start = marker_index + 1
    operations = all_operations[start:start + limit + 1]
    page = []
    for operation in operations:
        task = None
        preview_id = None
        resource_type = None
        if operation.resource_key.startswith("annotation-preview:"):
            resource_type = "annotation_preview"
            try:
                preview_id = uuid.UUID(operation.resource_key.split(":", 1)[1])
            except ValueError:
                continue
            preview = db.query(AnnotationTaskPreview).filter_by(id=preview_id).one_or_none()
            task = db.query(GenericAnnotationTask).filter_by(id=preview.task_id).one_or_none() if preview else None
        elif operation.resource_key.startswith("annotation-execution:"):
            resource_type = "annotation_execution"
            try:
                task = db.query(GenericAnnotationTask).filter_by(id=uuid.UUID(operation.resource_key.split(":", 1)[1])).one_or_none()
                _revision, preview_token = operation.idempotency_key.split(":", 1)
                preview_id = uuid.UUID(preview_token)
            except (ValueError, TypeError):
                continue
        if task is None or task.project_id != project_id or task.owner_id != owner_id:
            continue
        page.append({
            "id": str(operation.id), "resource_type": resource_type, "task_id": str(task.id), "preview_id": str(preview_id) if preview_id else None,
            "state": operation.state, "stage": operation.stage, "progress": operation.progress, "attempt": operation.attempt,
            "error_code": operation.error_code, "checksum": operation.checksum, "result_summary": operation.result_summary or {},
            "created_at": operation.created_at.isoformat() if operation.created_at else None,
        })
    has_next = len(page) > limit
    page = page[:limit]
    return {"items": page, "total": total, "next_cursor": page[-1]["id"] if has_next and page else None}
