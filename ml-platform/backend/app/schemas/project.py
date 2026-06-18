from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class ProjectCreate(BaseModel):
    name: str
    description: str = ""

class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: str
    owner_id: UUID
    created_at: datetime
    updated_at: datetime
    class Config: from_attributes = True

class ProjectList(BaseModel):
    items: list[ProjectResponse]
    total: int
