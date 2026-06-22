from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.api.auth import get_current_user

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
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == UUID(user_id)).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.role = role
    db.commit()
    return {"message": "Role updated", "user_id": str(user.id), "role": user.role}
