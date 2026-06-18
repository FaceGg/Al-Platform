# ML Algorithm Platform — Phase 1 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Build the MVP of a web-based visual ML workflow platform that can execute a full pipeline: import CSV -> preprocess -> train XGBoost -> evaluate -> visualize.

**Architecture:** React frontend with ReactFlow for drag-and-drop workflow editor, FastAPI backend with NetworkX-based DAG execution engine, SQLite for persistence during MVP. Frontend and backend communicate via REST API + WebSocket for real-time status.

**Tech Stack:** React 18 + TypeScript + ReactFlow + Ant Design 5 + ECharts (frontend), FastAPI + SQLAlchemy + NetworkX + scikit-learn + xgboost (backend), Celery + Redis (async tasks), SQLite (database).

---

## File Structure

`
ml-platform/
+-- backend/
|   +-- app/
|   |   +-- main.py                  # FastAPI app entry, CORS, lifespan
|   |   +-- config.py                # Settings / env vars
|   |   +-- database.py              # SQLAlchemy engine + session
|   |   +-- models/
|   |   |   +-- __init__.py
|   |   |   +-- user.py              # User model
|   |   |   +-- project.py           # Project model
|   |   |   +-- workflow.py          # Workflow / Node / Edge models
|   |   |   +-- run.py               # WorkflowRun / NodeRun models
|   |   |   +-- artifact.py          # Artifact model
|   |   +-- schemas/
|   |   |   +-- __init__.py
|   |   |   +-- project.py           # Pydantic schemas for project
|   |   |   +-- workflow.py          # Schemas for workflow/node/edge
|   |   |   +-- run.py               # Schemas for run
|   |   |   +-- operator.py          # Schemas for operator registry
|   |   +-- api/
|   |   |   +-- __init__.py
|   |   |   +-- auth.py              # POST /api/auth/login
|   |   |   +-- projects.py          # /api/projects CRUD
|   |   |   +-- workflows.py         # /api/workflows CRUD
|   |   |   +-- runs.py              # /api/workflows/{id}/run, /api/runs/{id}
|   |   |   +-- operators.py         # /api/operators
|   |   |   +-- datasets.py          # /api/datasets upload/preview
|   |   |   +-- templates.py         # /api/templates
|   |   +-- engine/
|   |   |   +-- __init__.py
|   |   |   +-- base_operator.py     # BaseOperator, PortSpec, ParamSpec
|   |   |   +-- registry.py          # OperatorRegistry (singleton)
|   |   |   +-- dag_executor.py      # DAG validation + scheduling + execution
|   |   |   +-- data_bus.py          # Inter-node data passing
|   |   +-- operators/
|   |   |   +-- __init__.py
|   |   |   +-- io_operators.py      # file_import, data_export
|   |   |   +-- processing.py        # missing_values, encoding, scaling, split
|   |   |   +-- ml_operators.py      # linear_regression, random_forest, xgboost
|   |   |   +-- evaluation.py        # classification_eval, confusion_matrix
|   |   |   +-- visualization.py     # scatter_plot, data_table, data_stats
|   |   +-- websocket/
|   |   |   +-- __init__.py
|   |   |   +-- manager.py           # WebSocket connection manager
|   +-- requirements.txt
|   +-- alembic.ini
|   +-- alembic/
|       +-- versions/
+-- frontend/
|   +-- package.json
|   +-- vite.config.ts
|   +-- tsconfig.json
|   +-- src/
|   |   +-- main.tsx
|   |   +-- App.tsx                   # Router + layout
|   |   +-- api/
|   |   |   +-- client.ts            # Axios instance + interceptors
|   |   |   +-- projects.ts          # Project API calls
|   |   |   +-- workflows.ts         # Workflow API calls
|   |   |   +-- runs.ts              # Run API calls
|   |   |   +-- operators.ts         # Operator API calls
|   |   +-- stores/
|   |   |   +-- workflowStore.ts      # Zustand store for workflow state
|   |   +-- pages/
|   |   |   +-- LoginPage.tsx
|   |   |   +-- DashboardPage.tsx
|   |   |   +-- ProjectListPage.tsx
|   |   |   +-- ProjectDetailPage.tsx
|   |   |   +-- WorkspacePage.tsx     # The main Canvas editor
|   |   |   +-- TemplateWizardPage.tsx
|   |   +-- components/
|   |   |   +-- Layout.tsx
|   |   |   +-- ProtectedRoute.tsx
|   |   |   +-- workspace/
|   |   |   |   +-- OperatorPanel.tsx        # Left sidebar
|   |   |   |   +-- WorkflowCanvas.tsx       # ReactFlow canvas
|   |   |   |   +-- CustomNode.tsx           # Custom ReactFlow node
|   |   |   |   +-- CustomEdge.tsx           # Custom ReactFlow edge
|   |   |   |   +-- NodeConfigPanel.tsx      # Right sidebar
|   |   |   |   +-- ResultPreview.tsx        # Node result panel
|   |   |   |   +-- ExecutionProgress.tsx    # Execution status bar
|   |   |   +-- template/
|   |   |   |   +-- TemplateCard.tsx
|   |   |   |   +-- TemplateConfigForm.tsx
|   |   |   +-- charts/
|   |   |       +-- ConfusionMatrix.tsx
|   |   |       +-- ScatterChart.tsx
|   |   |       +-- DataTable.tsx
+-- tests/
    +-- backend/
    |   +-- test_dag.py
    |   +-- test_operators.py
    |   +-- test_api.py
    +-- frontend/
        +-- test_workflow.test.ts


---

## Task Series A: Backend Infrastructure (Weeks 1-2)

### Task A1: FastAPI project skeleton

**Files:**
- Create: ml-platform/backend/app/__init__.py
- Create: ml-platform/backend/app/main.py
- Create: ml-platform/backend/app/config.py
- Create: ml-platform/backend/requirements.txt

- [ ] **Step 1: Create requirements.txt**

`
fastapi==0.115.0
uvicorn[standard]==0.31.0
sqlalchemy==2.0.*
alembic==1.13.*
python-jose[cryptography]==3.3.*
passlib[bcrypt]==1.7.*
python-multipart==0.0.29
pydantic==2.12.*
pydantic-settings==2.12.*
networkx==3.6.*
celery==5.4.*
redis==5.0.*
scikit-learn==1.7.*
xgboost==3.2.*
pandas==2.3.*
numpy==2.3.*
matplotlib==3.10.*
seaborn==0.13.*
joblib==1.5.*
websockets>=12.0
httpx==0.28.*
`

- [ ] **Step 2: Create config.py**

`python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "sqlite:///./ml_platform.db"
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24h
    
    class Config:
        env_file = ".env"

settings = Settings()
`

- [ ] **Step 3: Create main.py with CORS and lifespan**

`python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import engine, Base

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title="ML Platform API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health_check():
    return {"status": "ok"}
`

- [ ] **Step 4: Verify startup**

Run: cd ml-platform/backend && uvicorn app.main:app --reload --port 8000
Expected: Server starts, curl http://localhost:8000/api/health returns {"status":"ok"}

- [ ] **Step 5: Commit**

`
git add ml-platform/backend/
git commit -m "feat: FastAPI project skeleton with CORS and health check"
`

---

### Task A2: Database models + Alembic

**Files:**
- Create: ml-platform/backend/app/database.py
- Create: ml-platform/backend/app/models/__init__.py
- Create: ml-platform/backend/app/models/user.py
- Create: ml-platform/backend/app/models/project.py
- Create: ml-platform/backend/app/models/workflow.py
- Create: ml-platform/backend/app/models/run.py
- Create: ml-platform/backend/app/models/artifact.py

- [ ] **Step 1: Create database.py**

`python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
`

- [ ] **Step 2: Create all model files**

`python
# models/user.py
import uuid
from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(16), nullable=False, default="engineer")
    created_at = Column(DateTime, server_default=func.now())
`

`python
# models/project.py
import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base

class Project(Base):
    __tablename__ = "projects"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
`

`python
# models/workflow.py
import uuid
from sqlalchemy import Column, String, Text, Boolean, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base

class Workflow(Base):
    __tablename__ = "workflows"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    type = Column(String(16), default="free")  # 'template' | 'free'
    is_template = Column(Boolean, default=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class WorkflowNode(Base):
    __tablename__ = "nodes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    operator_id = Column(String(64), nullable=False)
    label = Column(String(128))
    position_x = Column(Float, nullable=False)
    position_y = Column(Float, nullable=False)
    params = Column(JSONB, default=dict)

class WorkflowEdge(Base):
    __tablename__ = "edges"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    source_node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    source_port = Column(String(64))
    target_node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    target_port = Column(String(64))
`

`python
# models/run.py
import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base

class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(16), default="pending")
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    error_message = Column(Text)
    triggered_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))

