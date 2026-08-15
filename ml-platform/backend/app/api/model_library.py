"""Model library API - CRUD for trained models."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.model_library import ModelLibrary
from app.models.user import User
from app.api.auth import get_current_user
from app.api.project_security import audit_service, resolve_project_access
from app.services.audit import AuditIntent
from app.services.project_access import ProjectAccessService

router = APIRouter(prefix="/api/model-library", tags=["model_library"])
PROJECT_WRITE_ACTIONS = {
    "POST /api/model-library": "model_library.create",
    "PUT /api/model-library/{model_id}": "model_library.update",
    "DELETE /api/model-library/{model_id}": "model_library.delete",
    "POST /api/model-library/batch-delete": "model_library.batch_delete",
}


@router.get("")
def list_models(
    status: str = Query(None),
    framework: str = Query(None),
    category: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(ModelLibrary)
    if current_user.role != "admin":
        accessible = [
            project.id for project in ProjectAccessService()
            .accessible_project_query(db, current_user.id).all()
        ]
        q = q.filter(
            (ModelLibrary.owner_id == current_user.id)
            | (ModelLibrary.project_id.in_(accessible))
            | (ModelLibrary.is_public.is_(True))
        )
    if status:
        q = q.filter(ModelLibrary.status == status)
    if framework:
        q = q.filter(ModelLibrary.framework == framework)
    models = q.order_by(ModelLibrary.created_at.desc()).all()
    return {
        "items": [
            {
                "id": str(m.id),
                "name": m.name,
                "version": m.version,
                "status": m.status,
                "framework": m.framework,
                "backbone": m.backbone,
                "description": m.description,
                "metrics": m.metrics or {},
                "params": m.params or {},
                "model_path": m.model_path,
                "format": m.format,
                "file_size": m.file_size,
                "progress": m.progress,
                "tags": m.tags or [],
                "is_public": m.is_public,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in models
        ],
        "total": len(models),
    }


@router.get("/{model_id}")
def get_model(model_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    m = db.query(ModelLibrary).filter(ModelLibrary.id == uuid.UUID(model_id)).first()
    if not m:
        raise HTTPException(404, "Model not found")
    if current_user.role != "admin":
        if m.project_id is not None:
            if resolve_project_access(db, m.project_id, current_user.id) is None:
                raise HTTPException(404, "Model not found")
        elif m.owner_id != current_user.id and not m.is_public:
            raise HTTPException(404, "Model not found")
    return {
        "id": str(m.id),
        "name": m.name,
        "algorithm_id": str(m.algorithm_id) if m.algorithm_id else None,
        "project_id": str(m.project_id) if m.project_id else None,
        "version": m.version,
        "status": m.status,
        "framework": m.framework,
        "backbone": m.backbone,
        "description": m.description,
        "metrics": m.metrics or {},
        "params": m.params or {},
        "model_path": m.model_path,
        "format": m.format,
        "file_size": m.file_size,
        "progress": m.progress,
        "tags": m.tags or [],
        "is_public": m.is_public,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@router.post("")
def create_model(
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project_id = uuid.UUID(data["project_id"]) if data.get("project_id") else None
    model = ModelLibrary(
        id=uuid.uuid4(),
        name=data["name"],
        algorithm_id=uuid.UUID(data["algorithm_id"]) if data.get("algorithm_id") else None,
        project_id=project_id,
        owner_id=current_user.id,
        version=data.get("version", "v1"),
        framework=data.get("framework", ""),
        backbone=data.get("backbone", ""),
        description=data.get("description", ""),
        params=data.get("params", {}),
        tags=data.get("tags", []),
    )
    if project_id is None:
        db.add(model)
        db.commit()
    else:
        access = resolve_project_access(db, project_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.create",
            intent=AuditIntent(
                project_id=project_id, action="model_library.create",
                resource_type="model_library", resource_id=str(model.id),
                changes={"name": model.name, "version": model.version},
            ),
            allowed_changes={"name", "version"},
        ):
            db.add(model)
    db.refresh(model)
    return {"id": str(model.id), "name": model.name}


@router.put("/{model_id}")
def update_model(
    model_id: str,
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    m = db.query(ModelLibrary).filter(ModelLibrary.id == uuid.UUID(model_id)).first()
    if not m:
        raise HTTPException(404)
    keys = {"name", "status", "description", "version", "metrics", "progress", "is_public", "tags"}
    if m.project_id is None:
        if m.owner_id != current_user.id:
            raise HTTPException(404)
        for key in keys:
            if key in data:
                setattr(m, key, data[key])
        db.commit()
    else:
        access = resolve_project_access(db, m.project_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.update",
            intent=AuditIntent(
                project_id=m.project_id, action="model_library.update",
                resource_type="model_library", resource_id=str(m.id), changes=data,
            ),
            allowed_changes=keys,
        ):
            for key in keys:
                if key in data:
                    setattr(m, key, data[key])
    return {"status": "ok"}


@router.delete("/{model_id}")
def delete_model(
    model_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    m = db.query(ModelLibrary).filter(ModelLibrary.id == uuid.UUID(model_id)).first()
    if not m:
        raise HTTPException(404)
    if m.project_id is None:
        if m.owner_id != current_user.id:
            raise HTTPException(404)
        db.delete(m)
        db.commit()
    else:
        access = resolve_project_access(db, m.project_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="resource.delete",
            intent=AuditIntent(
                project_id=m.project_id, action="model_library.delete",
                resource_type="model_library", resource_id=str(m.id),
            ),
            allowed_changes=set(),
        ):
            db.delete(m)
    return {"status": "deleted"}


@router.get("/stats/summary")
def model_stats(db: Session = Depends(get_db)):
    total = db.query(ModelLibrary).count()
    completed = db.query(ModelLibrary).filter(ModelLibrary.status == "completed").count()
    training = db.query(ModelLibrary).filter(ModelLibrary.status == "training").count()
    published = db.query(ModelLibrary).filter(ModelLibrary.status == "published").count()

    # Top models by mAP
    top = db.query(ModelLibrary).filter(
        ModelLibrary.metrics.isnot(None)
    ).order_by(ModelLibrary.metrics.desc()).limit(10).all()

    return {
        "total_models": total,
        "completed": completed,
        "training": training,
        "published": published,
        "top_models": [
            {"id": str(m.id), "name": m.name, "metrics": m.metrics or {}}
            for m in top
        ],
    }


from pydantic import BaseModel
from typing import List

class BatchDeleteRequest(BaseModel):
    ids: List[str]

@router.post("/batch-delete", status_code=200)
def batch_delete_models(
    data: BatchDeleteRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = 0
    for mid_str in data.ids:
        try:
            uid = uuid.UUID(mid_str)
        except ValueError:
            continue
        model = db.query(ModelLibrary).filter(ModelLibrary.id == uid).first()
        if not model:
            continue
        if model.project_id is None:
            if model.owner_id != current_user.id:
                continue
            db.delete(model)
        else:
            access = resolve_project_access(db, model.project_id, current_user.id)
            with audit_service(db).project_action(
                db, request=request, actor=current_user, access=access,
                permission="resource.delete",
                intent=AuditIntent(
                    project_id=model.project_id, action="model_library.batch_delete",
                    resource_type="model_library", resource_id=str(model.id),
                ),
                allowed_changes=set(),
            ):
                db.delete(model)
        deleted += 1
    if db.new or db.dirty or db.deleted:
        db.commit()
    return {"deleted": deleted}
