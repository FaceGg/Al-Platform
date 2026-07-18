"""Strict contracts for project membership and audit queries."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


MemberRole = Literal["editor", "operator", "viewer"]


class MemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    role: MemberRole


class MemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: MemberRole


class MemberResponse(BaseModel):
    user_id: UUID
    username: str
    role: Literal["owner", "editor", "operator", "viewer"]
    created_at: datetime | None = None


class MemberList(BaseModel):
    items: list[MemberResponse]
    total: int


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID | None
    actor_id: UUID | None
    actor_username: str
    action: str
    resource_type: str
    resource_id: str | None
    result: Literal["success", "denied", "failed"]
    request_id: UUID
    source_ip: str | None
    changes: dict
    error_code: str | None
    created_at: datetime


class AuditEventList(BaseModel):
    items: list[AuditEventResponse]
    total: int
    offset: int
    limit: int