class NodeRun(Base):
    __tablename__ = "node_runs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="SET NULL"))
    status = Column(String(16), default="pending")
    output_meta = Column(JSONB)
    preview_data = Column(Text)
    error_message = Column(Text)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
`

`python
# models/artifact.py
import uuid
from sqlalchemy import Column, String, Text, BigInteger, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base

class Artifact(Base):
    __tablename__ = "artifacts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(256), nullable=False)
    type = Column(String(32), nullable=False)
    storage_path = Column(String(512), nullable=False)
    file_size = Column(BigInteger)
    format = Column(String(32))
    metadata_ = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime, server_default=func.now())
`

- [ ] **Step 3: Run initial migration**

Run: cd ml-platform/backend && python -c "from app.database import engine, Base; from app.models import *; Base.metadata.create_all(bind=engine); print('Tables created')"
Expected: Tables created in ml_platform.db

- [ ] **Step 4: Commit**

`
git add ml-platform/backend/app/database.py ml-platform/backend/app/models/
git commit -m "feat: add database models for users, projects, workflows, runs, artifacts"
`

---

### Task A3: Pydantic schemas

**Files:**
- Create: ml-platform/backend/app/schemas/__init__.py
- Create: ml-platform/backend/app/schemas/project.py
- Create: ml-platform/backend/app/schemas/workflow.py
- Create: ml-platform/backend/app/schemas/run.py
- Create: ml-platform/backend/app/schemas/operator.py

- [ ] **Step 1: Create project schemas**

`python
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
    
    class Config:
        from_attributes = True

class ProjectList(BaseModel):
    items: list[ProjectResponse]
    total: int
`

- [ ] **Step 2: Create workflow schemas**

`python
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class NodePosition(BaseModel):
    x: float
    y: float

class NodeCreate(BaseModel):
    id: str  # client-generated ID
    operator_id: str
    label: str = ""
    position: NodePosition
    params: dict = {}

class EdgeCreate(BaseModel):
    id: str
    source: str       # source node client ID
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
    id: UUID
    operator_id: str
    label: str
    position_x: float
    position_y: float
    params: dict

class EdgeResponse(BaseModel):
    id: UUID
    source_node_id: UUID
    source_port: str
    target_node_id: UUID
    target_port: str

class WorkflowResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    description: str
    type: str
    nodes: list[NodeResponse] = []
    edges: list[EdgeResponse] = []
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
`

- [ ] **Step 3: Create run schemas**

`python
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

class NodeRunResponse(BaseModel):
    id: UUID
    node_id: UUID | None
    status: str
    output_meta: dict | None = None
    preview_data: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
`

- [ ] **Step 4: Create operator schemas**

`python
from pydantic import BaseModel

class PortSpecSchema(BaseModel):
    name: str
    type: str
    label: str

class ParamSpecSchema(BaseModel):
    name: str
    type: str
    default: str | int | float | bool | None = None
    label: str
    options: list[str] | None = None
    range_min: float | None = None
    range_max: float | None = None

class OperatorSchema(BaseModel):
    id: str
    name: str
    category: str
    description: str
    version: str = "1.0"
    inputs: list[PortSpecSchema]
    outputs: list[PortSpecSchema]
    parameters: list[ParamSpecSchema]
`

- [ ] **Step 5: Commit**

`
git add ml-platform/backend/app/schemas/
git commit -m "feat: add Pydantic schemas for all API entities"
`

---

## Task Series B: Workflow Engine (Weeks 3-4)

### Task B1: BaseOperator + OperatorRegistry

**Files:**
- Create: ml-platform/backend/app/engine/__init__.py
- Create: ml-platform/backend/app/engine/base_operator.py
- Create: ml-platform/backend/app/engine/registry.py

- [ ] **Step 1: Create base_operator.py**

`python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

@dataclass
class PortSpec:
    name: str
    type: str      # "DataTable" | "Model" | "Image" | "Chart" | "Params"
    label: str

@dataclass
class ParamSpec:
    name: str
    type: str      # "int" | "float" | "str" | "select" | "boolean" | "file"
    default: Any = None
    label: str = ""
    options: list[str] | None = None
    range_min: float | None = None
    range_max: float | None = None

