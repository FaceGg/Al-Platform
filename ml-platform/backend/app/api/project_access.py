"""Owner-managed project memberships and audit history."""

from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.database import get_db
from app.models.access import AuditEvent, ProjectMember
from app.models.user import User
from app.schemas.access import (
    AuditEventList,
    MemberCreate,
    MemberList,
    MemberResponse,
    MemberUpdate,
)
from app.services.audit import AuditIntent, AuditService
from app.services.project_access import ProjectAccessError, ProjectAccessService


router = APIRouter(tags=["project-access"])


def _http_access(error: ProjectAccessError):
    status = 404 if error.hidden else 403
    raise HTTPException(status, {"code": error.code, "message": str(error)})


def _require(db, project_id, user_id, permission):
    try:
        return ProjectAccessService().require(db, project_id, user_id, permission)
    except ProjectAccessError as error:
        _http_access(error)


def _audit_service(db) -> AuditService:
    return AuditService(sessionmaker(bind=db.get_bind()))


@router.get("/api/projects/{project_id}/members", response_model=MemberList)
def list_members(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = _require(db, project_id, current_user.id, "member.manage")
    owner = access.project.owner
    items = [{
        "user_id": owner.id,
        "username": owner.username,
        "role": "owner",
        "created_at": access.project.created_at,
    }]
    members = (
        db.query(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .filter(ProjectMember.project_id == access.project.id)
        .order_by(ProjectMember.created_at, ProjectMember.id)
        .all()
    )
    items.extend({
        "user_id": user.id,
        "username": user.username,
        "role": member.role,
        "created_at": member.created_at,
    } for member, user in members)
    return {"items": items, "total": len(items)}


@router.post(
    "/api/projects/{project_id}/members",
    response_model=MemberResponse,
    status_code=201,
)
def add_member(
    project_id: uuid.UUID,
    data: MemberCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = ProjectAccessService().resolve(db, project_id, current_user.id)
    if access is None:
        _http_access(ProjectAccessError("PROJECT_NOT_FOUND", hidden=True))
    target = db.query(User).filter(User.username == data.username).first()
    if target is None:
        raise HTTPException(404, {"code": "PROJECT_MEMBER_USER_NOT_FOUND"})
    if target.id == access.project.owner_id:
        raise HTTPException(409, {"code": "PROJECT_OWNER_MEMBERSHIP_IMMUTABLE"})
    if db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == target.id,
    ).first() is not None:
        raise HTTPException(409, {"code": "PROJECT_MEMBER_EXISTS"})
    member = ProjectMember(
        project_id=project_id,
        user_id=target.id,
        role=data.role,
        created_by=current_user.id,
    )
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="member.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="project.member.add",
            resource_type="project_member",
            resource_id=str(target.id),
            changes={"username": target.username, "role": data.role},
        ),
        allowed_changes={"username", "role"},
    ):
        db.add(member)
    db.refresh(member)
    return {
        "user_id": target.id,
        "username": target.username,
        "role": member.role,
        "created_at": member.created_at,
    }


@router.patch(
    "/api/projects/{project_id}/members/{user_id}",
    response_model=MemberResponse,
)
def update_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    data: MemberUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = ProjectAccessService().resolve(db, project_id, current_user.id)
    if access is None:
        _http_access(ProjectAccessError("PROJECT_NOT_FOUND", hidden=True))
    if user_id == access.project.owner_id:
        raise HTTPException(409, {"code": "PROJECT_OWNER_MEMBERSHIP_IMMUTABLE"})
    row = (
        db.query(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        .first()
    )
    if row is None:
        raise HTTPException(404, {"code": "PROJECT_MEMBER_NOT_FOUND"})
    member, target = row
    previous = member.role
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="member.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="project.member.role_change",
            resource_type="project_member",
            resource_id=str(user_id),
            changes={"previous_role": previous, "role": data.role},
        ),
        allowed_changes={"previous_role", "role"},
    ):
        member.role = data.role
    return {
        "user_id": target.id,
        "username": target.username,
        "role": member.role,
        "created_at": member.created_at,
    }


@router.delete(
    "/api/projects/{project_id}/members/{user_id}",
    status_code=204,
)
def remove_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = ProjectAccessService().resolve(db, project_id, current_user.id)
    if access is None:
        _http_access(ProjectAccessError("PROJECT_NOT_FOUND", hidden=True))
    if user_id == access.project.owner_id:
        raise HTTPException(409, {"code": "PROJECT_OWNER_MEMBERSHIP_IMMUTABLE"})
    member = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user_id,
    ).first()
    if member is None:
        raise HTTPException(404, {"code": "PROJECT_MEMBER_NOT_FOUND"})
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="member.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="project.member.remove",
            resource_type="project_member",
            resource_id=str(user_id),
            changes={"role": member.role},
        ),
        allowed_changes={"role"},
    ):
        db.delete(member)
    return Response(status_code=204)


@router.get(
    "/api/projects/{project_id}/audit-events",
    response_model=AuditEventList,
)
def list_audit_events(
    project_id: uuid.UUID,
    action: str | None = None,
    resource_type: str | None = None,
    actor_id: uuid.UUID | None = None,
    result: str | None = Query(default=None, pattern="^(success|denied|failed)$"),
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require(db, project_id, current_user.id, "audit.read")
    query = db.query(AuditEvent).filter(AuditEvent.project_id == project_id)
    if action is not None:
        query = query.filter(AuditEvent.action == action)
    if resource_type is not None:
        query = query.filter(AuditEvent.resource_type == resource_type)
    if actor_id is not None:
        query = query.filter(AuditEvent.actor_id == actor_id)
    if result is not None:
        query = query.filter(AuditEvent.result == result)
    if from_time is not None:
        query = query.filter(AuditEvent.created_at >= from_time)
    if to_time is not None:
        query = query.filter(AuditEvent.created_at <= to_time)
    total = query.count()
    items = query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).offset(offset).limit(limit).all()
    return {"items": items, "total": total, "offset": offset, "limit": limit}
