"""Pydantic contracts for model export and offline runtime results."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version_id: UUID
    annotation_task_id: UUID | None = None
    annotation_task_revision: int | None = Field(default=None, ge=0)
    include_runtime: bool = True


class ExportValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    files: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ModelExportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    operation_id: UUID | None = None
    status: str
    manifest_sha256: str | None = None


class OfflineInferenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    row_count: int
    output_path: str
