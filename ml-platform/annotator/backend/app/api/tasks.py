"""Portal task APIs backed by service-authenticated platform endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.services.platform_client import PlatformClient, PlatformClientError
from app.services.session import PortalPrincipal, require_annotator_session

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
    return HTTPException(status_code=error.status_code, detail=error.detail)

@router.get("/tasks")
async def list_tasks(
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None, max_length=32),
    assignment_state: str | None = Query(default=None, max_length=32),
    sort: str = Query(default="created_at", pattern="^(created_at|due_at|status|assignment_state)$"),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    principal: PortalPrincipal = Depends(require_annotator_session),
):
    try:
        return await PlatformClient().internal_request(
            "GET",
            "/api/internal/portal/tasks",
            subject_id=str(principal.subject_id),
            scope="assignment:read",
            params={key: value for key, value in {
                "cursor": cursor,
                "limit": limit,
                "search": search,
                "status": status,
                "assignment_state": assignment_state,
                "sort": sort,
                "direction": direction,
            }.items() if value is not None},
        )
    except PlatformClientError as error:
        raise _failure(error) from error

@router.get("/tasks/{task_id}")
async def get_task(task_id: UUID, assignment_id: UUID | None = None, principal: PortalPrincipal = Depends(require_annotator_session)):
    try:
        return await PlatformClient().internal_request("GET", f"/api/internal/portal/tasks/{task_id}", subject_id=str(principal.subject_id), scope="assignment:read", params={"assignment_id": str(assignment_id)} if assignment_id else {})
    except PlatformClientError as error:
        raise _failure(error) from error

@router.get("/tasks/{task_id}/samples")
async def list_samples(task_id: UUID, assignment_id: UUID | None = None, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), sample_search: str | None = Query(default=None, min_length=1, max_length=256), label_status: str | None = Query(default=None, pattern="^(complete|incomplete)$"), comment_status: str | None = Query(default=None, pattern="^(open|resolved|none)$"), modified_after: datetime | None = Query(default=None), authorized_field: str | None = Query(default=None, min_length=1, max_length=128), authorized_value: str | None = Query(default=None, max_length=256), principal: PortalPrincipal = Depends(require_annotator_session)):
    try:
        return await PlatformClient().internal_request("GET", f"/api/internal/portal/tasks/{task_id}/samples", subject_id=str(principal.subject_id), scope="assignment:read", params={key: value for key, value in {"cursor": cursor, "limit": limit, "offset": offset if offset else None, "sample_search": sample_search, "label_status": label_status, "comment_status": comment_status, "modified_after": modified_after.isoformat() if modified_after else None, "authorized_field": authorized_field, "authorized_value": authorized_value, **({"assignment_id": str(assignment_id)} if assignment_id else {})}.items() if value is not None})
    except PlatformClientError as error:
        raise _failure(error) from error

@router.put("/tasks/{task_id}/samples/{sample_id}/labels")
async def save_labels(task_id: UUID, sample_id: str, data: LabelWrite, assignment_id: UUID | None = None, principal: PortalPrincipal = Depends(require_annotator_session)):
    try:
        return await PlatformClient().internal_request("PUT", f"/api/internal/portal/tasks/{task_id}/samples/{sample_id}/labels", subject_id=str(principal.subject_id), scope="assignment:write", json=data.model_dump(), params={"assignment_id": str(assignment_id)} if assignment_id else {})
    except PlatformClientError as error:
        raise _failure(error) from error

@router.post("/tasks/{task_id}/bulk-labels")
async def bulk_labels(task_id: UUID, data: BulkLabelWrite, assignment_id: UUID | None = None, principal: PortalPrincipal = Depends(require_annotator_session)):
    try:
        return await PlatformClient().internal_request("POST", f"/api/internal/portal/tasks/{task_id}/bulk-labels", subject_id=str(principal.subject_id), scope="assignment:write", json=data.model_dump(), params={"assignment_id": str(assignment_id)} if assignment_id else {})
    except PlatformClientError as error:
        raise _failure(error) from error

@router.post("/tasks/{task_id}/confirm")
async def confirm(task_id: UUID, data: ConfirmationRequest, assignment_id: UUID | None = None, principal: PortalPrincipal = Depends(require_annotator_session)):
    try:
        return await PlatformClient().internal_request("POST", f"/api/internal/portal/tasks/{task_id}/confirm", subject_id=str(principal.subject_id), scope="assignment:write", json=data.model_dump(), params={"assignment_id": str(assignment_id)} if assignment_id else {})
    except PlatformClientError as error:
        raise _failure(error) from error

@router.post("/tasks/{task_id}/edit-for-return")
async def edit_for_return(task_id: UUID, data: ConfirmationRequest, assignment_id: UUID | None = None, principal: PortalPrincipal = Depends(require_annotator_session)):
    try:
        return await PlatformClient().internal_request("POST", f"/api/internal/portal/tasks/{task_id}/edit-for-return", subject_id=str(principal.subject_id), scope="assignment:write", json=data.model_dump(), params={"assignment_id": str(assignment_id)} if assignment_id else {})
    except PlatformClientError as error:
        raise _failure(error) from error

@router.post("/tasks/{task_id}/return")
async def return_task(task_id: UUID, data: ConfirmationRequest, assignment_id: UUID | None = None, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), principal: PortalPrincipal = Depends(require_annotator_session)):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail={"code": "IDEMPOTENCY_KEY_REQUIRED"})
    try:
        return await PlatformClient().internal_request("POST", f"/api/internal/portal/tasks/{task_id}/return", subject_id=str(principal.subject_id), scope="assignment:return", json=data.model_dump(), headers={"Idempotency-Key": idempotency_key}, params={"assignment_id": str(assignment_id)} if assignment_id else {})
    except PlatformClientError as error:
        raise _failure(error) from error
