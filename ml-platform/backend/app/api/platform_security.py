"""Admin-only platform security audit queries."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.users import get_current_admin
from app.database import get_db
from app.models.platform_audit import PlatformAuditEvent
from app.models.user import User
from app.schemas.platform_audit import PlatformAuditEventList


router = APIRouter(prefix="/api/admin", tags=["platform-security"])


@router.get("/security-audit", response_model=PlatformAuditEventList)
def list_platform_audit_events(
    action: str | None = None,
    resource_type: str | None = None,
    actor_id: UUID | None = None,
    result: Literal["success", "denied", "failed"] | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    query = db.query(PlatformAuditEvent)
    if action is not None:
        query = query.filter(PlatformAuditEvent.action == action)
    if resource_type is not None:
        query = query.filter(PlatformAuditEvent.resource_type == resource_type)
    if actor_id is not None:
        query = query.filter(PlatformAuditEvent.actor_id == actor_id)
    if result is not None:
        query = query.filter(PlatformAuditEvent.result == result)
    if from_time is not None:
        query = query.filter(PlatformAuditEvent.created_at >= from_time)
    if to_time is not None:
        query = query.filter(PlatformAuditEvent.created_at <= to_time)

    total = query.count()
    items = (
        query.order_by(PlatformAuditEvent.created_at.desc(), PlatformAuditEvent.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"items": items, "total": total, "offset": offset, "limit": limit}
