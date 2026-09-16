"""Generic annotation task preview and state endpoints."""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.annotation_tasks import (
    AnnotationPreviewCreate,
    AnnotationTaskExecute,
    AnnotationTaskRevisionCommand,
    AnnotationTaskTransition,
    TaskAction,
)
from app.services.annotation_task_state import (
    create_annotation_preview,
    get_annotation_preview,
    list_annotation_execution_results,
    list_annotation_execution_stats,
    list_annotation_operations,
    list_annotation_preview_samples,
    list_annotation_previews,
    list_annotation_tasks,
    serialize_annotation_preview,
    transition_annotation_task,
)
from app.tasks.annotation_preview_tasks import enqueue_annotation_preview
from app.tasks.annotation_execution_tasks import enqueue_annotation_execution

router = APIRouter(tags=["annotation-task-state"])


def _error(error: ValueError, request: Request | None = None):
    code = str(error)
    status_code = 409 if code in {"TASK_REVISION_CONFLICT", "TASK_STATE_INVALID", "PREVIEW_STALE", "PREVIEW_NOT_COMPLETED", "PREVIEW_CONFIGURATION_INCOMPLETE", "PREVIEW_NEEDS_REVIEW", "PREVIEW_PROGRESS_REGRESSION", "PREVIEW_PROGRESS_INVALID", "INVALID_STATS_KIND", "IDEMPOTENCY_CONFLICT", "REOPEN_REASON_REQUIRED"} else 404
    request_id = request.headers.get("X-Request-ID") if request is not None else None
    return HTTPException(status_code=status_code, detail={"request_id": request_id or str(uuid.uuid4()), "code": code, "message": code.replace("_", " ").lower(), "details": {}})


def _serialize(task):
    return {"id": str(task.id), "project_id": str(task.project_id), "dataset_version_id": str(task.dataset_version_id), "label_schema_id": str(task.label_schema_id), "mode": task.mode, "status": task.status, "task_revision": task.task_revision, "sample_scope": task.sample_scope or {}, "source_legacy_id": task.source_legacy_id}


def _require_write_headers(request: Request, x_request_id: str | None, idempotency_key: str | None):
    request_id = getattr(request.state, "request_id", None)
    if not x_request_id or request_id is None or str(request_id) != x_request_id:
        raise HTTPException(
            status_code=400,
            detail={
                "request_id": str(request_id) if request_id else None,
                "code": "REQUEST_ID_REQUIRED",
                "message": "X-Request-ID is required.",
                "details": {},
            },
        )
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(
            status_code=400,
            detail={
                "request_id": str(request_id),
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "Idempotency-Key is required.",
                "details": {},
            },
        )


