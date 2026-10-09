"""Week 15 developer-resource API schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SessionStatus = Literal["starting", "running", "stopping", "stopped", "failed", "terminated"]
ScanStatus = Literal["unknown", "pending", "passed", "failed"]


class NotebookStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: UUID
    namespace: str | None = Field(default=None, max_length=63)
    image_ref: str = Field(min_length=1, max_length=512)
    resources: dict = Field(default_factory=dict)
    gpu_class: str | None = Field(default=None, max_length=64)
    gpu_count: int = Field(default=1, ge=1, le=8)
    idle_timeout_seconds: int = Field(default=3600, ge=60, le=86400)


class NotebookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    user_id: UUID
    cluster_id: UUID
    namespace: str
    job_name: str
    image_ref: str
    resource_json: dict
    status: SessionStatus
    idle_timeout_seconds: int
    error_code: str | None = None
    last_activity_at: datetime | None = None
    started_at: datetime | None = None
    terminated_at: datetime | None = None
    created_at: datetime | None = None
    replayed: bool = False


class ImageRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry: str = Field(min_length=1, max_length=255)
    repository: str = Field(min_length=1, max_length=255)
    digest: str = Field(min_length=71, max_length=71)
    visibility: Literal["project", "platform"] = "project"
    scan_status: ScanStatus = "unknown"
    description: str = Field(default="", max_length=255)


class ImageUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    digest: str | None = None
    scan_status: ScanStatus | None = None
    scan_report_ref: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=255)


class ImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None = None
    registry: str
    repository: str
    digest: str
    visibility: Literal["project", "platform"]
    scan_status: ScanStatus
    scan_report_ref: str | None = None
    source: Literal["manual_registry", "build"]
    description: str | None = None
    created_at: datetime | None = None


class ImageBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    source_artifact_id: UUID | None = None
    builder_image: str | None = Field(default=None, max_length=512)
    destination: str = Field(min_length=1, max_length=512)
    registry_credential_ref: str = Field(min_length=1, max_length=255)


class ImageBuildResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    builder_image: str
    status: str
    output_image_id: UUID | None = None
    created_at: datetime | None = None
