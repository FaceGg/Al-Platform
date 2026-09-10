from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AssignmentCreate(BaseModel):
    annotator_ids: list[UUID] = Field(min_length=1)
    sample_scope: dict[str, Any]
    due_at: datetime | None = None


class LabelSaveRequest(BaseModel):
    values: dict[str, Any]
    base_revision: int = Field(ge=0)


class AssignmentReturnRequest(BaseModel):
    task_revision: int = Field(ge=0)
    scope_hash: str


class AssignmentEditRequest(BaseModel):
    task_revision: int = Field(ge=0)
