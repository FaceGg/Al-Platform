"""Industry-neutral annotation and AutoML task entrypoints."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.platform_models import GenericAnnotationTask
from app.models.project import Project
from app.models.user import User
from app.services.annotation_tasks import migrate_legacy_quality_run

router = APIRouter(tags=["generic-tasks"])


class GenericTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    dataset_version_id: uuid.UUID
    label_schema_id: uuid.UUID
    mode: Literal["manual", "automatic"] = "manual"
    sample_scope: dict = Field(default_factory=lambda: {"kind": "all"})
    label_snapshot: dict = Field(default_factory=dict)


def _uuid(value, field: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise HTTPException(status_code=422, detail={"code": "INVALID_UUID", "field": field}) from error


def _serialize(task: GenericAnnotationTask) -> dict:
    return {
        "id": str(task.id),
        "project_id": str(task.project_id),
        "dataset_version_id": str(task.dataset_version_id),
        "label_schema_id": str(task.label_schema_id),
        "mode": task.mode,
        "status": task.status,
        "sample_scope": task.sample_scope or {},
        "source_legacy_id": task.source_legacy_id,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def _require_project(db: Session, project_id: uuid.UUID, user: User) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})
    return project


def _contract_error(request: Request, code: str, message: str, status_code: int = 400, details: dict | None = None):
    request_id = str(getattr(request.state, "request_id", "")) or None
    return HTTPException(
        status_code=status_code,
        detail={"request_id": request_id, "code": code, "message": message, "details": details or {}},
    )


@router.get("/api/annotation-tasks")
def list_generic_annotation_tasks(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    tasks = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.owner_id == current_user.id
    ).order_by(GenericAnnotationTask.created_at.desc()).all()
    return {"items": [_serialize(task) for task in tasks], "total": len(tasks)}


def _request_context(request: Request, x_request_id: str | None, idempotency_key: str | None):
    request_id = getattr(request.state, "request_id", None)
    if not x_request_id or request_id is None or str(request_id) != x_request_id:
        raise _contract_error(request, "REQUEST_ID_REQUIRED", "X-Request-ID is required")
    if not idempotency_key or len(idempotency_key) > 128:
        raise _contract_error(request, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required")
    return idempotency_key


@router.post("/api/annotation-tasks", status_code=status.HTTP_201_CREATED)
def create_generic_annotation_task(
    data: GenericTaskCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = _request_context(request, x_request_id, idempotency_key)
    project_id = data.project_id
    _require_project(db, project_id, current_user)
    existing = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.idempotency_key == key,
        GenericAnnotationTask.owner_id == current_user.id,
    ).first()
    if existing is not None:
        return _serialize(existing)
    task = GenericAnnotationTask(
        project_id=project_id,
        dataset_version_id=data.dataset_version_id,
        label_schema_id=data.label_schema_id,
        owner_id=current_user.id,
        mode=data.mode,
        sample_scope=data.sample_scope,
        label_snapshot=data.label_snapshot,
        idempotency_key=key,
    )
    db.add(task)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(GenericAnnotationTask).filter(
            GenericAnnotationTask.idempotency_key == key,
            GenericAnnotationTask.owner_id == current_user.id,
        ).first()
        if existing is None:
            raise
        return _serialize(existing)
    db.refresh(task)
    return _serialize(task)


@router.post("/api/automl-tasks", status_code=status.HTTP_201_CREATED)
def create_automl_task(
    data: GenericTaskCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    payload = data.model_copy(update={"mode": "automatic"})
    return create_generic_annotation_task(payload, request, db, current_user, x_request_id, idempotency_key)


@router.post("/api/projects/{project_id}/spot-weld/runs", status_code=status.HTTP_410_GONE)
def reject_legacy_spot_weld_write(
    project_id: uuid.UUID,
    request: Request,
    data: dict | None = None,
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Close the industry-specific write path during generic migration."""
    _request_context(request, x_request_id, idempotency_key)
    request_id = str(getattr(request.state, "request_id", "")) or None
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "request_id": request_id,
            "code": "GENERIC_API_REQUIRED",
            "message": "Use /api/annotation-tasks or /api/automl-tasks.",
            "details": {},
            "legacy_route": f"/api/projects/{project_id}/spot-weld/runs",
        },
    )


@router.post("/api/annotation-tasks/{legacy_run_id}/migrate", status_code=status.HTTP_201_CREATED)
def migrate_legacy_task(
    legacy_run_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _request_context(request, x_request_id, idempotency_key)
    from app.models.spot_weld_quality import SpotWeldQualityRun
    run = db.query(SpotWeldQualityRun).filter(SpotWeldQualityRun.id == legacy_run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "LEGACY_QUALITY_RUN_NOT_FOUND", "message": "Legacy run not found"})
    if run.created_by_id != current_user.id or run.project_id is None:
        raise HTTPException(status_code=404, detail={"code": "LEGACY_QUALITY_RUN_NOT_FOUND", "message": "Legacy run not found"})
    _require_project(db, run.project_id, current_user)
    task = migrate_legacy_quality_run(db, legacy_run_id)
    return _serialize(task)