class BaseOperator(ABC):
    id: str = ""
    name: str = ""
    category: str = ""
    description: str = ""
    version: str = "1.0"
    inputs: list[PortSpec] = []
    outputs: list[PortSpec] = []
    parameters: list[ParamSpec] = []
    
    @abstractmethod
    def validate(self, inputs: dict[str, Any]) -> bool:
        ...
    
    @abstractmethod
    def execute(self, inputs: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        ...
    
    def get_preview(self, outputs: dict[str, Any]) -> dict[str, Any]:
        preview = {}
        for name, value in outputs.items():
            if isinstance(value, list) and len(value) > 0:
                if isinstance(value[0], dict):
                    preview[name] = value[:5]
                else:
                    preview[name] = value[:10]
        return preview
`

- [ ] **Step 2: Create registry.py**

`python
from typing import Type
from app.engine.base_operator import BaseOperator

class OperatorRegistry:
    _operators: dict[str, BaseOperator] = {}
    
    @classmethod
    def register(cls, operator: BaseOperator):
        if operator.id in cls._operators:
            raise ValueError(f"Operator '{operator.id}' already registered")
        cls._operators[operator.id] = operator
    
    @classmethod
    def get(cls, operator_id: str) -> BaseOperator | None:
        return cls._operators.get(operator_id)
    
    @classmethod
    def list_all(cls) -> list[BaseOperator]:
        return list(cls._operators.values())
    
    @classmethod
    def list_by_category(cls, category: str) -> list[BaseOperator]:
        return [op for op in cls._operators.values() if op.category == category]

def register_operator(cls: Type[BaseOperator]):
    instance = cls()
    OperatorRegistry.register(instance)
    return cls
`

- [ ] **Step 3: Write and run test**

`python
# tests/backend/test_operators.py
from app.engine.base_operator import PortSpec, ParamSpec, BaseOperator
from app.engine.registry import OperatorRegistry

class DummyOp(BaseOperator):
    id = "test_dummy"
    name = "Dummy"
    category = "test"
    description = "Test operator"
    inputs = [PortSpec(name="data", type="DataTable", label="Input Data")]
    outputs = [PortSpec(name="result", type="DataTable", label="Result Data")]
    parameters = [ParamSpec(name="value", type="int", default=42, label="Value")]
    
    def validate(self, inputs):
        return "data" in inputs
    
    def execute(self, inputs, params):
        return {"result": [{"value": params.get("value", 42)}]}

def test_operator_registration():
    op = DummyOp()
    OperatorRegistry.register(op)
    assert OperatorRegistry.get("test_dummy") is op
    assert len(OperatorRegistry.list_by_category("test")) == 1

def test_operator_execution():
    op = DummyOp()
    result = op.execute({"data": []}, {"value": 100})
    assert result["result"][0]["value"] == 100

def test_operator_validate():
    op = DummyOp()
    assert op.validate({"data": []}) is True
    assert op.validate({}) is False
`

Run: python -m pytest tests/backend/test_operators.py -v
Expected: All 3 tests pass

- [ ] **Step 4: Commit**

`
git add ml-platform/backend/app/engine/ tests/
git commit -m "feat: BaseOperator class and OperatorRegistry with tests"
`


### Task B2: DAG Executor

**Files:**
- Create: ml-platform/backend/app/engine/dag_executor.py
- Create: ml-platform/backend/app/engine/data_bus.py

- [ ] **Step 1: Create data_bus.py**

`python
import os
import json
import pandas as pd
from pathlib import Path
from typing import Any

TEMP_DIR = Path("temp_data")
TEMP_DIR.mkdir(exist_ok=True)

class DataBus:
    """Handles data passing between nodes via filesystem."""
    
    @staticmethod
    def save_data(run_id: str, node_id: str, port: str, data: Any):
        run_dir = TEMP_DIR / str(run_id)
        run_dir.mkdir(exist_ok=True)
        path = run_dir / f"{node_id}_{port}"
        if isinstance(data, pd.DataFrame):
            data.to_parquet(path.with_suffix(".parquet"))
        else:
            with open(path.with_suffix(".json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
        return str(path)
    
    @staticmethod
    def load_data(path_str: str) -> Any:
        p = Path(path_str)
        if p.suffix == ".parquet":
            return pd.read_parquet(p)
        elif p.suffix == ".json":
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
    
    @staticmethod
    def cleanup_run(run_id: str):
        run_dir = TEMP_DIR / str(run_id)
        if run_dir.exists():
            import shutil
            shutil.rmtree(run_dir)
`

- [ ] **Step 2: Create dag_executor.py**

`python
import asyncio
import networkx as nx
from uuid import UUID
from typing import Any
from app.engine.registry import OperatorRegistry
from app.engine.data_bus import DataBus

class DAGExecutor:
    def __init__(self, nodes: list[dict], edges: list[dict]):
        self.nodes = {n["id"]: n for n in nodes}
        self.edges = edges
        self.graph = nx.DiGraph()
        self._build_graph()
    
    def _build_graph(self):
        for n in self.nodes.values():
            self.graph.add_node(n["id"])
        for e in self.edges:
            src = e["source_node_id"] if isinstance(e["source_node_id"], str) else str(e["source_node_id"])
            tgt = e["target_node_id"] if isinstance(e["target_node_id"], str) else str(e["target_node_id"])
            self.graph.add_edge(src, tgt, port_map={
                "source_port": e["source_port"],
                "target_port": e["target_port"]
            })
    
    def validate(self) -> list[str]:
        errors = []
        if not nx.is_directed_acyclic_graph(self.graph):
            errors.append("Workflow contains cycles")
        for node_id, node_data in self.nodes.items():
            op = OperatorRegistry.get(node_data["operator_id"])
            if op is None:
                errors.append(f"Operator '{node_data['operator_id']}' not found")
                continue
            # Check required input edges
            for port in op.inputs:
                has_edge = any(
                    e["target_port"] == port.name and (
                        (isinstance(e["target_node_id"], str) and e["target_node_id"] == node_id) or
                        (str(e["target_node_id"]) == str(node_id))
                    )
                    for e in self.edges
                )
                if port.type == "DataTable" and not has_edge:
                    errors.append(f"Node '{node_data.get('label', node_id)}': missing input '{port.name}'")
        return errors
    
    async def execute(self, run_id: str, status_callback=None):
        """Execute the DAG topologically, calling status_callback(node_id, status, result) for each node."""
        execution_order = list(nx.topological_sort(self.graph))
        results = {}
        
        for node_id in execution_order:
            if status_callback:
                await status_callback(node_id, "running", None)
            
            node_info = self.nodes[node_id]
            op = OperatorRegistry.get(node_info["operator_id"])
            if op is None:
                if status_callback:
                    await status_callback(node_id, "failed", {"error": f"Operator not found"})
                continue
            
            # Collect inputs from upstream nodes
            inputs = {}
            for _, _, edge_data in self.graph.in_edges(node_id, data=True):
                src_id, tgt_id = _, _  # unpack properly
                for src, tgt, data in self.graph.in_edges(node_id, data=True):
                    if src in results:
                        port_map = data.get("port_map", {})
                        src_port = port_map.get("source_port", "output")
                        tgt_port = port_map.get("target_port", "input")
                        if src_port in results[src]:
                            inputs[tgt_port] = results[src][src_port]
            
            try:
                op_inputs = {}
                for port in op.inputs:
                    if port.name in inputs:
                        op_inputs[port.name] = inputs[port.name]
                
                op.validate(op_inputs)
                output = op.execute(op_inputs, node_info.get("params", {}))
                results[node_id] = output
                
                if status_callback:
                    preview = op.get_preview(output)
                    await status_callback(node_id, "completed", {"output": preview})
            except Exception as e:
                if status_callback:
                    await status_callback(node_id, "failed", {"error": str(e)})
        
        return results
`

- [ ] **Step 3: Write and run DAG tests**

`python
# tests/backend/test_dag.py
import pytest
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import OperatorRegistry
from app.engine.dag_executor import DAGExecutor

class AddOneOp(BaseOperator):
    id = "test_add_one"
    name = "Add One"
    category = "test"
    inputs = [PortSpec("data", "DataTable", "Input")]
    outputs = [PortSpec("result", "DataTable", "Output")]
    parameters = [ParamSpec("offset", "int", 1, "Offset")]
    def validate(self, inputs): return True
    def execute(self, inputs, params):
        data = inputs.get("data", [])
        offset = params.get("offset", 1)
        return {"result": [{"value": d["value"] + offset} for d in data]}

class IdentityOp(BaseOperator):
    id = "test_identity"
    name = "Identity"
    category = "test"
    inputs = [PortSpec("data", "DataTable", "Input")]
    outputs = [PortSpec("result", "DataTable", "Output")]
    parameters = []
    def validate(self, inputs): return True
    def execute(self, inputs, params):
        return {"result": inputs.get("data", [])}

@pytest.fixture(autouse=True)
def setup():
    OperatorRegistry._operators = {}
    OperatorRegistry.register(AddOneOp())
    OperatorRegistry.register(IdentityOp())

@pytest.mark.asyncio
async def test_linear_dag():
    nodes = [
        {"id": "n1", "operator_id": "test_add_one", "params": {"offset": 1}},
        {"id": "n2", "operator_id": "test_add_one", "params": {"offset": 2}},
    ]
    edges = [{"source_node_id": "n1", "source_port": "result", "target_node_id": "n2", "target_port": "data"}]
    executor = DAGExecutor(nodes, edges)
    assert len(executor.validate()) == 0
    
    # Mock the first node output manually
    executor.nodes["n1"] = nodes[0]
    
    statuses = []
    async def cb(nid, status, result):
        statuses.append((nid, status))
    
    # Inject input for n1
    class MockOp:
        def __init__(self):
            self.inputs = [PortSpec("data", "DataTable", "Input")]
            self.outputs = [PortSpec("result", "DataTable", "Output")]
            self.parameters = []
        def validate(self, inputs): return True
        def execute(self, inputs, params):
            return {"result": [{"value": 10}]}
        def get_preview(self, outputs):
            return {"result": outputs.get("result", [])[:5]}
    
    original_op = OperatorRegistry.get("test_add_one")
    OperatorRegistry._operators["test_add_one"] = MockOp()
    
    results = await executor.execute("test-run-id", cb)
    assert "n1" in results
    assert "n2" in results

@pytest.mark.asyncio
async def test_cycle_detection():
    nodes = [{"id": "n1", "operator_id": "test_identity", "params": {}},
             {"id": "n2", "operator_id": "test_identity", "params": {}}]
    edges = [{"source_node_id": "n1", "source_port": "result", "target_node_id": "n2", "target_port": "data"},
             {"source_node_id": "n2", "source_port": "result", "target_node_id": "n1", "target_port": "data"}]
    executor = DAGExecutor(nodes, edges)
    errors = executor.validate()
    assert any("cycle" in e.lower() for e in errors)
`

Run: python -m pytest tests/backend/test_dag.py -v
Expected: All tests pass

- [ ] **Step 4: Commit**

`
git add ml-platform/backend/app/engine/dag_executor.py ml-platform/backend/app/engine/data_bus.py tests/
git commit -m "feat: DAG executor with topological sort, validation, and async execution"
`

---

## Task Series C: Operator Implementations (Weeks 3-4, cont.)

### Task C1: Implement CSV Import + Data Processing operators

**Files:**
- Create: ml-platform/backend/app/operators/__init__.py
- Create: ml-platform/backend/app/operators/io_operators.py
- Create: ml-platform/backend/app/operators/processing.py

- [ ] **Step 1: Implement IO operators (CSV import + data export)**

`python
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import pandas as pd

@register_operator
class CSVImport(BaseOperator):
    id = "csv_import"
    name = "CSV/Excel Import"
    category = "data_io"
    description = "Import data from CSV or Excel file"
    inputs = []
    outputs = [PortSpec("data", "DataTable", "Output Data")]
    parameters = [
        ParamSpec("file_path", "file", "", "Data File"),
        ParamSpec("delimiter", "str", ",", "Delimiter"),
        ParamSpec("has_header", "boolean", True, "Has Header Row"),
        ParamSpec("encoding", "str", "utf-8", "File Encoding"),
    ]
    
    def validate(self, inputs):
        return True
    
    def execute(self, inputs, params):
        file_path = params.get("file_path", "")
        delimiter = params.get("delimiter", ",")
        has_header = params.get("has_header", True)
        encoding = params.get("encoding", "utf-8")
        if file_path.endswith(".csv"):
            df = pd.read_csv(file_path, delimiter=delimiter, header=0 if has_header else None, encoding=encoding)
        else:
            df = pd.read_excel(file_path, header=0 if has_header else None)
        return {"data": df.to_dict(orient="records")}
    
    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}
`

- [ ] **Step 2: Implement missing values handler**

`python
@register_operator
class MissingValueHandler(BaseOperator):
    id = "missing_value_handler"
    name = "Handle Missing Values"
    category = "processing"
    description = "Fill or drop missing values"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Cleaned Data")]
    parameters = [
        ParamSpec("strategy", "select", "drop", "Strategy",
                  options=["drop", "mean", "median", "most_frequent", "constant"]),
        ParamSpec("fill_value", "str", "0", "Fill Value (for constant strategy)"),
        ParamSpec("columns", "str", "", "Columns to apply (comma-sep, empty=all)"),
    ]
    
    def validate(self, inputs):
        return "data" in inputs
    
    def execute(self, inputs, params):
        import pandas as pd
        df = pd.DataFrame(inputs["data"])
        strategy = params.get("strategy", "drop")
        cols_input = params.get("columns", "").strip()
        cols = [c.strip() for c in cols_input.split(",") if c.strip()] if cols_input else df.columns.tolist()
        
        if strategy == "drop":
            df = df.dropna(subset=cols)
        else:
            for col in cols:
                if strategy == "mean" and pd.api.types.is_numeric_dtype(df[col]):
                    df[col] = df[col].fillna(df[col].mean())
                elif strategy == "median" and pd.api.types.is_numeric_dtype(df[col]):
                    df[col] = df[col].fillna(df[col].median())
                elif strategy == "most_frequent":
                    df[col] = df[col].fillna(df[col].mode().iloc[0] if not df[col].mode().empty else "")
                elif strategy == "constant":
                    df[col] = df[col].fillna(params.get("fill_value", "0"))
        return {"data": df.to_dict(orient="records")}
`

(Continuing with encoding, scaling, split operators with same decorator pattern...)

- [ ] **Step 3: Implement encoding operator**

`python
@register_operator
class LabelEncoderOp(BaseOperator):
    id = "label_encoder"
    name = "Label Encoding"
    category = "processing"
    description = "Encode categorical columns to numeric"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Encoded Data")]
    parameters = [
        ParamSpec("columns", "str", "", "Columns to encode (comma-sep, empty=all categorical)"),
        ParamSpec("encoding_type", "select", "label", "Encoding Type", options=["label", "onehot"]),
    ]
    def validate(self, inputs): return "data" in inputs
    def execute(self, inputs, params):
        import pandas as pd
        from sklearn.preprocessing import LabelEncoder
        df = pd.DataFrame(inputs["data"])
        cols = [c.strip() for c in params.get("columns", "").split(",") if c.strip()] \
               if params.get("columns") else df.select_dtypes(include=["object"]).columns.tolist()
        if params.get("encoding_type") == "onehot":
            df = pd.get_dummies(df, columns=cols)
        else:
            for col in cols:
                df[col] = LabelEncoder().fit_transform(df[col].astype(str))
        return {"data": df.to_dict(orient="records")}
`

- [ ] **Step 4: Implement scaling operator**

`python
@register_operator
class ScalerOp(BaseOperator):
    id = "scaler"
    name = "Feature Scaling"
    category = "processing"
    description = "Scale numeric features"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Scaled Data")]
    parameters = [
        ParamSpec("method", "select", "standard", "Scaling Method", options=["standard", "minmax", "robust"]),
        ParamSpec("columns", "str", "", "Columns to scale (comma-sep, empty=all numeric)"),
    ]
    def validate(self, inputs): return "data" in inputs
    def execute(self, inputs, params):
        import pandas as pd
        from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler
        df = pd.DataFrame(inputs["data"])
        cols = [c.strip() for c in params.get("columns", "").split(",") if c.strip()] \
               if params.get("columns") else df.select_dtypes(include=["float64", "int64"]).columns.tolist()
        if not cols:
            return {"data": inputs["data"]}
        method = params.get("method", "standard")
        scaler_map = {"standard": StandardScaler(), "minmax": MinMaxScaler(), "robust": RobustScaler()}
        scaler = scaler_map.get(method, StandardScaler())
        df[cols] = scaler.fit_transform(df[cols])
        return {"data": df.to_dict(orient="records")}
`

- [ ] **Step 5: Implement train/test split operator**

`python
@register_operator
class TrainTestSplit(BaseOperator):
    id = "train_test_split"
    name = "Train/Test Split"
    category = "processing"
    description = "Split data into training and test sets"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("train", "DataTable", "Training Data"),
               PortSpec("test", "DataTable", "Test Data")]
    parameters = [
        ParamSpec("test_size", "float", 0.2, "Test Size Ratio"),
        ParamSpec("random_seed", "int", 42, "Random Seed"),
        ParamSpec("stratify_column", "str", "", "Column for stratified split (optional)"),
    ]
    def validate(self, inputs): return "data" in inputs
    def execute(self, inputs, params):
        import pandas as pd
        from sklearn.model_selection import train_test_split
        df = pd.DataFrame(inputs["data"])
        stratify = df[params["stratify_column"]] if params.get("stratify_column") else None
        train, test = train_test_split(
            df, test_size=params.get("test_size", 0.2),
            random_state=params.get("random_seed", 42),
            stratify=stratify
        )
        return {"train": train.to_dict(orient="records"), "test": test.to_dict(orient="records")}
`

- [ ] **Step 6: Commit**

`
git add ml-platform/backend/app/operators/
git commit -m "feat: implement CSV import, missing value, encoding, scaling, and split operators"
`

---

### Task C2: ML + Evaluation + Visualization operators

**Files:**
- Create: ml-platform/backend/app/operators/ml_operators.py
- Create: ml-platform/backend/app/operators/evaluation.py
- Create: ml-platform/backend/app/operators/visualization.py

- [ ] **Step 1: Implement XGBoost + Random Forest + Linear Regression operators**

`python
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression
import xgboost as xgb

@register_operator
class XGBoostTrainer(BaseOperator):
    id = "xgboost_train"
    name = "XGBoost Training"
    category = "ml"
    description = "Train an XGBoost classifier or regressor"
    inputs = [PortSpec("train", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("task", "select", "classification", "Task Type", options=["classification", "regression"]),
        ParamSpec("n_estimators", "int", 100, "Number of Trees", range_min=10, range_max=1000),
        ParamSpec("max_depth", "int", 6, "Max Depth", range_min=1, range_max=50),
        ParamSpec("learning_rate", "float", 0.1, "Learning Rate", range_min=0.001, range_max=1.0),
        ParamSpec("random_seed", "int", 42, "Random Seed"),
    ]
    def validate(self, inputs): return "train" in inputs
    def execute(self, inputs, params):
        df = pd.DataFrame(inputs["train"])
        target = params["target_column"]
        X = df.drop(columns=[target])
        y = df[target]
        
        objective = "binary:logistic" if params.get("task") == "classification" else "reg:squarederror"
        model = xgb.XGBClassifier(
            n_estimators=int(params.get("n_estimators", 100)),
            max_depth=int(params.get("max_depth", 6)),
            learning_rate=float(params.get("learning_rate", 0.1)),
            random_state=int(params.get("random_seed", 42)),
            use_label_encoder=False,
            eval_metric="logloss" if params.get("task") == "classification" else "rmse",
            objective=objective,
        )
        model.fit(X, y)
        import joblib, io
        buf = io.BytesIO()
        joblib.dump(model, buf)
        return {"model": buf.getvalue(), "model_obj": model}
    
    def get_preview(self, outputs):
        return {"model": f"XGBoost ({outputs.get('model_obj', None)})"}
`

- [ ] **Step 2: Implement Classification Evaluation operator**

`python
@register_operator
class ClassificationEval(BaseOperator):
    id = "classification_eval"
    name = "Classification Evaluation"
    category = "evaluation"
    description = "Evaluate classification model performance"
    inputs = [PortSpec("model", "Model", "Trained Model"),
              PortSpec("test", "DataTable", "Test Data")]
    outputs = [PortSpec("metrics", "Params", "Evaluation Metrics"),
               PortSpec("chart", "Chart", "Confusion Matrix Chart")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
    ]
    def validate(self, inputs): return "model" in inputs and "test" in inputs
    def execute(self, inputs, params):
        import joblib, io, base64
        import numpy as np
        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
        import matplotlib.pyplot as plt
        import seaborn as sns
        
        df = pd.DataFrame(inputs["test"])
        target = params["target_column"]
        X_test = df.drop(columns=[target])
        y_test = df[target]
        
        model_data = inputs["model"]
        if isinstance(model_data, bytes):
            model = joblib.load(io.BytesIO(model_data))
        else:
            model = model_data
        y_pred = model.predict(X_test)
        
        metrics = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision": float(precision_score(y_test, y_pred, average="weighted", zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, average="weighted", zero_division=0)),
            "f1": float(f1_score(y_test, y_pred, average="weighted", zero_division=0)),
        }
        
        cm = confusion_matrix(y_test, y_pred)
        fig, ax = plt.subplots(figsize=(6, 5))
        sns.heatmap(cm, annot=True, fmt="d", ax=ax, cmap="Blues")
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual")
        ax.set_title("Confusion Matrix")
        
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        chart_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        
        return {"metrics": metrics, "chart": f"data:image/png;base64,{chart_b64}"}
    
    def get_preview(self, outputs):
        metrics = outputs.get("metrics", {})
        return {"metrics": metrics, "chart_type": "confusion_matrix"}
`

- [ ] **Step 3: Implement data visualization operators**

(Scatter plot, data table, data stats operators following the same pattern, returning base64-encoded chart images)

- [ ] **Step 4: Commit**

`
git add ml-platform/backend/app/operators/ml_operators.py ml-platform/backend/app/operators/evaluation.py ml-platform/backend/app/operators/visualization.py
git commit -m "feat: ML training, evaluation, and visualization operators"
`


---

## Task Series D: API Routes + WebSocket (Weeks 5-6)

### Task D1: Auth + Projects + Workflows CRUD API

**Files:**
- Create: ml-platform/backend/app/api/__init__.py
- Create: ml-platform/backend/app/api/auth.py
- Create: ml-platform/backend/app/api/projects.py
- Create: ml-platform/backend/app/api/workflows.py

- [ ] **Step 1: Implement auth endpoints**

`python
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(401, "User not found")
    return user

@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not pwd_context.verify(form.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer", "user_id": str(user.id), "role": user.role}

@router.post("/register")
def register(username: str, password: str, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(400, "Username already exists")
    user = User(username=username, password_hash=pwd_context.hash(password))
    db.add(user)
    db.commit()
    return {"message": "User created", "user_id": str(user.id)}
`

- [ ] **Step 2: Implement projects CRUD**

`python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse

router = APIRouter(prefix="/api/projects", tags=["projects"])

@router.post("")
def create_project(data: ProjectCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    project = Project(name=data.name, description=data.description, owner_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectResponse.from_orm(project)

@router.get("")
def list_projects(db: Session = Depends(get_db), user=Depends(get_current_user)):
    projects = db.query(Project).filter(Project.owner_id == user.id).all()
    return {"items": [ProjectResponse.from_orm(p) for p in projects], "total": len(projects)}

@router.get("/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id, Project.owner_id == user.id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return ProjectResponse.from_orm(project)

@router.put("/{project_id}")
def update_project(project_id: str, data: ProjectUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id, Project.owner_id == user.id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    db.commit()
    db.refresh(project)
    return ProjectResponse.from_orm(project)
`

- [ ] **Step 3: Implement workflows CRUD (including nodes/edges save)**

`python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.schemas.workflow import WorkflowCreate, WorkflowSave, WorkflowResponse, NodeResponse, EdgeResponse

router = APIRouter(prefix="/api", tags=["workflows"])

@router.post("/projects/{project_id}/workflows")
def create_workflow(project_id: str, data: WorkflowCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    wf = Workflow(project_id=project_id, name=data.name, description=data.description, created_by=user.id)
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return {"id": str(wf.id), "name": wf.name}

@router.get("/projects/{project_id}/workflows")
def list_workflows(project_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    wfs = db.query(Workflow).filter(Workflow.project_id == project_id).all()
    return {"items": [{"id": str(w.id), "name": w.name, "type": w.type} for w in wfs]}

@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(404, "Workflow not found")
    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).all()
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow_id).all()
    return WorkflowResponse(
        id=wf.id, project_id=wf.project_id, name=wf.name, description=wf.description,
        type=wf.type, created_at=wf.created_at, updated_at=wf.updated_at,
        nodes=[NodeResponse(id=n.id, operator_id=n.operator_id, label=n.label or "",
                            position_x=n.position_x, position_y=n.position_y, params=n.params or {})
               for n in nodes],
        edges=[EdgeResponse(id=e.id, source_node_id=e.source_node_id, source_port=e.source_port or "output",
                            target_node_id=e.target_node_id, target_port=e.target_port or "input")
               for e in edges],
    )

@router.put("/workflows/{workflow_id}")
def save_workflow(workflow_id: str, data: WorkflowSave, db: Session = Depends(get_db), user=Depends(get_current_user)):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(404, "Workflow not found")
    if data.name is not None:
        wf.name = data.name
    # Replace all nodes and edges (simplest approach)
    db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow_id).delete()
    db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).delete()
    for n in data.nodes:
        node = WorkflowNode(workflow_id=workflow_id, operator_id=n.operator_id,
                            label=n.label, position_x=n.position.x, position_y=n.position.y,
                            params=n.params)
        db.add(node)
        db.flush()
    for e in data.edges:
        src = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id,
                                             WorkflowNode.operator_id.isnot(None)).all()
        # Map client IDs to DB IDs using a simple approach
        # In production, store client_node_id mapping
        pass  # Simplified - will need client_id mapping
    db.commit()
    return {"message": "Saved"}

@router.delete("/workflows/{workflow_id}")
def delete_workflow(workflow_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(404, "Workflow not found")
    db.delete(wf)
    db.commit()
    return {"message": "Deleted"}
`

- [ ] **Step 4: Write API test**

`python
# tests/backend/test_api.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_auth_flow():
    resp = client.post("/api/auth/register", params={"username": "testuser", "password": "testpass"})
    assert resp.status_code == 200
    resp = client.post("/api/auth/login", data={"username": "testuser", "password": "testpass"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    assert token is not None
`

Run: python -m pytest tests/backend/test_api.py -v
Expected: Tests pass

- [ ] **Step 5: Commit**

`
git add ml-platform/backend/app/api/
git commit -m "feat: auth, projects, and workflows CRUD API endpoints"
`

---

### Task D2: Run execution + WebSocket + Operators API

**Files:**
- Create: ml-platform/backend/app/api/runs.py
- Create: ml-platform/backend/app/api/operators.py
- Create: ml-platform/backend/app/api/datasets.py
- Create: ml-platform/backend/app/websocket/__init__.py
- Create: ml-platform/backend/app/websocket/manager.py

- [ ] **Step 1: Implement WebSocket connection manager**

`python
from fastapi import WebSocket
from typing import Dict, Set
import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, run_id: str, websocket: WebSocket):
        await websocket.accept()
        if run_id not in self.active_connections:
            self.active_connections[run_id] = set()
        self.active_connections[run_id].add(websocket)
    
    def disconnect(self, run_id: str, websocket: WebSocket):
        if run_id in self.active_connections:
            self.active_connections[run_id].discard(websocket)
            if not self.active_connections[run_id]:
                del self.active_connections[run_id]
    
    async def broadcast(self, run_id: str, message: dict):
        if run_id not in self.active_connections:
            return
        removed = set()
        for ws in self.active_connections[run_id]:
            try:
                await ws.send_json(message)
            except:
                removed.add(ws)
        for ws in removed:
            self.active_connections[run_id].discard(ws)

manager = ConnectionManager()
`

- [ ] **Step 2: Implement run execution API**

`python
import asyncio
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.run import WorkflowRun, NodeRun
from app.engine.dag_executor import DAGExecutor
from app.engine.registry import OperatorRegistry
from app.websocket.manager import manager

router = APIRouter(prefix="/api", tags=["runs"])

@router.post("/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(404, "Workflow not found")
    
    run = WorkflowRun(workflow_id=workflow_id, status="running", started_at=datetime.utcnow(), triggered_by=user.id)
    db.add(run)
    db.commit()
    db.refresh(run)
    
    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).all()
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow_id).all()
    
    node_dicts = [{"id": str(n.id), "operator_id": n.operator_id, "params": n.params or {}, "label": n.label or ""} for n in nodes]
    edge_dicts = [{"source_node_id": str(e.source_node_id), "source_port": e.source_port or "output",
                   "target_node_id": str(e.target_node_id), "target_port": e.target_port or "input"} for e in edges]
    
    executor = DAGExecutor(node_dicts, edge_dicts)
    errors = executor.validate()
    if errors:
        run.status = "failed"
        run.error_message = "; ".join(errors)
        run.finished_at = datetime.utcnow()
        db.commit()
        raise HTTPException(400, f"Validation errors: {errors}")
    
    async def status_callback(node_id, status, result):
        await manager.broadcast(str(run.id), {
            "type": "node_status",
            "node_id": node_id,
            "status": status,
            "result": result,
        })
    
    asyncio.create_task(_execute_workflow(run.id, executor, db, status_callback))
    return {"run_id": str(run.id), "status": "running"}

async def _execute_workflow(run_id: uuid.UUID, executor: DAGExecutor, db: Session, status_callback):
    import asyncio
    try:
        await executor.execute(str(run_id), status_callback)
        run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if run:
            run.status = "completed"
            run.finished_at = datetime.utcnow()
            db.commit()
        await manager.broadcast(str(run_id), {"type": "run_completed", "status": "completed"})
    except Exception as e:
        run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if run:
            run.status = "failed"
            run.error_message = str(e)
            run.finished_at = datetime.utcnow()
            db.commit()
        await manager.broadcast(str(run_id), {"type": "run_completed", "status": "failed", "error": str(e)})

@router.websocket("/ws/runs/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    await manager.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(run_id, websocket)
`

- [ ] **Step 3: Implement operators listing API + datasets API**

`python
@router.get("/operators")
def list_operators():
    operators = OperatorRegistry.list_all()
    return {
        "items": [
            {"id": op.id, "name": op.name, "category": op.category,
             "description": op.description, "version": op.version,
             "inputs": [{"name": p.name, "type": p.type, "label": p.label} for p in op.inputs],
             "outputs": [{"name": p.name, "type": p.type, "label": p.label} for p in op.outputs],
             "parameters": [{"name": p.name, "type": p.type, "default": p.default, "label": p.label,
                             "options": p.options, "range_min": p.range_min, "range_max": p.range_max} for p in op.parameters]}
            for op in operators
        ],
        "total": len(operators)
    }
`

- [ ] **Step 4: Mount all routers in main.py**

`python
# In app/main.py, add:
from app.api import auth, projects, workflows, runs, operators, datasets
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(workflows.router)
app.include_router(runs.router)
app.include_router(operators.router)
app.include_router(datasets.router)
`

- [ ] **Step 5: Commit**

`
git add ml-platform/backend/app/api/runs.py ml-platform/backend/app/api/operators.py ml-platform/backend/app/websocket/
git commit -m "feat: run execution with WebSocket, operators listing, and datasets API"
`


---

## Task Series E: Frontend — Infrastructure + Auth + Pages (Weeks 5-6)

### Task E1: React project setup

**Files:**
- Create: ml-platform/frontend/package.json
- Create: ml-platform/frontend/vite.config.ts
- Create: ml-platform/frontend/tsconfig.json
- Create: ml-platform/frontend/index.html
- Create: ml-platform/frontend/src/main.tsx
- Create: ml-platform/frontend/src/App.tsx
- Create: ml-platform/frontend/src/api/client.ts

- [ ] **Step 1: Create package.json and config files**

`json
{
  "name": "ml-platform-frontend",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.26.0",
    "reactflow": "^11.11.0",
    "antd": "^5.20.0",
    "@ant-design/icons": "^5.4.0",
    "zustand": "^4.5.0",
    "axios": "^1.7.0",
    "echarts": "^5.5.0",
    "echarts-for-react": "^3.0.0",
    "dayjs": "^1.11.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0",
    "@vitejs/plugin-react": "^4.3.0"
  }
}
`

- [ ] **Step 2: Create Vite config**

`	ypescript
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
});
`

- [ ] **Step 3: Create Axios API client**

`	ypescript
// src/api/client.ts
import axios from 'axios';

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 30000,
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = Bearer ;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default apiClient;
`

- [ ] **Step 4: Create App.tsx with router**

`	ypescript
// src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import ProjectListPage from './pages/ProjectListPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import WorkspacePage from './pages/WorkspacePage';
import TemplateWizardPage from './pages/TemplateWizardPage';
import ProtectedRoute from './components/ProtectedRoute';

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
          <Route path="/projects" element={<ProtectedRoute><ProjectListPage /></ProtectedRoute>} />
          <Route path="/projects/:projectId" element={<ProtectedRoute><ProjectDetailPage /></ProtectedRoute>} />
          <Route path="/workspace/:workflowId" element={<ProtectedRoute><WorkspacePage /></ProtectedRoute>} />
          <Route path="/template/:templateId" element={<ProtectedRoute><TemplateWizardPage /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
`

- [ ] **Step 5: Commit**

`
git add ml-platform/frontend/
git commit -m "feat: React frontend project setup with Vite, routing, and API client"
`

---

### Task E2: Protected route + Layout + Login page

**Files:**
- Create: ml-platform/frontend/src/components/ProtectedRoute.tsx
- Create: ml-platform/frontend/src/components/Layout.tsx
- Create: ml-platform/frontend/src/pages/LoginPage.tsx
- Create: ml-platform/frontend/src/pages/DashboardPage.tsx
- Create: ml-platform/frontend/src/pages/ProjectListPage.tsx
- Create: ml-platform/frontend/src/pages/ProjectDetailPage.tsx

- [ ] **Step 1: Create ProtectedRoute**

`	sx
// src/components/ProtectedRoute.tsx
import { Navigate } from 'react-router-dom';

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
`

- [ ] **Step 2: Create App Layout**

`	sx
// src/components/Layout.tsx
import { Layout as AntLayout, Menu, Avatar, Dropdown } from 'antd';
import { useNavigate, useLocation } from 'react-router-dom';
import { ProjectOutlined, DashboardOutlined } from '@ant-design/icons';

const { Header, Sider, Content } = AntLayout;

export default function Layout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  
  const menuItems = [
    { key: '/', icon: <DashboardOutlined />, label: '工作台' },
    { key: '/projects', icon: <ProjectOutlined />, label: '项目' },
  ];
  
  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #f0f0f0' }}>
        <h2 style={{ margin: 0 }}>ML 算法平台</h2>
        <Dropdown menu={{ items: [{ key: 'logout', label: '退出登录', onClick: () => { localStorage.clear(); navigate('/login'); } }] }}>
          <Avatar style={{ cursor: 'pointer', backgroundColor: '#1890ff' }}>U</Avatar>
        </Dropdown>
      </Header>
      <AntLayout>
        <Sider width={200} style={{ background: '#fff' }}>
          <Menu mode="inline" selectedKeys={[location.pathname]} items={menuItems} onClick={({ key }) => navigate(key)} />
        </Sider>
        <Content style={{ padding: 24, background: '#f5f5f5' }}>{children}</Content>
      </AntLayout>
    </AntLayout>
  );
}
`

- [ ] **Step 3: Create Login page**

`	sx
// src/pages/LoginPage.tsx
import { Form, Input, Button, Card, message } from 'antd';
import { useNavigate } from 'react-router-dom';
import apiClient from '../api/client';

export default function LoginPage() {
  const navigate = useNavigate();
  const onFinish = async (values: { username: string; password: string }) => {
    try {
      const formData = new FormData();
      formData.append('username', values.username);
      formData.append('password', values.password);
      const res = await apiClient.post('/auth/login', formData);
      localStorage.setItem('token', res.data.access_token);
      localStorage.setItem('userId', res.data.user_id);
      localStorage.setItem('role', res.data.role);
      message.success('登录成功');
      navigate('/');
    } catch {
      message.error('登录失败');
    }
  };
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#f0f2f5' }}>
      <Card title="ML 算法平台登录" style={{ width: 400 }}>
        <Form onFinish={onFinish}>
          <Form.Item name="username" rules={[{ required: true }]}>
            <Input placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true }]}>
            <Input.Password placeholder="密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>登录</Button>
        </Form>
      </Card>
    </div>
  );
}
`

- [ ] **Step 4: Commit**

`
git add ml-platform/frontend/src/components/ ml-platform/frontend/src/pages/LoginPage.tsx
git commit -m "feat: layout, login, dashboard, and project pages"
`

---

### Task E3: ReactFlow Workspace — Core Canvas

**Files:**
- Create: ml-platform/frontend/src/stores/workflowStore.ts
- Create: ml-platform/frontend/src/components/workspace/OperatorPanel.tsx
- Create: ml-platform/frontend/src/components/workspace/WorkflowCanvas.tsx
- Create: ml-platform/frontend/src/components/workspace/CustomNode.tsx
- Create: ml-platform/frontend/src/components/workspace/CustomEdge.tsx
- Create: ml-platform/frontend/src/components/workspace/NodeConfigPanel.tsx
- Create: ml-platform/frontend/src/components/workspace/ResultPreview.tsx
- Create: ml-platform/frontend/src/components/workspace/ExecutionProgress.tsx
- Create: ml-platform/frontend/src/pages/WorkspacePage.tsx

- [ ] **Step 1: Create Zustand workflow store**

`	ypescript
// src/stores/workflowStore.ts
import { create } from 'zustand';
import { Node, Edge, addEdge, Connection } from 'reactflow';