@router.post("/api/annotation-tasks/{task_id}/preview", status_code=status.HTTP_202_ACCEPTED)
def create_preview(task_id: uuid.UUID, data: AnnotationPreviewCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        preview = create_annotation_preview(db, task_id, data.task_revision, data.config_hash, current_user.id)
    except ValueError as error:
        raise _error(error, request) from error
    dispatch = enqueue_annotation_preview(task_id, preview.id, current_user.id) if getattr(preview, "_created_now", True) else None
    return {"operation_id": str(preview.operation_id), "preview_id": str(preview.id), "task_revision": preview.task_revision, "status": preview.status, "dispatch_id": getattr(dispatch, "id", None)}


@router.post("/api/annotation-tasks/{task_id}/transition")
def transition_task(task_id: uuid.UUID, data: AnnotationTaskTransition, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        task = transition_annotation_task(db, task_id, data.task_revision, data.action, current_user.id, data.preview_id)
    except ValueError as error:
        raise _error(error, request) from error
    payload = _serialize(task)
    operation_id = getattr(task, "_execution_operation_id", None)
    if data.action.value == "execute" and operation_id is not None:
        preview_id = getattr(task, "_execution_preview_id", data.preview_id)
        dispatch = enqueue_annotation_execution(task.id, preview_id, operation_id, current_user.id)
        payload["operation_id"] = str(operation_id)
        payload["dispatch_id"] = getattr(dispatch, "id", None)
    return payload


@router.post("/api/annotation-tasks/{task_id}/execute", status_code=status.HTTP_202_ACCEPTED)
def execute_task(task_id: uuid.UUID, data: AnnotationTaskExecute, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Queue automatic execution while retaining the shared transition guard."""
    transition = AnnotationTaskTransition(task_revision=data.task_revision, action=TaskAction.execute, preview_id=data.preview_id)
    return transition_task(task_id, transition, request, db, current_user)


def _lifecycle_transition(
    task_id: uuid.UUID,
    data: AnnotationTaskRevisionCommand,
    action: TaskAction,
    request: Request,
    x_request_id: str | None,
    idempotency_key: str | None,
    db: Session,
    current_user: User,
):
    _require_write_headers(request, x_request_id, idempotency_key)
    try:
        task = transition_annotation_task(
            db,
            task_id,
            data.task_revision,
            action,
            current_user.id,
            preview_id=data.preview_id,
            idempotency_key=idempotency_key,
            request_id=getattr(request.state, "request_id", None),
            reason=data.reason,
        )
    except ValueError as error:
        raise _error(error, request) from error
    stored = getattr(task, "_command_response_payload", None)
    if isinstance(stored, dict):
        return stored
    payload = _serialize(task)
    operation_id = getattr(task, "_command_operation_id", None)
    if operation_id is not None:
        payload["operation_id"] = str(operation_id)
    return payload


@router.post("/api/annotation-tasks/{task_id}/publish", status_code=status.HTTP_202_ACCEPTED)
def publish_task(
    task_id: uuid.UUID,
    data: AnnotationTaskRevisionCommand,
    request: Request,
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _lifecycle_transition(task_id, data, TaskAction.publish, request, x_request_id, idempotency_key, db, current_user)


@router.post("/api/annotation-tasks/{task_id}/pause", status_code=status.HTTP_202_ACCEPTED)
def pause_task(
    task_id: uuid.UUID,
    data: AnnotationTaskRevisionCommand,
    request: Request,
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _lifecycle_transition(task_id, data, TaskAction.pause, request, x_request_id, idempotency_key, db, current_user)


@router.post("/api/annotation-tasks/{task_id}/reopen", status_code=status.HTTP_202_ACCEPTED)
def reopen_task(
    task_id: uuid.UUID,
    data: AnnotationTaskRevisionCommand,
    request: Request,
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _lifecycle_transition(task_id, data, TaskAction.reopen, request, x_request_id, idempotency_key, db, current_user)


@router.get("/api/annotation-tasks/{task_id}/previews")
def list_previews(task_id: uuid.UUID, request: Request, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return list_annotation_previews(db, task_id, current_user.id, cursor=cursor, limit=limit)
    except ValueError as error:
        raise _error(error, request) from error


@router.get("/api/annotation-tasks/{task_id}/previews/{preview_id}")
def preview_detail(task_id: uuid.UUID, preview_id: uuid.UUID, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        preview = get_annotation_preview(db, task_id, preview_id, current_user.id)
    except ValueError as error:
        raise _error(error, request) from error
    return serialize_annotation_preview(preview)


@router.get("/api/annotation-tasks/{task_id}/previews/{preview_id}/samples")
def preview_samples(task_id: uuid.UUID, preview_id: uuid.UUID, request: Request, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return list_annotation_preview_samples(db, task_id, preview_id, current_user.id, cursor=cursor, limit=limit)
    except ValueError as error:
        raise _error(error, request) from error


@router.get("/api/annotation-tasks/{task_id}/executions/{operation_id}/results")
def execution_results(task_id: uuid.UUID, operation_id: uuid.UUID, request: Request, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return list_annotation_execution_results(db, task_id, operation_id, current_user.id, cursor=cursor, limit=limit)
    except ValueError as error:
        raise _error(error, request) from error


@router.get("/api/annotation-tasks/{task_id}/executions/{operation_id}/stats")
def execution_stats(task_id: uuid.UUID, operation_id: uuid.UUID, request: Request, kind: str = Query(default="sample"), cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return list_annotation_execution_stats(db, task_id, operation_id, current_user.id, kind=kind, cursor=cursor, limit=limit)
    except ValueError as error:
        raise _error(error, request) from error


@router.get("/api/annotation-operations")
def annotation_operations(project_id: uuid.UUID, request: Request, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return list_annotation_operations(db, project_id, current_user.id, cursor=cursor, limit=limit)
    except ValueError as error:
        raise _error(error, request) from error
