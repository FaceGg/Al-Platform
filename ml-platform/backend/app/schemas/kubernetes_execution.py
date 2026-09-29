"""Strict contracts for the Week 14 Kubernetes job API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["queued", "submitted", "running", "succeeded", "failed", "cancelled", "timed_out", "orphaned"]


class JobSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: UUID
    namespace: str | None = Field(default=None, max_length=63)
    image_ref: str = Field(min_length=1, max_length=512)
    command: list[str] = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    resources: dict[str, float] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=600, ge=1)
    task_id: UUID | None = None
    input_bindings: list = Field(default_factory=list)
    output_bindings: list = Field(default_factory=list)


class JobRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    cluster_id: UUID
    namespace: str
    job_name: str
    image_ref: str
    command_json: list
    args_json: list
    resource_json: dict
    status: JobStatus
    status_detail: str | None = None
    error_code: str | None = None
    revision: int
    timeout_seconds: int
    exit_code: int | None = None
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    replayed: bool = False
