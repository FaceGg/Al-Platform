"""Platform API management (component marketplace)."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.api_model import PlatformAPI
from app.models.user import User
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/platform/apis", tags=["platform_apis"])


@router.get("")
def list_apis(
    api_type: str = Query(None),
    status: str = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(PlatformAPI)
    if api_type:
        q = q.filter(PlatformAPI.api_type == api_type)
    if status:
        q = q.filter(PlatformAPI.status == status)
    apis = q.order_by(PlatformAPI.created_at.desc()).all()
    return {
        "items": [
            {
                "id": str(a.id),
                "name": a.name,
                "api_type": a.api_type,
                "algorithm_type": a.algorithm_type,
                "endpoint": a.endpoint,
                "method": a.method,
                "version": a.version,
                "status": a.status,
                "description": a.description,
                "total_calls": a.total_calls,
                "success_calls": a.success_calls,
                "failed_calls": a.failed_calls,
                "is_public": a.is_public,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in apis
        ],
        "total": len(apis),
    }


@router.post("")
def create_api(data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    api = PlatformAPI(
        name=data["name"],
        api_type=data.get("api_type", "model"),
        algorithm_type=data.get("algorithm_type", ""),
        endpoint=data.get("endpoint", ""),
        method=data.get("method", "POST"),
        version=data.get("version", "v1"),
        description=data.get("description", ""),
        request_schema=data.get("request_schema", {}),
        owner_id=current_user.id,
        is_public=data.get("is_public", False),
    )
    db.add(api)
    db.commit()
    db.refresh(api)
    return {"id": str(api.id), "name": api.name}


@router.put("/{api_id}")
def update_api(api_id: str, data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    api = db.query(PlatformAPI).filter(PlatformAPI.id == uuid.UUID(api_id)).first()
    if not api:
        raise HTTPException(404)
    for key in ["name", "status", "description", "endpoint", "is_public"]:
        if key in data:
            setattr(api, key, data[key])
    db.commit()
    return {"status": "ok"}


@router.delete("/{api_id}")
def delete_api(api_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    api = db.query(PlatformAPI).filter(PlatformAPI.id == uuid.UUID(api_id)).first()
    if not api:
        raise HTTPException(404)
    db.delete(api)
    db.commit()
    return {"status": "deleted"}


@router.get("/stats")
def api_stats(db: Session = Depends(get_db)):
    total = db.query(PlatformAPI).count()
    published = db.query(PlatformAPI).filter(PlatformAPI.status == "published").count()
    total_calls = db.query(PlatformAPI).with_entities(PlatformAPI.total_calls).all()
    return {
        "total_apis": total,
        "published": published,
        "total_calls": sum(c[0] or 0 for c in total_calls),
    }
