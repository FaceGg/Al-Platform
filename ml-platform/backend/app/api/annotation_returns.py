"""Data-management APIs for accepting or returning annotation batches."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.services.annotation_returns import (
    AnnotationReturnError,
    accept_return_batch,
    diff_return_batch,
    export_return_batch_dataset,
    export_return_batch_preview,
    list_return_batches,
    require_return_batch_project_owner,
    reject_return_batch,
)

router = APIRouter(tags=["annotation-returns"])


class ReturnBatchReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_revision: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=2000)


class ExportDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=256)
    # Chinese label column names must be renamed to English identifiers here.
    renames: dict[str, str] = Field(default_factory=dict)


def _error(error: AnnotationReturnError, request: Request):
    status = 422 if error.code in {"RETURN_REASON_REQUIRED", "EXPORT_NAME_REQUIRED", "EXPORT_LABEL_NAME_INVALID"} else 409
    if error.code in {"RETURN_BATCH_NOT_FOUND", "ANNOTATION_TASK_NOT_FOUND", "PROJECT_NOT_FOUND"}:
        status = 404
    return HTTPException(
        status_code=status,
        detail={"request_id": str(getattr(request.state, "request_id", "")) or None, "code": error.code, "message": error.code.replace("_", " ").lower(), "details": {}},
    )


def _project_or_error(db: Session, project_id: uuid.UUID, user: User) -> None:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})


@router.get("/api/projects/{project_id}/annotation-return-batches")
def list_project_return_batches(
    project_id: uuid.UUID,
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del request
    _project_or_error(db, project_id, current_user)
    try:
        return list_return_batches(db, project_id, cursor, limit)
    except AnnotationReturnError as error:
        raise HTTPException(status_code=422, detail={"code": error.code}) from error


@router.get("/api/annotation-return-batches/{return_batch_id}/diff")
def return_batch_diff(
    return_batch_id: uuid.UUID,
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        require_return_batch_project_owner(db, return_batch_id, current_user.id)
        return diff_return_batch(db, return_batch_id, cursor, limit)
    except AnnotationReturnError as error:
        raise _error(error, request) from error


@router.post("/api/annotation-return-batches/{return_batch_id}/accept")
def accept_batch(
    return_batch_id: uuid.UUID,
    data: ReturnBatchReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        require_return_batch_project_owner(db, return_batch_id, current_user.id)
        version = accept_return_batch(db, return_batch_id, data.task_revision, current_user)
    except AnnotationReturnError as error:
        raise _error(error, request) from error
    return {"dataset_version_id": str(version.id), "status": version.status, "version": version.version}


@router.post("/api/annotation-return-batches/{return_batch_id}/return")
def return_batch(
    return_batch_id: uuid.UUID,
    data: ReturnBatchReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        require_return_batch_project_owner(db, return_batch_id, current_user.id)
        batch = reject_return_batch(db, return_batch_id, data.task_revision, data.reason or "", current_user)
    except AnnotationReturnError as error:
        raise _error(error, request) from error
    return {"id": str(batch.id), "state": batch.state}


@router.get("/api/annotation-return-batches/{return_batch_id}/export-preview")
def export_preview(
    return_batch_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        require_return_batch_project_owner(db, return_batch_id, current_user.id)
        return export_return_batch_preview(db, return_batch_id)
    except AnnotationReturnError as error:
        raise _error(error, request) from error


@router.post("/api/annotation-return-batches/{return_batch_id}/export-dataset")
def export_dataset(
    return_batch_id: uuid.UUID,
    data: ExportDatasetRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        require_return_batch_project_owner(db, return_batch_id, current_user.id)
        artifact, version, mappings = export_return_batch_dataset(
            db, return_batch_id, data.name, current_user, renames=data.renames,
        )
    except AnnotationReturnError as error:
        raise _error(error, request) from error
    return {
        "dataset_id": str(artifact.id),
        "name": artifact.name,
        "dataset_version_id": str(version.id),
        "version": version.version,
        "row_count": version.row_count,
        "label_mappings": mappings,
    }
