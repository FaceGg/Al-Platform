"""Platform API management (component marketplace)."""
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.api_model import PlatformAPI
from app.models.user import User
from app.api.auth import get_current_user
from app.services.resource_access import ResourceAccessService
from app.services.api_publication import APIPublicationError, publish_deployment, unpublish_deployment

router = APIRouter(prefix="/api/platform/apis", tags=["platform_apis"])


class APIType(str, Enum):
    model = "model"
    orchestration = "orchestration"
    custom = "custom"


class APIMethod(str, Enum):
    get = "GET"
    post = "POST"
    put = "PUT"
    patch = "PATCH"
    delete = "DELETE"


class PlatformAPICreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    api_type: APIType = APIType.model
    algorithm_type: str = Field(default="", max_length=64)
    endpoint: str = Field(min_length=1, max_length=512)
    method: APIMethod = APIMethod.post
    version: str = Field(default="v1", min_length=1, max_length=32)
    description: str = Field(default="", max_length=10000)
    request_schema: dict[str, Any] = Field(default_factory=dict)
    response_schema: dict[str, Any] = Field(default_factory=dict)
    source_kind: APIType = APIType.custom
    source_id: Optional[uuid.UUID] = None
    is_public: bool = False

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        if not value.startswith("/api/"):
            raise ValueError("endpoint must be an internal /api/ path")
        return value


class PlatformAPIItem(BaseModel):
    id: str
    name: str
    api_type: str
    algorithm_type: str = ""
    endpoint: str
    method: str
    version: str
    status: str
    source_kind: str
    source_id: Optional[str] = None
    description: str = ""
    request_schema: dict[str, Any] = Field(default_factory=dict)
    response_schema: dict[str, Any] = Field(default_factory=dict)
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    is_public: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    last_error: Optional[str] = None


class PlatformAPIUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=256)
    status: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=10000)
    endpoint: Optional[str] = Field(default=None, max_length=512)
    is_public: Optional[bool] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in {"published", "offline", "failed"}:
            raise ValueError("unsupported API status")
        return value

    @field_validator("endpoint")
    @classmethod
    def validate_update_endpoint(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.startswith("/api/"):
            raise ValueError("endpoint must be an internal /api/ path")
        return value


def _serialize_api(api: PlatformAPI) -> PlatformAPIItem:
    return PlatformAPIItem(
        id=str(api.id), name=api.name, api_type=api.api_type,
        algorithm_type=api.algorithm_type or "", endpoint=api.endpoint or "",
        method=api.method, version=api.version, status=api.status,
        source_kind=api.source_kind or api.api_type,
        source_id=str(api.source_id) if api.source_id else None,
        description=api.description or "", request_schema=api.request_schema or {},
        response_schema=api.response_schema or {}, total_calls=api.total_calls or 0,
        success_calls=api.success_calls or 0, failed_calls=api.failed_calls or 0,
        is_public=bool(api.is_public), created_at=api.created_at,
        updated_at=api.updated_at, published_at=api.published_at,
        last_error=api.last_error,
    )


@router.get("")
def list_apis(
    api_type: str = Query(None),
    status: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(PlatformAPI).filter(or_(
        PlatformAPI.owner_id == current_user.id,
        PlatformAPI.is_public.is_(True),
    ))
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
                "source_kind": a.source_kind or a.api_type,
                "source_id": str(a.source_id) if a.source_id else None,
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


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PlatformAPIItem)
def create_api(data: PlatformAPICreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if data.api_type != APIType.custom or data.source_kind != APIType.custom or data.source_id is not None:
        raise HTTPException(
            422,
            detail="model and orchestration APIs must be created from executable sources",
        )
    api = PlatformAPI(
        name=data.name, api_type=data.api_type.value,
        algorithm_type=data.algorithm_type, endpoint=data.endpoint,
        method=data.method.value, version=data.version,
        description=data.description, request_schema=data.request_schema,
        response_schema=data.response_schema, source_kind=data.source_kind.value,
        source_id=data.source_id,
        owner_id=current_user.id,
        is_public=data.is_public,
    )
    db.add(api)
    db.commit()
    db.refresh(api)
    return _serialize_api(api)


@router.put("/{api_id}", response_model=PlatformAPIItem)
def update_api(api_id: str, data: PlatformAPIUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    api = ResourceAccessService().require_owned(
        db,
        PlatformAPI,
        api_id,
        current_user.id,
    )
    if api.source_id is not None or api.source_kind != "custom":
        raise HTTPException(409, detail="source-bound APIs are managed by their deployment lifecycle")
    changes = data.model_dump(exclude_unset=True)
    if "status" in changes:
        allowed = {
            "published": {"offline", "failed", "published"},
            "offline": {"published", "offline"},
            "failed": {"offline", "failed"},
        }
        if changes["status"] not in allowed.get(api.status, set()):
            raise HTTPException(422, detail="invalid API status transition")
    for key, value in changes.items():
        setattr(api, key, value)
    if changes.get("status") == "published":
        api.published_at = datetime.utcnow()
    db.commit()
    db.refresh(api)
    return _serialize_api(api)


@router.delete("/{api_id}")
def delete_api(api_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    api = ResourceAccessService().require_owned(
        db,
        PlatformAPI,
        api_id,
        current_user.id,
    )
    if api.source_id is not None or api.source_kind != "custom":
        raise HTTPException(409, detail="source-bound APIs cannot be deleted directly")
    db.delete(api)
    db.commit()
    return {"status": "deleted"}


@router.get("/stats")
def api_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(PlatformAPI).filter(or_(
        PlatformAPI.owner_id == current_user.id,
        PlatformAPI.is_public.is_(True),
    ))
    total = query.count()
    published = query.filter(PlatformAPI.status == "published").count()
    total_calls = query.with_entities(PlatformAPI.total_calls).all()
    return {
        "total_apis": total,
        "published": published,
        "offline": query.filter(PlatformAPI.status == "offline").count(),
        "failed": query.filter(PlatformAPI.status == "failed").count(),
        "total_calls": sum(c[0] or 0 for c in total_calls),
    }


@router.post("/publish/deployment/{deployment_id}", response_model=PlatformAPIItem, status_code=status.HTTP_201_CREATED)
def publish_deployment_api(
    deployment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return _serialize_api(publish_deployment(db, deployment_id, current_user.id))
    except APIPublicationError as error:
        status_code = 404 if error.code.endswith("NOT_FOUND") else 403 if error.code.endswith("PERMISSION_DENIED") else 409
        raise HTTPException(status_code, detail={"code": error.code, "message": str(error)}) from error


@router.post("/publish/deployment/{deployment_id}/offline", response_model=PlatformAPIItem)
def unpublish_deployment_api(
    deployment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return _serialize_api(unpublish_deployment(db, deployment_id, current_user.id))
    except APIPublicationError as error:
        raise HTTPException(404, detail={"code": error.code, "message": str(error)}) from error
