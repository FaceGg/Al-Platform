from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime

class NodePosition(BaseModel):
    x: float
    y: float

class NodeCreate(BaseModel):
    id: str  # client-generated
    operator_id: str
    label: str = ""
    position: NodePosition
    params: dict = {}

class EdgeCreate(BaseModel):
    id: str
    source: str
    source_port: str
    target: str
    target_port: str

class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    nodes: list[NodeCreate] = []
    edges: list[EdgeCreate] = []

class WorkflowSave(BaseModel):
    name: str | None = None
    description: str | None = None
    nodes: list[NodeCreate] = []
    edges: list[EdgeCreate] = []

class NodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    operator_id: str
    label: str
    position_x: float
    position_y: float
    params: dict

class EdgeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_node_id: UUID
    source_port: str
    target_node_id: UUID
    target_port: str

class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    # 平台通用模板不归属项目，project_id 为空
    project_id: UUID | None = None
    name: str
    description: str
    type: str
    nodes: list[NodeResponse] = []
    edges: list[EdgeResponse] = []
    created_at: datetime
    updated_at: datetime