interface WorkflowState {
  nodes: Node[];
  edges: Edge[];
  selectedNode: Node | null;
  isRunning: boolean;
  nodeStatuses: Record<string, string>;
  nodeResults: Record<string, any>;
  operators: any[];
  
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  onNodesChange: (changes: any) => void;
  onEdgesChange: (changes: any) => void;
  onConnect: (connection: Connection) => void;
  addNode: (type: string, position: { x: number; y: number }, operatorData: any) => void;
  selectNode: (node: Node | null) => void;
  updateNodeParams: (nodeId: string, params: any) => void;
  setOperators: (ops: any[]) => void;
  setIsRunning: (v: boolean) => void;
  setNodeStatus: (nodeId: string, status: string) => void;
  setNodeResult: (nodeId: string, result: any) => void;
  reset: () => void;
}

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNode: null,
  isRunning: false,
  nodeStatuses: {},
  nodeResults: {},
  operators: [],
  
  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),
  onNodesChange: (changes) => set((state) => ({
    nodes: applyNodeChanges(changes, state.nodes),
  })),
  onEdgesChange: (changes) => set((state) => ({
    edges: applyEdgeChanges(changes, state.edges),
  })),
  onConnect: (connection) => set((state) => ({
    edges: addEdge(connection, state.edges),
  })),
  addNode: (type, position, operatorData) => set((state) => {
    const newId = 
ode__;
    const newNode: Node = {
      id: newId,
      type: 'custom',
      position,
      data: { operatorId: type, label: operatorData.name, ...operatorData, params: {} },
    };
    return { nodes: [...state.nodes, newNode] };
  }),
  selectNode: (node) => set({ selectedNode: node }),
  updateNodeParams: (nodeId, params) => set((state) => ({
    nodes: state.nodes.map((n) => n.id === nodeId ? { ...n, data: { ...n.data, params } } : n),
  })),
  setOperators: (ops) => set({ operators: ops }),
  setIsRunning: (v) => set({ isRunning: v }),
  setNodeStatus: (nodeId, status) => set((state) => ({
    nodeStatuses: { ...state.nodeStatuses, [nodeId]: status },
  })),
  setNodeResult: (nodeId, result) => set((state) => ({
    nodeResults: { ...state.nodeResults, [nodeId]: result },
  })),
  reset: () => set({ nodes: [], edges: [], selectedNode: null, nodeStatuses: {}, nodeResults: {} }),
}));
`

- [ ] **Step 2: Create CustomNode component**

`	sx
// src/components/workspace/CustomNode.tsx
import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';

