"""Platform announcements CRUD API.

Reads are open to any authenticated user (the portal notices panel);
create/update/delete are system-admin only, mirroring the user-management
gate. Order: pinned first, then newest.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.users import get_current_admin
from app.database import get_db
from app.models.announcement import Announcement
from app.models.user import User

router = APIRouter(prefix="/api/announcements", tags=["announcements"])

LIST_LIMIT = 50


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=4000)
    pinned: bool = False


class AnnouncementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, max_length=4000)
    pinned: bool | None = None


def _out(item: Announcement) -> dict:
    return {
        "id": str(item.id),
        "title": item.title,
        "content": item.content,
        "pinned": bool(item.pinned),
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _get_item(db: Session, announcement_id: uuid.UUID | str) -> Announcement:
    try:
        item_uuid = uuid.UUID(str(announcement_id))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="ANNOUNCEMENT_NOT_FOUND")
    item = db.query(Announcement).filter(Announcement.id == item_uuid).first()
    if item is None:
        raise HTTPException(status_code=404, detail="ANNOUNCEMENT_NOT_FOUND")
    return item


@router.get("")
def list_announcements(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    items = (
        db.query(Announcement)
        .order_by(Announcement.pinned.desc(), Announcement.created_at.desc())
        .limit(LIST_LIMIT)
        .all()
    )
    return [_out(item) for item in items]


@router.post("", status_code=201)
def create_announcement(
    payload: AnnouncementCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    item = Announcement(
        title=payload.title.strip(),
        content=payload.content.strip(),
        pinned=payload.pinned,
        created_by=admin.username,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _out(item)


@router.patch("/{announcement_id}")
def update_announcement(
    announcement_id: str,
    payload: AnnouncementUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    item = _get_item(db, announcement_id)
    if payload.title is not None:
        item.title = payload.title.strip()
    if payload.content is not None:
        item.content = payload.content.strip()
    if payload.pinned is not None:
        item.pinned = payload.pinned
    db.commit()
    db.refresh(item)
    return _out(item)


@router.delete("/{announcement_id}", status_code=204)
def delete_announcement(
    announcement_id: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    item = _get_item(db, announcement_id)
    db.delete(item)
    db.commit()
    return None
