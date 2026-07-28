from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from sqlalchemy.orm import Session

from app.database import get_db

from app.models.user import User

import uuid
from app.api.auth import get_current_user
from app.schemas.platform_audit import PLATFORM_ROLES
from app.services.platform_audit import (
    PlatformAuditIntent,
    record_failed_platform_event,
    record_platform_event,
)



router = APIRouter(prefix="/api", tags=["users"])





def get_current_admin(

    current_user: User = Depends(get_current_user),

) -> User:

    if current_user.role != "admin":

        raise HTTPException(status_code=403, detail="Admin privileges required")

    return current_user





@router.get("/admin/users")

def list_users(

    db: Session = Depends(get_db),

    admin: User = Depends(get_current_admin),

):

    users = db.query(User).all()

    return [

        {

            "id": str(u.id),

            "username": u.username,

            "role": u.role,

            "created_at": u.created_at.isoformat() if u.created_at else None,

        }

        for u in users

    ]





@router.get("/admin/users/{user_id}")

def get_user_detail(

    user_id: str,

    db: Session = Depends(get_db),

    admin: User = Depends(get_current_admin),

):

    user = db.query(User).filter(User.id == UUID(user_id)).first()

    if not user:

        raise HTTPException(404, "User not found")

    return {

        "id": str(user.id),

        "username": user.username,

        "role": user.role,

        "created_at": user.created_at.isoformat() if user.created_at else None,

    }





@router.put("/admin/users/{user_id}/role")

def update_user_role(

    user_id: str,

    role: str,

    request: Request,

    db: Session = Depends(get_db),

    admin: User = Depends(get_current_admin),

):

    if role not in PLATFORM_ROLES:
        record_failed_platform_event(
            db,
            actor=admin,
            request=request,
            intent=PlatformAuditIntent(
                action="platform.user.role_change",
                resource_type="user",
                resource_id=user_id,
                changes={"role": role},
            ),
            error_code="INVALID_PLATFORM_ROLE",
        )
        raise HTTPException(422, {"code": "INVALID_PLATFORM_ROLE"})

    user = db.query(User).filter(User.id == UUID(user_id)).first()

    if not user:
        record_failed_platform_event(
            db,
            actor=admin,
            request=request,
            intent=PlatformAuditIntent(
                action="platform.user.role_change",
                resource_type="user",
                resource_id=user_id,
            ),
            error_code="USER_NOT_FOUND",
        )
        raise HTTPException(404, "User not found")

    if user.id == admin.id and role != "admin":
        record_failed_platform_event(
            db,
            actor=admin,
            request=request,
            intent=PlatformAuditIntent(
                action="platform.user.role_change",
                resource_type="user",
                resource_id=str(user.id),
                changes={"previous_role": user.role, "role": role},
            ),
            error_code="SELF_ROLE_CHANGE_FORBIDDEN",
        )
        raise HTTPException(400, {"code": "SELF_ROLE_CHANGE_FORBIDDEN"})

    previous_role = user.role

    user.role = role

    record_platform_event(
        db,
        actor=admin,
        request=request,
        intent=PlatformAuditIntent(
            action="platform.user.role_change",
            resource_type="user",
            resource_id=str(user.id),
            changes={"previous_role": previous_role, "role": role},
        ),
        result="success",
    )

    db.commit()

    return {"message": "Role updated", "user_id": str(user.id), "role": user.role}


@router.delete("/admin/users/{user_id}")
def delete_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == UUID(user_id)).first()
    if not user:
        record_failed_platform_event(
            db,
            actor=admin,
            request=request,
            intent=PlatformAuditIntent(
                action="platform.user.delete",
                resource_type="user",
                resource_id=user_id,
            ),
            error_code="USER_NOT_FOUND",
        )
        raise HTTPException(404, "User not found")
    if user.id == admin.id:
        record_failed_platform_event(
            db,
            actor=admin,
            request=request,
            intent=PlatformAuditIntent(
                action="platform.user.delete",
                resource_type="user",
                resource_id=str(user.id),
                changes={"username": user.username},
            ),
            error_code="SELF_DELETE_FORBIDDEN",
        )
        raise HTTPException(400, {"code": "SELF_DELETE_FORBIDDEN"})
    db.delete(user)
    record_platform_event(
        db,
        actor=admin,
        request=request,
        intent=PlatformAuditIntent(
            action="platform.user.delete",
            resource_type="user",
            resource_id=str(user.id),
            changes={"username": user.username},
        ),
        result="success",
    )
    db.commit()
    return {"message": "?????", "user_id": str(user.id)}
