"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine

# Import all operators so they register themselves
import app.operators.io_operators  # noqa: F401
import app.operators.processing  # noqa: F401
import app.operators.ml_operators  # noqa: F401
import app.operators.evaluation  # noqa: F401
import app.operators.visualization  # noqa: F401

# Import API routers
from app.api import auth, projects, workflows, runs, operators, datasets, workflows_direct


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


@app.get("/api/health")
def health_check():
    """Return API health status."""
    return {"status": "ok"}
