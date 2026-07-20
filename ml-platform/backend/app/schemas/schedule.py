"""Typed API contracts for persisted pipeline schedules."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=10)
    backoff_seconds: float = Field(default=0, ge=0, le=3600)
    max_backoff_seconds: float = Field(default=3600, ge=0, le=86400)


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    workflow_id: UUID
    cron_expression: str = Field(min_length=1, max_length=128)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    max_concurrency: int = Field(default=1, ge=1, le=100)
    dependencies: list[UUID] = Field(default_factory=list, max_length=100)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)
    workflow_version: int | None = Field(default=None, ge=1)


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    cron_expression: str | None = Field(default=None, min_length=1, max_length=128)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=100)
    dependencies: list[UUID] | None = Field(default=None, max_length=100)
    retry_policy: RetryPolicy | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)
    workflow_version: int | None = Field(default=None, ge=1)


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    workflow_id: UUID
    name: str
    cron_expression: str
    timezone: str
    enabled: bool
    paused_at: datetime | None
    max_concurrency: int
    dependencies: list[str]
    retry_policy: dict
    timeout_seconds: int | None
    workflow_version: int | None
    next_run_at: datetime
    last_run_at: datetime | None
    last_error_code: str | None
    created_by: UUID
    created_at: datetime | None
    updated_at: datetime | None


class ScheduleList(BaseModel):
    items: list[ScheduleResponse]
    total: int


class BackfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurrences: list[datetime] = Field(min_length=1, max_length=100)


class ScheduleRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    schedule_id: UUID
    workflow_run_id: UUID | None
    scheduled_for: datetime
    claimed_at: datetime | None
    next_attempt_at: datetime | None
    finished_at: datetime | None
    status: str
    attempt: int
    skip_reason: str | None
    error_code: str | None
    error_message: str | None


class ScheduleRunList(BaseModel):
    items: list[ScheduleRunResponse]
    total: int
    offset: int
    limit: int
