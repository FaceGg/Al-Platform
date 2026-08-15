from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.database import Base, get_db

from app.models.user import User
from app.models.model_library import ModelLibrary

import uuid
from app.api.auth import get_current_user



router = APIRouter(prefix="/api", tags=["users"])


class BatchDeleteUsersRequest(BaseModel):
    user_ids: list[UUID] = Field(min_length=1)





def _user_foreign_key_columns():
    for table in Base.metadata.tables.values():
        if table.name == User.__tablename__:
            continue
        for column in table.columns:
            if any(
                foreign_key.column.table.name == User.__tablename__
                and foreign_key.column.name == "id"
                for foreign_key in column.foreign_keys
            ):
                yield table, column


def _delete_user_resources(db: Session, user_id: UUID, replacement_user_id: UUID) -> None:
    db.query(ModelLibrary).filter(ModelLibrary.owner_id == user_id).update(
        {ModelLibrary.owner_id: replacement_user_id}, synchronize_session=False
    )
    for table, column in _user_foreign_key_columns():
        if table.name == "project_members" and column.name == "user_id":
            db.execute(delete(table).where(column == user_id))
            continue
        replacement_user = (
            replacement_user_id
            if not column.nullable or column.name == "owner_id"
            else None
        )
        db.execute(
            update(table).where(column == user_id).values({column.name: replacement_user})
        )
    db.execute(delete(User).where(User.id == user_id))
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





@router.post("/admin/users/batch-delete")
def batch_delete_users(
    data: BatchDeleteUsersRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    requested_ids = list(dict.fromkeys(data.user_ids))
    users_by_id = {
        user.id: user
        for user in db.query(User).filter(User.id.in_(requested_ids)).all()
    }

    deleted_ids: list[str] = []
    not_found_ids: list[str] = []
    skipped_current_user = False
    for user_id in requested_ids:
        user = users_by_id.get(user_id)
        if user is None:
            not_found_ids.append(str(user_id))
            continue
        if user.id == admin.id:
            skipped_current_user = True
            continue
        _delete_user_resources(db, user.id, admin.id)
        deleted_ids.append(str(user_id))

    db.commit()
    return {
        "deleted_ids": deleted_ids,
        "not_found_ids": not_found_ids,
        "skipped_current_user": skipped_current_user,
    }


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


@router.delete("/admin/users/{user_id}")
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == UUID(user_id)).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id:
        raise HTTPException(400, "Cannot delete the current administrator")
    deleted_user_id = user.id
    _delete_user_resources(db, deleted_user_id, admin.id)
    db.commit()
    return {"message": "User deleted", "user_id": str(deleted_user_id)}
