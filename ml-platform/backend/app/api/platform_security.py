"""Admin-only platform security audit queries."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.users import get_current_admin
from app.database import get_db
from app.models.platform_audit import PlatformAuditEvent
from app.models.user import User
from app.schemas.platform_audit import PLATFORM_ROLES, PlatformAuditEventList
from app.services.platform_audit import PlatformAuditIntent, record_platform_event
from app.services.section_visibility import (
    ALWAYS_VISIBLE_VIEWS,
    SECTION_VISIBILITY_KEY,
    VIEW_IDS,
)


router = APIRouter(prefix="/api/admin", tags=["platform-security"])


class SectionVisibilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: dict[str, list[str]] = Field(default_factory=dict)


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


@router.get("/section-visibility")
def get_section_visibility(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """板块可见性配置（技术方案 §7.1）：nav.section_visibility 原样读取。"""
    from app.models.platform_option import get_option

    return {"config": get_option(db, SECTION_VISIBILITY_KEY, {}) or {}, "view_ids": list(VIEW_IDS)}


@router.put("/section-visibility")
def put_section_visibility(
    request: Request,
    data: SectionVisibilityUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """保存板块可见性（admin only）：按角色收敛，未配置角色保持全可见；
    portal 恒可见（保存时自动补回，配置面不展示该开关）；admin 不接受收敛。"""
    from app.models.platform_option import get_option, set_option

    config = dict(data.config)
    config.pop("admin", None)  # admin 永远全可见，不接受配置
    for role, allowed in config.items():
        if role not in PLATFORM_ROLES:
            raise HTTPException(422, {"code": "SECTION_VISIBILITY_ROLE_INVALID"})
        if not isinstance(allowed, list) or any(view not in VIEW_IDS for view in allowed):
            raise HTTPException(422, {"code": "SECTION_VISIBILITY_VIEW_INVALID"})
        # portal 恒可见：保存时自动补回
        for view in ALWAYS_VISIBLE_VIEWS:
            if view not in allowed:
                allowed.append(view)
    previous = get_option(db, SECTION_VISIBILITY_KEY, {}) or {}
    set_option(db, SECTION_VISIBILITY_KEY, config)
    record_platform_event(
        db,
        actor=admin,
        request=request,
        intent=PlatformAuditIntent(
            action="platform.section_visibility.update",
            resource_type="platform_option",
            resource_id=SECTION_VISIBILITY_KEY,
            changes={"roles": sorted(config.keys()), "previous_roles": sorted(previous.keys())},
        ),
        result="success",
    )
    db.commit()
    return {"config": config}
