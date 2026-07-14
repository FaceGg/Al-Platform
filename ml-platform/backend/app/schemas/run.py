from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class NodeRunResponse(BaseModel):
    id: UUID
    node_id: UUID | None
    status: str
    attempt: int = 1
    result: dict | None = None
    output_meta: dict | None = None
    preview_data: str | None = None
    error_message: str | None = None
    error_code: str | None = None
    error_details: dict | None = None
    duration_ms: int | None = None
    logs: list[dict] = []
    started_at: datetime | None = None
    finished_at: datetime | None = None
    class Config: from_attributes = True

class RunResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    error_code: str | None = None
    error_details: dict | None = None
    workflow_version: int | None = None
    logs: list[dict] = []
    cancel_requested_at: datetime | None = None
    cancelled_at: datetime | None = None
    node_runs: list[NodeRunResponse] = []
    class Config: from_attributes = True
