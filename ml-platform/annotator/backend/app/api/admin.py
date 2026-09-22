"""Admin portal review endpoints: owner-scoped task review through the platform."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.services.platform_client import PlatformClient, PlatformClientError
from app.services.session import PortalPrincipal, require_portal_session

router = APIRouter(prefix="/portal/admin", tags=["portal-admin"])

class AdminCommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=4000)
    parent_id: UUID | None = None

class AdminReturnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=2000)

def _failure(error: PlatformClientError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)

def _require_admin(principal: PortalPrincipal) -> PortalPrincipal:
    if principal.kind != "admin" or principal.user_id is None:
        raise HTTPException(status_code=403, detail={"code": "PORTAL_ADMIN_REQUIRED"})
    return principal

@router.get("/tasks")
async def list_admin_tasks(
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=128),
    principal: PortalPrincipal = Depends(require_portal_session),
):
    _require_admin(principal)
    try:
        return await PlatformClient().internal_request(
            "GET",
            "/api/internal/portal/admin/tasks",
            admin_user_id=str(principal.user_id),
            scope="admin_review:read",
            params={key: value for key, value in {
                "cursor": cursor,
                "limit": limit,
                "search": search,
            }.items() if value is not None},
        )
    except PlatformClientError as error:
        raise _failure(error) from error

@router.get("/tasks/{task_id}")
async def get_admin_task(task_id: UUID, principal: PortalPrincipal = Depends(require_portal_session)):
    _require_admin(principal)
    try:
        return await PlatformClient().internal_request(
            "GET",
            f"/api/internal/portal/admin/tasks/{task_id}",
            admin_user_id=str(principal.user_id),
            scope="admin_review:read",
        )
    except PlatformClientError as error:
        raise _failure(error) from error

@router.get("/tasks/{task_id}/samples")
async def list_admin_samples(
    task_id: UUID,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    sample_search: str | None = Query(default=None, min_length=1, max_length=256),
    principal: PortalPrincipal = Depends(require_portal_session),
):
    _require_admin(principal)
    try:
        return await PlatformClient().internal_request(
            "GET",
            f"/api/internal/portal/admin/tasks/{task_id}/samples",
            admin_user_id=str(principal.user_id),
            scope="admin_review:read",
            params={key: value for key, value in {
                "cursor": cursor,
                "limit": limit,
                "sample_search": sample_search,
            }.items() if value is not None},
        )
    except PlatformClientError as error:
        raise _failure(error) from error

@router.get("/tasks/{task_id}/comments")
async def list_admin_comments(
    task_id: UUID,
    sample_id: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=200, ge=1, le=500),
    principal: PortalPrincipal = Depends(require_portal_session),
):
    _require_admin(principal)
    try:
        return await PlatformClient().internal_request(
            "GET",
            f"/api/internal/portal/admin/tasks/{task_id}/comments",
            admin_user_id=str(principal.user_id),
            scope="admin_review:read",
            params={key: value for key, value in {
                "sample_id": sample_id,
                "limit": limit,
            }.items() if value is not None},
        )
    except PlatformClientError as error:
        raise _failure(error) from error

@router.post("/tasks/{task_id}/comments", status_code=201)
async def create_admin_comment(
    task_id: UUID,
    data: AdminCommentCreate,
    principal: PortalPrincipal = Depends(require_portal_session),
):
    _require_admin(principal)
    try:
        return await PlatformClient().internal_request(
            "POST",
            f"/api/internal/portal/admin/tasks/{task_id}/comments",
            admin_user_id=str(principal.user_id),
            scope="admin_review:write",
            json=data.model_dump(mode="json"),
        )
    except PlatformClientError as error:
        raise _failure(error) from error

@router.post("/tasks/{task_id}/accept")
async def accept_admin_task(task_id: UUID, principal: PortalPrincipal = Depends(require_portal_session)):
    _require_admin(principal)
    try:
        return await PlatformClient().internal_request(
            "POST",
            f"/api/internal/portal/admin/tasks/{task_id}/accept",
            admin_user_id=str(principal.user_id),
            scope="admin_review:write",
        )
    except PlatformClientError as error:
        raise _failure(error) from error

@router.post("/tasks/{task_id}/return")
async def return_admin_task(
    task_id: UUID,
    data: AdminReturnRequest,
    principal: PortalPrincipal = Depends(require_portal_session),
):
    _require_admin(principal)
    try:
        return await PlatformClient().internal_request(
            "POST",
            f"/api/internal/portal/admin/tasks/{task_id}/return",
            admin_user_id=str(principal.user_id),
            scope="admin_review:write",
            json=data.model_dump(mode="json"),
        )
    except PlatformClientError as error:
        raise _failure(error) from error
