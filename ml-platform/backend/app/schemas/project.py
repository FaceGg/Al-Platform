from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime

class ProjectCreate(BaseModel):
    name: str
    description: str = ""

class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    owner_id: UUID
    creator_username: str | None = None
    created_at: datetime
    updated_at: datetime
    project_role: str | None = None

class ProjectList(BaseModel):
    items: list[ProjectResponse]
    total: int
