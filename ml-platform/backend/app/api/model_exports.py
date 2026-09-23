"""Project-scoped model export operations and downloads."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.project_security import require_project_access
from app.config import settings
from app.database import get_db
from app.models.artifact import Artifact
from app.models.model_export import ModelExport
from app.models.model_registry import ModelVersion
from app.models.operation import DurableOperation
from app.models.platform_models import GenericAnnotationTask
from app.models.user import User
from app.schemas.model_export import ExportValidationResponse, ModelExportCreate
from app.services.model_export import ExportError, build_export_package, validate_export_package
from app.tasks.model_export_tasks import enqueue_model_export

router = APIRouter(tags=["model_exports"])


def _version(db: Session, version_id: UUID, user_id):
    item = db.query(ModelVersion).filter(ModelVersion.id == version_id).first()
    if item is None:
        raise HTTPException(404, {"code": "MODEL_VERSION_NOT_FOUND"})
    project_id = item.registered_model.project_id
    require_project_access(db, project_id, user_id, "project.read")
    return item, project_id


def _view(item: ModelExport):
    return {
        "id": str(item.id),
        "operation_id": str(item.operation_id) if item.operation_id else None,
        "model_version_id": str(item.model_version_id),
        "annotation_task_id": str(item.annotation_task_id) if item.annotation_task_id else None,
        "annotation_task_revision": item.annotation_task_revision,
        "include_runtime": item.include_runtime,
        "status": item.status,
        "package_path": bool(item.package_path),
        "manifest_sha256": item.manifest_sha256,
        "error": item.error,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }


@router.post("/api/model-versions/{version_id}/exports", status_code=202)
def create_export(
    version_id: UUID,
    data: ModelExportCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    version, project_id = _version(db, version_id, current_user.id)
    if getattr(version, "lifecycle_state", None) != "enabled":
        raise HTTPException(409, {"code": "MODEL_VERSION_NOT_ENABLED"})
    if data.model_version_id != version_id:
        raise HTTPException(422, {"code": "MODEL_VERSION_MISMATCH"})
    if data.annotation_task_id is not None:
        task = db.query(GenericAnnotationTask).filter(GenericAnnotationTask.id == data.annotation_task_id).first()
        if task is None or task.project_id != project_id:
            raise HTTPException(404, {"code": "ANNOTATION_TASK_NOT_FOUND"})
        if data.annotation_task_revision is not None and task.task_revision != data.annotation_task_revision:
            raise HTTPException(409, {"code": "ANNOTATION_TASK_REVISION_MISMATCH"})
    idem = request.headers.get("Idempotency-Key")
    if not idem:
        raise HTTPException(400, {"code": "IDEMPOTENCY_KEY_REQUIRED"})
    scope = f"model-version:{version_id}:task:{data.annotation_task_id or 'none'}:revision:{data.annotation_task_revision if data.annotation_task_revision is not None else 'none'}"
    payload = data.model_dump(mode="json")
    request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    existing = db.query(ModelExport).filter(ModelExport.idempotency_scope == scope, ModelExport.idempotency_key == idem).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(409, {"code": "MODEL_EXPORT_IDEMPOTENCY_CONFLICT"})
        return _view(existing)
    item = ModelExport(
        model_version_id=version_id,
        annotation_task_id=data.annotation_task_id,
        annotation_task_revision=data.annotation_task_revision,
        idempotency_scope=scope,
        idempotency_key=idem,
        request_hash=request_hash,
        include_runtime=data.include_runtime,
        status="queued",
        created_by_id=current_user.id,
    )
    db.add(item)
    db.flush()
    operation = DurableOperation(
        resource_key=f"model-export:{item.id}",
        idempotency_key=idem,
        state="queued",
        stage="queued",
    )
    db.add(operation)
    db.flush()
    item.operation_id = operation.id
    db.commit()
    db.refresh(item)
    enqueue_model_export(item.id)
    return _view(item)


@router.get("/api/model-exports/{export_id}")
def get_export(export_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(ModelExport).filter(ModelExport.id == export_id).first()
    if item is None:
        raise HTTPException(404, {"code": "MODEL_EXPORT_NOT_FOUND"})
    _version(db, item.model_version_id, current_user.id)
    return _view(item)


@router.get("/api/model-versions/{version_id}/exports")
def list_exports(version_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _version(db, version_id, current_user.id)
    items = db.query(ModelExport).filter(ModelExport.model_version_id == version_id).order_by(ModelExport.created_at.desc()).all()
    return {"items": [_view(item) for item in items], "total": len(items)}


@router.post("/api/model-exports/{export_id}/validate", response_model=ExportValidationResponse)
def validate_export(export_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(ModelExport).filter(ModelExport.id == export_id).first()
    if item is None:
        raise HTTPException(404, {"code": "MODEL_EXPORT_NOT_FOUND"})
    _version(db, item.model_version_id, current_user.id)
    if item.status != "completed" or not item.package_path:
        raise HTTPException(409, {"code": "MODEL_EXPORT_NOT_READY"})
    try:
        report = validate_export_package(item.package_path)
    except ExportError as error:
        return ExportValidationResponse(valid=False, errors=[{"code": error.code}])
    return ExportValidationResponse(valid=report.valid, files=list(report.files), errors=list(report.errors))


@router.get("/api/model-exports/{export_id}/download")
def download_export(export_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(ModelExport).filter(ModelExport.id == export_id).first()
    if item is None:
        raise HTTPException(404, {"code": "MODEL_EXPORT_NOT_FOUND"})
    _version(db, item.model_version_id, current_user.id)
    if item.status != "completed" or not item.package_path:
        raise HTTPException(409, {"code": "MODEL_EXPORT_NOT_READY"})
    path = Path(item.package_path)
    if not path.is_file():
        raise HTTPException(404, {"code": "MODEL_EXPORT_PACKAGE_MISSING"})
    try:
        report = validate_export_package(path)
    except ExportError as error:
        raise HTTPException(409, {"code": error.code}) from error
    if not report.valid:
        raise HTTPException(409, {"code": "MODEL_EXPORT_INVALID"})
    # Conditional update turns the authorization into a single-use capability
    # even if two clients race after both pass package validation.
    from sqlalchemy import update
    from datetime import datetime, timezone
    consumed = db.execute(
        update(ModelExport)
        .where(ModelExport.id == item.id, ModelExport.download_used_at.is_(None))
        .values(download_used_at=datetime.now(timezone.utc).replace(tzinfo=None))
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, {"code": "MODEL_EXPORT_DOWNLOAD_ALREADY_USED"})
    db.commit()
    return FileResponse(path, media_type="application/zip", filename=path.name)
