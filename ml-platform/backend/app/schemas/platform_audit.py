"""Strict contracts shared by platform security audit producers and readers."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# 平台角色（技术方案 §7.1/D10）：quality=质量工程师；User.role 为 String(16)
# 无 DB 约束，扩枚举零迁移；注册默认角色不变（engineer）
PLATFORM_ROLES = frozenset({"admin", "engineer", "operator", "viewer", "quality"})


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
    created_at: datetime


class PlatformAuditEventList(BaseModel):
    items: list[PlatformAuditEventResponse]
    total: int
    offset: int
    limit: int
