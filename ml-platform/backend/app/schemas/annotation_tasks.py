import uuid
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class TaskAction(str, Enum):
    publish = "publish"
    execute = "execute"
    pause = "pause"
    cancel = "cancel"
    complete = "complete"


class AnnotationPreviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_revision: int = Field(ge=0)
    config_hash: str = Field(min_length=1, max_length=128)


class AnnotationTaskTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_revision: int = Field(ge=0)
    action: TaskAction
    preview_id: uuid.UUID | None = None
