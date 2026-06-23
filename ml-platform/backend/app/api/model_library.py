"""Model library API - CRUD for trained models."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.model_library import ModelLibrary
from app.models.user import User
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/model-library", tags=["model_library"])


@router.get("")
def list_models(
    status: str = Query(None),
    framework: str = Query(None),
    category: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(ModelLibrary)
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
def create_model(data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    model = ModelLibrary(
        name=data["name"],
        algorithm_id=uuid.UUID(data["algorithm_id"]) if data.get("algorithm_id") else None,
        project_id=uuid.UUID(data["project_id"]) if data.get("project_id") else None,
        owner_id=current_user.id,
        version=data.get("version", "v1"),
        framework=data.get("framework", ""),
        backbone=data.get("backbone", ""),
        description=data.get("description", ""),
        params=data.get("params", {}),
        tags=data.get("tags", []),
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return {"id": str(model.id), "name": model.name}


@router.put("/{model_id}")
def update_model(model_id: str, data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    m = db.query(ModelLibrary).filter(ModelLibrary.id == uuid.UUID(model_id)).first()
    if not m:
        raise HTTPException(404)
    for key in ["name", "status", "description", "version", "metrics", "progress", "is_public", "tags"]:
        if key in data:
            setattr(m, key, data[key])
    db.commit()
    return {"status": "ok"}


@router.delete("/{model_id}")
def delete_model(model_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    m = db.query(ModelLibrary).filter(ModelLibrary.id == uuid.UUID(model_id)).first()
    if not m:
        raise HTTPException(404)
    db.delete(m)
    db.commit()
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