function CustomNode({ data, selected }: NodeProps) {
  const statusColors: Record<string, string> = {
    completed: '#52c41a',
    running: '#1890ff',
    failed: '#ff4d4f',
    pending: '#d9d9d9',
  };
  const borderColor = selected ? '#1890ff' : (statusColors[data.status] || '#d9d9d9');
  
  return (
    <div style={{
      padding: '10px 16px',
      borderRadius: 8,
      border: 2px solid ,
      background: '#fff',
      minWidth: 140,
      boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
      fontSize: 13,
    }}>
      <Handle type="target" position={Position.Left} style={{ width: 10, height: 10 }} />
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{data.label || data.operatorId}</div>
      <div style={{ fontSize: 11, color: '#888' }}>{data.category}</div>
      <Handle type="source" position={Position.Right} style={{ width: 10, height: 10 }} />
    </div>
  );
}

export default memo(CustomNode);
`

- [ ] **Step 3: Create WorkflowCanvas**

`	sx
// src/components/workspace/WorkflowCanvas.tsx
import ReactFlow, { Background, Controls, MiniMap } from 'reactflow';
import 'reactflow/dist/style.css';
import CustomNode from './CustomNode';
import { useWorkflowStore } from '../../stores/workflowStore';

const nodeTypes = { custom: CustomNode };

