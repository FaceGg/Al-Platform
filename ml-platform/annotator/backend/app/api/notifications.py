"""Recipient-owned in-app notices through the independent portal session."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.platform_client import PlatformClient, PlatformClientError
from app.services.session import PortalPrincipal, require_annotator_session

router = APIRouter(prefix="/portal/notifications", tags=["portal-notifications"])


@router.get("")
async def list_notifications(
    cursor: UUID | None = None,
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    principal: PortalPrincipal = Depends(require_annotator_session),
):
    params = {"limit": limit, "unread_only": unread_only}
    if cursor is not None:
        params["cursor"] = str(cursor)
    try:
        return await PlatformClient().internal_request(
            "GET", "/api/internal/portal/notifications",
            subject_id=str(principal.subject_id), scope="notification:read", params=params,
        )
    except PlatformClientError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: UUID,
    principal: PortalPrincipal = Depends(require_annotator_session),
):
    try:
        return await PlatformClient().internal_request(
            "POST", f"/api/internal/portal/notifications/{notification_id}/read",
            subject_id=str(principal.subject_id), scope="notification:write",
        )
    except PlatformClientError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
