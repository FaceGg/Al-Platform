"""Industry-neutral annotation and AutoML task entrypoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.platform_models import GenericAnnotationTask
from app.models.project import Project
from app.models.user import User
from app.services.annotation_tasks import migrate_legacy_quality_run

router = APIRouter(tags=["generic-tasks"])


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


@router.get("/api/annotation-tasks")
def list_generic_annotation_tasks(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    tasks = db.query(GenericAnnotationTask).filter(
        GenericAnnotationTask.owner_id == current_user.id
    ).order_by(GenericAnnotationTask.created_at.desc()).all()
    return {"items": [_serialize(task) for task in tasks], "total": len(tasks)}


@router.post("/api/annotation-tasks", status_code=status.HTTP_201_CREATED)
def create_generic_annotation_task(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_id = _uuid(data.get("project_id"), "project_id")
    dataset_version_id = _uuid(data.get("dataset_version_id"), "dataset_version_id")
    label_schema_id = _uuid(data.get("label_schema_id"), "label_schema_id")
    _require_project(db, project_id, current_user)
    mode = data.get("mode", "manual")
    if mode not in {"manual", "automatic"}:
        raise HTTPException(status_code=422, detail={"code": "INVALID_TASK_MODE"})
    scope = data.get("sample_scope", {"kind": "all"})
    if not isinstance(scope, dict):
        raise HTTPException(status_code=422, detail={"code": "INVALID_SAMPLE_SCOPE"})
    task = GenericAnnotationTask(
        project_id=project_id,
        dataset_version_id=dataset_version_id,
        label_schema_id=label_schema_id,
        owner_id=current_user.id,
        mode=mode,
        sample_scope=scope,
        label_snapshot=data.get("label_snapshot", {}),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return _serialize(task)


@router.post("/api/automl-tasks", status_code=status.HTTP_201_CREATED)
def create_automl_task(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = dict(data)
    payload["mode"] = "automatic"
    return create_generic_annotation_task(payload, db, current_user)


@router.post("/api/projects/{project_id}/spot-weld/runs", status_code=status.HTTP_410_GONE)
def reject_legacy_spot_weld_write(project_id: uuid.UUID, data: dict | None = None):
    """Close the industry-specific write path during generic migration."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "GENERIC_API_REQUIRED",
            "message": "Use /api/annotation-tasks or /api/automl-tasks.",
            "legacy_route": f"/api/projects/{project_id}/spot-weld/runs",
        },
    )


@router.post("/api/annotation-tasks/{legacy_run_id}/migrate", status_code=status.HTTP_201_CREATED)
def migrate_legacy_task(
    legacy_run_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = migrate_legacy_quality_run(db, legacy_run_id)
    if task.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return _serialize(task)