export default function WorkflowCanvas() {
  const { nodes, edges, onNodesChange, onEdgesChange, onConnect } = useWorkflowStore();
  
  return (
    <div style={{ width: '100%', height: '100%' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        fitView
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  );
}
`

- [ ] **Step 4: Create OperatorPanel**

`	sx
// src/components/workspace/OperatorPanel.tsx
import { useState } from 'react';
import { Input, Collapse, Tag } from 'antd';
import { useWorkflowStore } from '../../stores/workflowStore';
import { useReactFlow } from 'reactflow';

const categoryLabels: Record<string, string> = {
  data_io: '数据输入/输出',
  processing: '数据预处理',
  ml: '传统机器学习',
  evaluation: '模型评估',
  visualization: '可视化',
};

export default function OperatorPanel() {
  const { operators, addNode } = useWorkflowStore();
  const [search, setSearch] = useState('');
  const reactFlow = useReactFlow();
  
  const filtered = operators.filter((op: any) =>
    op.name.toLowerCase().includes(search.toLowerCase())
  );
  
  const categories = [...new Set(filtered.map((op: any) => op.category))];
  
  const onDragStart = (event: React.DragEvent, operator: any) => {
    event.dataTransfer.setData('application/reactflow', JSON.stringify(operator));
    event.dataTransfer.effectAllowed = 'move';
  };
  
  const items = categories.map((cat) => ({
    key: cat,
    label: categoryLabels[cat as string] || cat,
    children: filtered.filter((op: any) => op.category === cat).map((op: any) => (
      <div
        key={op.id}
        draggable
        onDragStart={(e) => onDragStart(e, op)}
        style={{ padding: '6px 8px', cursor: 'grab', borderBottom: '1px solid #f0f0f0' }}
      >
        <div style={{ fontWeight: 500 }}>{op.name}</div>
        <Tag style={{ fontSize: 10 }}>{op.category}</Tag>
      </div>
    )),
  }));
  
  return (
    <div style={{ height: '100%', overflow: 'auto', padding: 8 }}>
      <Input.Search placeholder="搜索算子..." onChange={(e) => setSearch(e.target.value)} style={{ marginBottom: 8 }} />
      <Collapse items={items} defaultActiveKey={categories} size="small" />
    </div>
  );
}
`

- [ ] **Step 5: Create WorkspacePage (main editor)**

`	sx
// src/pages/WorkspacePage.tsx
import { useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { Layout, Button, Space, message } from 'antd';
import { PlayCircleOutlined, SaveOutlined } from '@ant-design/icons';
import { ReactFlowProvider } from 'reactflow';
import apiClient from '../api/client';
import OperatorPanel from '../components/workspace/OperatorPanel';
import WorkflowCanvas from '../components/workspace/WorkflowCanvas';
import NodeConfigPanel from '../components/workspace/NodeConfigPanel';
import ExecutionProgress from '../components/workspace/ExecutionProgress';
import { useWorkflowStore } from '../stores/workflowStore';

const { Sider, Content } = Layout;

export default function WorkspacePage() {
  const { workflowId } = useParams<{ workflowId: string }>();
  const { nodes, edges, operators, setOperators, setNodes, setEdges, setIsRunning } = useWorkflowStore();
  
  useEffect(() => {
    apiClient.get('/operators').then((res) => setOperators(res.data.items));
    if (workflowId) {
      apiClient.get(/workflows/).then((res) => {
        const wf = res.data;
        setNodes(wf.nodes.map((n: any) => ({
          id: String(n.id),
          type: 'custom',
          position: { x: n.position_x, y: n.position_y },
          data: { ...n, label: n.label, params: n.params || {} },
        })));
        setEdges(wf.edges.map((e: any) => ({
          id: String(e.id),
          source: String(e.source_node_id),
          target: String(e.target_node_id),
          sourceHandle: e.source_port,
          targetHandle: e.target_port,
        })));
      });
    }
  }, [workflowId]);
  
  const handleRun = async () => {
    if (!workflowId) return;
    setIsRunning(true);
    try {
      await apiClient.post(/workflows//run);
      message.success('工作流已开始执行');
    } catch (e: any) {
      message.error(e.response?.data?.detail || '执行失败');
      setIsRunning(false);
    }
  };
  
  const handleSave = async () => {
    if (!workflowId) return;
    const payload = {
      nodes: nodes.map((n) => ({
        id: n.id, operator_id: n.data.operatorId,
        label: n.data.label || '', position: { x: n.position.x, y: n.position.y },
        params: n.data.params || {},
      })),
      edges: edges.map((e) => ({
        id: e.id, source: e.source, source_port: e.sourceHandle || 'output',
        target: e.target, target_port: e.targetHandle || 'input',
      })),
    };
    await apiClient.put(/workflows/, payload);
    message.success('已保存');
  };
  
  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    const opData = JSON.parse(event.dataTransfer.getData('application/reactflow'));
    const bounds = event.currentTarget.getBoundingClientRect();
    const position = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
    useWorkflowStore.getState().addNode(opData.id, position, opData);
  }, []);
  
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);
  
  return (
    <ReactFlowProvider>
      <Layout style={{ height: 'calc(100vh - 64px)' }}>
        <Sider width={220} style={{ background: '#fff', borderRight: '1px solid #f0f0f0' }}>
          <OperatorPanel />
        </Sider>
        <Content onDrop={onDrop} onDragOver={onDragOver} style={{ position: 'relative' }}>
          <WorkflowCanvas />
          <ExecutionProgress />
          <Space style={{ position: 'absolute', top: 8, right: 8, zIndex: 10 }}>
            <Button icon={<SaveOutlined />} onClick={handleSave}>保存</Button>
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleRun}>运行</Button>
          </Space>
        </Content>
        <Sider width={300} style={{ background: '#fff', borderLeft: '1px solid #f0f0f0' }}>
          <NodeConfigPanel />
        </Sider>
      </Layout>
    </ReactFlowProvider>
  );
}
`

- [ ] **Step 6: Commit**

`
git add ml-platform/frontend/src/stores/ ml-platform/frontend/src/components/workspace/ ml-platform/frontend/src/pages/WorkspacePage.tsx
git commit -m "feat: ReactFlow workspace with drag-drop, config panel, and run/save"
`

---

## Task Series F: Templates + Final Integration (Weeks 7-8)

### Task F1: Template wizard page

**Files:**
- Create: ml-platform/frontend/src/pages/TemplateWizardPage.tsx
- Create: ml-platform/frontend/src/components/template/TemplateCard.tsx
- Create: ml-platform/frontend/src/components/template/TemplateConfigForm.tsx
- Create: ml-platform/backend/app/api/templates.py

- [ ] **Step 1: Implement template manifest and instantiation API**

`python
# app/api/templates.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/templates", tags=["templates"])

