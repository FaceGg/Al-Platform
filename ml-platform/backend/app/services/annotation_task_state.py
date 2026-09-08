"""State transitions and preview operations for generic annotation tasks."""

import uuid
from datetime import datetime, timezone

from app.models.access import AuditEvent
from app.models.platform_models import AnnotationTaskPreview, GenericAnnotationTask
from app.schemas.annotation_tasks import TaskAction

_TRANSITIONS = {
    "preview_ready": {TaskAction.publish: "awaiting_annotation", TaskAction.execute: "executing"},
    "executing": {TaskAction.pause: "paused", TaskAction.cancel: "cancelled", TaskAction.complete: "completed"},
    "awaiting_annotation": {TaskAction.pause: "paused", TaskAction.cancel: "cancelled", TaskAction.complete: "completed"},
    "in_progress": {TaskAction.pause: "paused", TaskAction.cancel: "cancelled", TaskAction.complete: "completed"},
    "paused": {TaskAction.execute: "executing", TaskAction.publish: "awaiting_annotation", TaskAction.cancel: "cancelled"},
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
        return existing
    if task.status in {"pending", "draft"}:
        task.status = "preview_ready"
    elif task.status not in {"previewing", "preview_ready"}:
        raise ValueError("TASK_STATE_INVALID")
    preview = AnnotationTaskPreview(task_id=task.id, task_revision=task_revision, config_hash=config_hash, created_by=actor_id, status="queued", summary={"sample_scope": task.sample_scope or {}})
    db.add(preview)
    db.commit()
    db.refresh(preview)
    return preview


def transition_annotation_task(db, task_id, expected_revision: int, action: TaskAction, actor_id, preview_id=None):
    task = _task_or_error(db, task_id, actor_id)
    if task.task_revision != expected_revision:
        raise ValueError("TASK_REVISION_CONFLICT")
    if action == TaskAction.execute:
        preview = db.query(AnnotationTaskPreview).filter_by(id=preview_id, task_id=task.id).one_or_none()
        if preview is None or preview.task_revision != expected_revision or preview.status not in {"queued", "ready", "completed"}:
            raise ValueError("PREVIEW_STALE")
    next_status = _TRANSITIONS.get(task.status, {}).get(action)
    if next_status is None:
        raise ValueError("TASK_STATE_INVALID")
    previous_status = task.status
    task.status = next_status
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


def list_annotation_tasks(db, project_id, owner_id, cursor=None, limit=50):
    limit = max(1, min(int(limit), 200))
    query = db.query(GenericAnnotationTask).filter(GenericAnnotationTask.project_id == project_id, GenericAnnotationTask.owner_id == owner_id).order_by(GenericAnnotationTask.created_at.desc(), GenericAnnotationTask.id.desc())
    if cursor:
        try:
            marker_id = uuid.UUID(cursor)
        except (ValueError, AttributeError) as error:
            raise ValueError("INVALID_CURSOR") from error
        marker = db.query(GenericAnnotationTask).filter(GenericAnnotationTask.id == marker_id).one_or_none()
        if marker is not None:
            query = query.filter(GenericAnnotationTask.created_at < marker.created_at)
    total = query.count()
    items = query.limit(limit + 1).all()
    has_next = len(items) > limit
    items = items[:limit]
    return {"items": [{"id": str(item.id), "project_id": str(item.project_id), "mode": item.mode, "status": item.status, "task_revision": item.task_revision, "sample_scope": item.sample_scope or {}} for item in items], "total": total, "next_cursor": str(items[-1].id) if has_next and items else None}


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
    return {"items": [{"id": str(item.id), "operation_id": str(item.operation_id), "task_revision": item.task_revision, "config_hash": item.config_hash, "status": item.status, "summary": item.summary or {}} for item in items], "total": len(all_items), "next_cursor": str(items[-1].id) if has_next and items else None}


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
