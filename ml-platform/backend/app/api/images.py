"""Week 15 image catalog API: immutable digest registry with scan-status
coupling, plus the decision-gated build endpoint."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.developer_resources import ContainerImage, ImageBuild
from app.models.user import User
from app.schemas.developer_resources import (
    ImageBuildRequest,
    ImageBuildResponse,
    ImageRegisterRequest,
    ImageResponse,
    ImageUpdateRequest,
)
from app.services.audit import AuditIntent, AuditService
from app.services.image_build_service import ImageBuildError, record_build
from app.services.project_access import ProjectAccessError, ProjectAccessService

router = APIRouter(prefix="/api/images", tags=["images"])

DIGEST_PATTERN_PREFIX = "sha256:"
import re

DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


def _http_access(error: ProjectAccessError):
    raise HTTPException(404 if error.hidden else 403, {"code": error.code, "message": str(error)})


def _audit(db: Session, request: Request, actor, project_id, permission: str, action: str, resource_id, changes: dict, allowed: set[str]):
    access = ProjectAccessService().require(db, project_id, actor.id, permission)
    return AuditService(sessionmaker(bind=db.get_bind())).project_action(
        db,
        request=request,
        actor=actor,
        access=access,
        permission=permission,
        intent=AuditIntent(
            project_id=project_id,
            action=action,
            resource_type="container_image",
            resource_id=str(resource_id),
            changes=changes,
        ),
        allowed_changes=allowed,
    )


def _visible_images_query(db: Session, user_id):
    project_ids = [row.id for row in ProjectAccessService().accessible_project_query(db, user_id).all()]
    from sqlalchemy import or_

    return db.query(ContainerImage).filter(
        or_(ContainerImage.visibility == "platform", ContainerImage.project_id.in_(project_ids or [uuid.uuid4()]))
    )


@router.post("", response_model=ImageResponse, status_code=201)
def register_image(
    data: ImageRegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not DIGEST_PATTERN.match(data.digest or ""):
        raise HTTPException(422, {"code": "IMAGE_DIGEST_INVALID", "message": "digest must be sha256:<64 hex>"})
    project_id = None
    if data.visibility == "project":
        # Registration is a resource creation against the caller's first
        # accessible project (platform images carry no project owner).
        owned = ProjectAccessService().accessible_project_query(db, current_user.id).first()
        if owned is None:
            raise HTTPException(403, {"code": "PROJECT_PERMISSION_DENIED", "message": "no accessible project"})
        project_id = owned.id
        try:
            ProjectAccessService().require(db, project_id, current_user.id, "resource.create")
        except ProjectAccessError as error:
            _http_access(error)
    exists = (
        db.query(ContainerImage.id)
        .filter(
            ContainerImage.registry == data.registry,
            ContainerImage.repository == data.repository,
            ContainerImage.digest == data.digest,
        )
        .first()
    )
    if exists is not None:
        raise HTTPException(409, {"code": "IMAGE_DIGEST_EXISTS", "message": "digest already registered"})
    image = ContainerImage(
        project_id=project_id,
        registry=data.registry,
        repository=data.repository,
        digest=data.digest,
        visibility=data.visibility,
        scan_status=data.scan_status,
        source="manual_registry",
        description=data.description,
        registered_by=current_user.id,
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    with _audit(db, request, current_user, project_id or _any_project(db, current_user), "resource.create", "image.register", image.id, {"digest": data.digest}, set()):
        pass
    return ImageResponse.model_validate(image)


def _any_project(db: Session, user):
    return ProjectAccessService().accessible_project_query(db, user.id).first().id


@router.get("")
def list_images(
    request: Request,
    response: Response,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _visible_images_query(db, current_user.id)
    total = query.count()
    items = query.order_by(ContainerImage.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "items": [ImageResponse.model_validate(row).model_dump(mode="json") for row in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def _load_image(db: Session, image_id: uuid.UUID, user) -> ContainerImage:
    image = db.query(ContainerImage).filter(ContainerImage.id == image_id).first()
    if image is None:
        raise HTTPException(404, {"code": "IMAGE_NOT_FOUND"})
    if image.visibility != "platform":
        try:
            ProjectAccessService().require(db, image.project_id, user.id, "project.read")
        except ProjectAccessError as error:
            _http_access(error)
    return image


@router.get("/{image_id}", response_model=ImageResponse)
def get_image(
    image_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    image = _load_image(db, image_id, current_user)
    return ImageResponse.model_validate(image)


@router.patch("/{image_id}", response_model=ImageResponse)
def update_image(
    image_id: uuid.UUID,
    data: ImageUpdateRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    image = _load_image(db, image_id, current_user)
    try:
        ProjectAccessService().require(db, image.project_id or _any_project(db, current_user), current_user.id, "resource.update")
    except ProjectAccessError as error:
        _http_access(error)
    if data.digest is not None and data.digest != image.digest:
        raise HTTPException(422, {"code": "IMAGE_DIGEST_IMMUTABLE", "message": "a new digest is a new catalog entry"})
    if data.scan_status is not None:
        image.scan_status = data.scan_status
    if data.scan_report_ref is not None:
        image.scan_report_ref = data.scan_report_ref
    if data.description is not None:
        image.description = data.description
    db.commit()
    with _audit(db, request, current_user, image.project_id or _any_project(db, current_user), "resource.update", "image.update", image.id, {"scan_status": image.scan_status}, set()):
        pass
    return ImageResponse.model_validate(image)


@router.post("/builds", response_model=ImageBuildResponse, status_code=201)
def create_build(
    data: ImageBuildRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not settings.image_build_approved:
        raise HTTPException(
            501,
            {
                "code": "IMAGE_BUILD_NOT_APPROVED",
                "message": "online image builds are not approved; register pre-built digests instead",
            },
        )
    try:
        ProjectAccessService().require(db, data.project_id, current_user.id, "resource.create")
    except ProjectAccessError as error:
        _http_access(error)
    builder_image = data.builder_image or settings.image_build_builder_image
    try:
        build = record_build(
            db,
            project_id=data.project_id,
            registered_by=current_user.id,
            builder_image=builder_image,
            destination=data.destination,
            source_artifact_id=data.source_artifact_id,
        )
    except ImageBuildError as error:
        raise HTTPException(error.status, {"code": error.code, "message": error.message})
    except (KeyError, ValueError) as error:
        raise HTTPException(422, {"code": "IMAGE_DESTINATION_INVALID", "message": str(error)})
    return ImageBuildResponse.model_validate(build)