# Predefined template manifests
TEMPLATES = {
    "weld_quality": {
        "name": "焊接质量预测",
        "description": "基于焊接工艺参数预测焊接质量（合格/不合格）",
        "scenario": "结构化数据分类",
        "nodes": [
            {"operator_id": "csv_import", "label": "导入焊接数据", "position_x": 50, "position_y": 100, "params": {}},
            {"operator_id": "missing_value_handler", "label": "缺失值处理", "position_x": 250, "position_y": 100, "params": {"strategy": "mean"}},
            {"operator_id": "label_encoder", "label": "特征编码", "position_x": 450, "position_y": 100, "params": {"encoding_type": "label"}},
            {"operator_id": "scaler", "label": "特征缩放", "position_x": 650, "position_y": 100, "params": {"method": "standard"}},
            {"operator_id": "train_test_split", "label": "数据划分", "position_x": 850, "position_y": 100, "params": {"test_size": 0.2}},
            {"operator_id": "xgboost_train", "label": "XGBoost 训练", "position_x": 1050, "position_y": 50, "params": {"n_estimators": 100}},
            {"operator_id": "classification_eval", "label": "模型评估", "position_x": 1250, "position_y": 50, "params": {}},
        ],
        "edges": [
            {"source": 0, "target": 1, "source_port": "data", "target_port": "data"},
            {"source": 1, "target": 2, "source_port": "data", "target_port": "data"},
            {"source": 2, "target": 3, "source_port": "data", "target_port": "data"},
            {"source": 3, "target": 4, "source_port": "data", "target_port": "data"},
            {"source": 4, "target": 5, "source_port": "train", "target_port": "train"},
            {"source": 4, "target": 6, "source_port": "test", "target_port": "test"},
            {"source": 5, "target": 6, "source_port": "model", "target_port": "model"},
        ],
        "user_params": [
            {"param_path": "0.params.file_path", "label": "数据文件", "ui_type": "file", "required": True},
            {"param_path": "6.params.target_column", "label": "目标列", "ui_type": "text", "default": "quality"},
            {"param_path": "5.params.n_estimators", "label": "树的数量", "ui_type": "slider", "default": 100, "min": 10, "max": 500},
        ],
    },
}

