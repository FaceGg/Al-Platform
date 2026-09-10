"""Portal comment endpoints with portal-session identity only."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.services.platform_client import PlatformClient, PlatformClientError
from app.services.session import PortalPrincipal, require_portal_session

router = APIRouter(prefix="/portal", tags=["portal-comments"])

class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    content: str = Field(min_length=1, max_length=4000)
    sample_id: str | None = Field(default=None, max_length=256)
    related_revision: int | None = Field(default=None, ge=0)

def _failure(error: PlatformClientError) -> HTTPException:
    return HTTPException(status_code=502, detail={"code": "PORTAL_PLATFORM_UNAVAILABLE", "message": str(error)})

@router.get("/comments")
async def list_comments(task_id: UUID | None = None, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200), principal: PortalPrincipal = Depends(require_portal_session)):
    try:
        return await PlatformClient().internal_request("GET", "/api/internal/portal/comments", subject_id=str(principal.subject_id), scope="comment:read", params={"task_id": str(task_id) if task_id else None, "cursor": cursor, "limit": limit})
    except PlatformClientError as error:
        raise _failure(error) from error

@router.post("/comments", status_code=201)
async def create_comment(data: CommentCreate, principal: PortalPrincipal = Depends(require_portal_session)):
    try:
        return await PlatformClient().internal_request("POST", "/api/internal/portal/comments", subject_id=str(principal.subject_id), scope="comment:write", json=data.model_dump(mode="json"))
    except PlatformClientError as error:
        raise _failure(error) from error
