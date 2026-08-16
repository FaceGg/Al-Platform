"""Strict contracts shared by platform security audit producers and readers."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


PLATFORM_ROLES = frozenset({"admin", "engineer", "operator", "viewer"})


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class PlatformAuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_id: UUID | None
    actor_username: str
    action: str
    resource_type: str
    resource_id: str | None
    result: str
    request_id: UUID
    source_ip: str | None
    changes: dict[str, object]
    error_code: str | None


class PlatformAuditEventList(BaseModel):
    items: list[PlatformAuditEventResponse]
    total: int
    offset: int
    limit: int