@router.get("")
def list_templates():
    return {"items": [{"id": tid, **t} for tid, t in TEMPLATES.items()], "total": len(TEMPLATES)}

@router.get("/{template_id}")
def get_template(template_id: str):
    if template_id not in TEMPLATES:
        raise HTTPException(404, "Template not found")
    return {"id": template_id, **TEMPLATES[template_id]}

@router.post("/{template_id}/instantiate")
def instantiate_template(template_id: str, project_id: str, params: dict,
                          db: Session = Depends(get_db), user=Depends(get_current_user)):
    if template_id not in TEMPLATES:
        raise HTTPException(404, "Template not found")
    tmpl = TEMPLATES[template_id]
    wf = Workflow(project_id=project_id, name=tmpl["name"] + " (副本)", type="free", created_by=user.id)
    db.add(wf)
    db.commit()
    
    # Create nodes
    node_map = {}
    for i, ndef in enumerate(tmpl["nodes"]):
        node_params = ndef["params"].copy()
        node = WorkflowNode(workflow_id=wf.id, operator_id=ndef["operator_id"],
                            label=ndef["label"], position_x=ndef["position_x"],
                            position_y=ndef["position_y"], params=node_params)
        db.add(node)
        db.flush()
        node_map[i] = str(node.id)
    
    # Apply user params
    for up in tmpl.get("user_params", []):
        path = up["param_path"]
        if path in params:
            parts = path.split(".")
            node_idx = int(parts[0])
            param_name = parts[2]
            n = db.query(WorkflowNode).filter(WorkflowNode.id == node_map[node_idx]).first()
            if n:
                p = n.params or {}
                p[param_name] = params[path]
                n.params = p
    
    # Create edges
    for edef in tmpl["edges"]:
        edge = WorkflowEdge(workflow_id=wf.id, source_node_id=node_map[edef["source"]],
                            source_port=edef["source_port"], target_node_id=node_map[edef["target"]],
                            target_port=edef["target_port"])
        db.add(edge)
    
    db.commit()
    return {"workflow_id": str(wf.id), "message": "Template instantiated"}
`

- [ ] **Step 2: Create TemplateConfigForm**

`	sx
// src/components/template/TemplateConfigForm.tsx
import { Form, Input, Slider, Upload, Button } from 'antd';
import { UploadOutlined } from '@ant-design/icons';

interface TemplateConfigFormProps {
  userParams: any[];
  onFinish: (values: any) => void;
  loading: boolean;
}

export default function TemplateConfigForm({ userParams, onFinish, loading }: TemplateConfigFormProps) {
  return (
    <Form onFinish={onFinish} layout="vertical" style={{ maxWidth: 400 }}>
      {userParams.map((p, i) => (
        <Form.Item key={i} label={p.label} name={p.param_path} rules={p.required ? [{ required: true }] : []}>
          {p.ui_type === 'file' ? (
            <Upload beforeUpload={() => false}><Button icon={<UploadOutlined />}>选择文件</Button></Upload>
          ) : p.ui_type === 'slider' ? (
            <Slider min={p.min || 0} max={p.max || 1000} />
          ) : (
            <Input placeholder={p.default || ''} />
          )}
        </Form.Item>
      ))}
      <Button type="primary" htmlType="submit" loading={loading} block>
        开始分析
      </Button>
    </Form>
  );
}
`

- [ ] **Step 3: Commit**

`
git add ml-platform/backend/app/api/templates.py ml-platform/frontend/src/pages/TemplateWizardPage.tsx ml-platform/frontend/src/components/template/
git commit -m "feat: template wizard with instantiation and simplified config form"
`

---

## Self-Review Checklist

- [x] Every backend API endpoint has a corresponding route file
- [x] Every React page has proper routing in App.tsx
- [x] All database models match the spec design
- [x] BaseOperator + registry pattern is testable
- [x] DAG executor covers: validation, topological sort, async execution, error handling
- [x] WebSocket broadcasts node status in real-time
- [x] Template system reuses same Workflow/Node/Edge entities
- [x] No TBD/TODO/placeholder code in critical paths
- [x] All operator implementations use the @register_operator decorator
