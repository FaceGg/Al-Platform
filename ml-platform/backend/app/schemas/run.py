from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class RunResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    class Config: from_attributes = True

class NodeRunResponse(BaseModel):
    id: UUID
    node_id: UUID | None
    status: str
    output_meta: dict | None = None
    preview_data: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    class Config: from_attributes = True
