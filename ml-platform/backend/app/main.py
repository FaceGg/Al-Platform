"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine

# Import all operators so they register themselves
# Import models (must happen before create_all)
from app.models import knowledge  # noqa: F401 (register models)
from app.models import training as training_models  # noqa: F401 (register models)
from app.models import agent as agent_models  # noqa: F401 (register models)

import app.operators.io_operators  # noqa: F401
import app.operators.processing  # noqa: F401
import app.operators.ml_operators  # noqa: F401
import app.operators.evaluation  # noqa: F401
import app.operators.visualization  # noqa: F401

try:
    import app.operators.dl_operators  # noqa: F401
except ImportError:
    pass

# Import API routers
from app.api import auth, projects, workflows, runs, operators, datasets, workflows_direct, templates
from app.api import users, models as model_api
from app.api import knowledge, monitor, labeling, training, orchestration


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create database tables on startup and clean up on shutdown."""
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()


app = FastAPI(
    title="ML Platform API",
    description="Web-based visual ML workflow platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(workflows.router)
app.include_router(runs.router)
app.include_router(operators.router)
app.include_router(datasets.router)
app.include_router(workflows_direct.router)
app.include_router(templates.router)
app.include_router(users.router)
app.include_router(model_api.router)
app.include_router(knowledge.router)
app.include_router(monitor.router)
app.include_router(labeling.router)
app.include_router(training.router)
app.include_router(orchestration.router)


@app.get("/api/health")
def health_check():
    """Return API health status."""
    return {"status": "ok"}
