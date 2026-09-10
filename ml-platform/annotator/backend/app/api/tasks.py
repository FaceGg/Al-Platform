"""Portal task APIs backed by service-authenticated platform endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.services.platform_client import PlatformClient, PlatformClientError
from app.services.session import PortalPrincipal, require_portal_session

router = APIRouter(prefix="/portal", tags=["portal-tasks"])

class LabelWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any]
    base_revision: int = Field(ge=0)

class BulkLabelWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[dict[str, Any]] = Field(min_length=1)

class ConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_revision: int = Field(ge=0)
    scope_hash: str = Field(min_length=1, max_length=128)

def _failure(error: PlatformClientError) -> HTTPException:
    return HTTPException(status_code=502, detail={"code": "PORTAL_PLATFORM_UNAVAILABLE", "message": str(error)})

@router.get("/tasks")
async def list_tasks(principal: PortalPrincipal = Depends(require_portal_session)):
    try:
        return await PlatformClient().internal_request("GET", "/api/internal/portal/tasks", subject_id=str(principal.subject_id), scope="assignment:read")
    except PlatformClientError as error:
        raise _failure(error) from error

@router.get("/tasks/{task_id}")
async def get_task(task_id: UUID, principal: PortalPrincipal = Depends(require_portal_session)):
    try:
        return await PlatformClient().internal_request("GET", f"/api/internal/portal/tasks/{task_id}", subject_id=str(principal.subject_id), scope="assignment:read")
    except PlatformClientError as error:
        raise _failure(error) from error

@router.get("/tasks/{task_id}/samples")
async def list_samples(task_id: UUID, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200), principal: PortalPrincipal = Depends(require_portal_session)):
    try:
        return await PlatformClient().internal_request("GET", f"/api/internal/portal/tasks/{task_id}/samples", subject_id=str(principal.subject_id), scope="assignment:read", params={"cursor": cursor, "limit": limit})
    except PlatformClientError as error:
        raise _failure(error) from error

@router.put("/tasks/{task_id}/samples/{sample_id}/labels")
async def save_labels(task_id: UUID, sample_id: str, data: LabelWrite, principal: PortalPrincipal = Depends(require_portal_session)):
    try:
        return await PlatformClient().internal_request("PUT", f"/api/internal/portal/tasks/{task_id}/samples/{sample_id}/labels", subject_id=str(principal.subject_id), scope="assignment:write", json=data.model_dump())
    except PlatformClientError as error:
        raise _failure(error) from error

@router.post("/tasks/{task_id}/bulk-labels")
async def bulk_labels(task_id: UUID, data: BulkLabelWrite, principal: PortalPrincipal = Depends(require_portal_session)):
    try:
        return await PlatformClient().internal_request("POST", f"/api/internal/portal/tasks/{task_id}/bulk-labels", subject_id=str(principal.subject_id), scope="assignment:write", json=data.model_dump())
    except PlatformClientError as error:
        raise _failure(error) from error

@router.post("/tasks/{task_id}/confirm")
async def confirm(task_id: UUID, data: ConfirmationRequest, principal: PortalPrincipal = Depends(require_portal_session)):
    try:
        return await PlatformClient().internal_request("POST", f"/api/internal/portal/tasks/{task_id}/confirm", subject_id=str(principal.subject_id), scope="assignment:write", json=data.model_dump())
    except PlatformClientError as error:
        raise _failure(error) from error

@router.post("/tasks/{task_id}/edit-for-return")
async def edit_for_return(task_id: UUID, data: ConfirmationRequest, principal: PortalPrincipal = Depends(require_portal_session)):
    try:
        return await PlatformClient().internal_request("POST", f"/api/internal/portal/tasks/{task_id}/edit-for-return", subject_id=str(principal.subject_id), scope="assignment:write", json={"task_revision": data.task_revision})
    except PlatformClientError as error:
        raise _failure(error) from error

@router.post("/tasks/{task_id}/return")
async def return_task(task_id: UUID, data: ConfirmationRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), principal: PortalPrincipal = Depends(require_portal_session)):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail={"code": "IDEMPOTENCY_KEY_REQUIRED"})
    try:
        return await PlatformClient().internal_request("POST", f"/api/internal/portal/tasks/{task_id}/return", subject_id=str(principal.subject_id), scope="assignment:return", json=data.model_dump(), headers={"Idempotency-Key": idempotency_key})
    except PlatformClientError as error:
        raise _failure(error) from error
