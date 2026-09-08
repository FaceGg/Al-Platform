"""Generic annotation task preview and state endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.annotation_tasks import AnnotationPreviewCreate, AnnotationTaskTransition
from app.services.annotation_task_state import create_annotation_preview, get_annotation_preview, list_annotation_previews, list_annotation_tasks, transition_annotation_task
from app.tasks.annotation_preview_tasks import enqueue_annotation_preview

router = APIRouter(tags=["annotation-task-state"])


def _error(error: ValueError):
    code = str(error)
    status_code = 409 if code in {"TASK_REVISION_CONFLICT", "TASK_STATE_INVALID", "PREVIEW_STALE"} else 404
    return HTTPException(status_code=status_code, detail={"code": code})


def _serialize(task):
    return {"id": str(task.id), "project_id": str(task.project_id), "dataset_version_id": str(task.dataset_version_id), "label_schema_id": str(task.label_schema_id), "mode": task.mode, "status": task.status, "task_revision": task.task_revision, "sample_scope": task.sample_scope or {}, "source_legacy_id": task.source_legacy_id}


@router.post("/api/annotation-tasks/{task_id}/preview", status_code=status.HTTP_202_ACCEPTED)
def create_preview(task_id: uuid.UUID, data: AnnotationPreviewCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        preview = create_annotation_preview(db, task_id, data.task_revision, data.config_hash, current_user.id)
    except ValueError as error:
        raise _error(error) from error
    dispatch = enqueue_annotation_preview(task_id, preview.id, current_user.id)
    return {"operation_id": str(preview.operation_id), "preview_id": str(preview.id), "task_revision": preview.task_revision, "status": preview.status, "dispatch_id": getattr(dispatch, "id", None)}


@router.post("/api/annotation-tasks/{task_id}/transition")
def transition_task(task_id: uuid.UUID, data: AnnotationTaskTransition, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        task = transition_annotation_task(db, task_id, data.task_revision, data.action, current_user.id, data.preview_id)
    except ValueError as error:
        raise _error(error) from error
    return _serialize(task)


@router.get("/api/annotation-tasks/{task_id}/previews")
def list_previews(task_id: uuid.UUID, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return list_annotation_previews(db, task_id, current_user.id, cursor=cursor, limit=limit)
    except ValueError as error:
        raise _error(error) from error


@router.get("/api/annotation-tasks/{task_id}/previews/{preview_id}")
def preview_detail(task_id: uuid.UUID, preview_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        preview = get_annotation_preview(db, task_id, preview_id, current_user.id)
    except ValueError as error:
        raise _error(error) from error
    return {"id": str(preview.id), "operation_id": str(preview.operation_id), "task_revision": preview.task_revision, "config_hash": preview.config_hash, "status": preview.status, "progress": preview.progress, "summary": preview.summary or {}, "error": preview.error, "completed_at": preview.completed_at.isoformat() if preview.completed_at else None}
