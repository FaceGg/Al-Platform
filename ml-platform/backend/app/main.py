"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis import asyncio as redis_async
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.database_migrations import ensure_schema_compatibility
from app.database_schema import require_current_schema
from app.events.subscriber import RedisRunEventSubscriber
from app.middleware.request_id import RequestIdMiddleware
from app.websocket.manager import manager
from app.services.project_access import ProjectAccessError
from app.services.spot_weld_quality import recover_orphaned_local_quality_runs

# Import all operators so they register themselves
# Import models (must happen before create_all)
from app.models import knowledge  # noqa: F401 (register models)
from app.models import training as training_models  # noqa: F401 (register models)
from app.models import algorithm as algo_models  # noqa: F401 (register models)
from app.models import model_library as ml_models  # noqa: F401 (register models)
from app.models import api_model as api_models  # noqa: F401 (register models)
from app.models import compute as compute_models  # noqa: F401 (register models)
from app.models import agent as agent_models  # noqa: F401 (register models)
from app.models import platform_models as pm  # noqa: F401 (register models)
from app.models import access as access_models  # noqa: F401 (register models)
from app.models import spot_weld_quality as spot_weld_quality_models  # noqa: F401 (register models)

import app.operators.io_operators  # noqa: F401
import app.operators.processing  # noqa: F401
import app.operators.ml_operators  # noqa: F401
import app.operators.evaluation  # noqa: F401
import app.operators.visualization  # noqa: F401

try:
    import app.operators.dl_operators  # noqa: F401
except ImportError:
    pass

try:
    import app.operators.mechanism_models  # noqa: F401
except ImportError:
    pass

import app.operators.control_operators  # noqa: F401

# Import API routers
from app.api import auth, projects, workflows, runs, operators, datasets, workflows_direct, workflow_versions, templates
from app.api import users, models as model_api
from app.api import knowledge, monitor, labeling, training, orchestration
from app.api import algorithm as algo_api, platform_api, compute, annotations as annot_api, chat as chat_api
from app.api import model_library as model_lib_api, dashboard as dash_api, readiness, experiments, schedules
from app.api import project_access as project_access_api
from app.api import model_registry as model_registry_api
from app.api import spot_weld_quality as spot_weld_quality_api


def initialize_database(app_settings=None, db_engine=None) -> None:
    """Initialize local schemas or verify the production migration revision."""
    if app_settings is None:
        app_settings = settings
    if db_engine is None:
        db_engine = engine
    if app_settings.app_mode == "production":
        require_current_schema(db_engine)
        return
    Base.metadata.create_all(bind=db_engine)
    ensure_schema_compatibility(db_engine)


def configure_runtime_dependencies(
    target_app: FastAPI,
    *,
    app_settings=None,
    db_engine=None,
    session_factory=None,
) -> None:
    """Configure optional runtime database dependencies for an application."""
    target_app.state.settings = app_settings
    target_app.state.engine = db_engine
    target_app.state.session_factory = session_factory


def _runtime_dependencies(target_app: FastAPI):
    app_settings = getattr(target_app.state, "settings", None)
    db_engine = getattr(target_app.state, "engine", None)
    session_factory = getattr(target_app.state, "session_factory", None)
    return (
        settings if app_settings is None else app_settings,
        engine if db_engine is None else db_engine,
        SessionLocal if session_factory is None else session_factory,
    )


async def start_event_subscriber(app_settings):
    """Start the Redis-to-WebSocket bridge when event Redis is configured."""
    redis_events_url = getattr(app_settings, "redis_events_url", None)
    if redis_events_url is None:
        return None
    redis_client = redis_async.Redis.from_url(
        redis_events_url.get_secret_value(),
        decode_responses=False,
    )
    stop_event = asyncio.Event()
    subscriber = RedisRunEventSubscriber(redis_client, manager)
    task = asyncio.create_task(subscriber.run(stop_event))
    return redis_client, stop_event, task


async def stop_event_subscriber(runtime) -> None:
    if runtime is None:
        return
    redis_client, stop_event, task = runtime
    stop_event.set()
    try:
        await task
    finally:
        await redis_client.aclose()


def ensure_default_admin(session_factory) -> None:
    """Create the local bootstrap administrator without startup races."""
    from app.models.user import User
    from passlib.context import CryptContext

    db = session_factory()
    try:
        if db.query(User).filter(User.username == "admin").first():
            return
        pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
        db.add(User(
            username="admin",
            password_hash=pwd_ctx.hash("admin123"),
            role="admin",
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if db.query(User).filter(User.username == "admin").first() is None:
                raise
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create database tables on startup and clean up on shutdown."""
    app_settings, db_engine, session_factory = _runtime_dependencies(app)
    initialize_database(app_settings, db_engine)
    ensure_default_admin(session_factory)
    with session_factory() as db:
        recover_orphaned_local_quality_runs(db)
    # Capture event loop for background thread WebSocket broadcast
    import app.api.runs as runs_mod
    runs_mod._main_loop = asyncio.get_running_loop()
    event_subscriber = None
    try:
        event_subscriber = await start_event_subscriber(app_settings)
        yield
    finally:
        try:
            await stop_event_subscriber(event_subscriber)
        finally:
            db_engine.dispose()


app = FastAPI(
    title="智擎",
    description="Web-based visual AI model training orchestration platform",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ProjectAccessError)
async def project_access_exception_handler(
    request: Request, error: ProjectAccessError,
):
    status = 404 if error.hidden else 403
    return JSONResponse(
        status_code=status,
        content={"detail": {"code": error.code, "message": str(error)}},
    )
app.add_middleware(RequestIdMiddleware)

# Register routers
app.include_router(auth.router)
app.include_router(project_access_api.router)
app.include_router(projects.router)
app.include_router(workflows.router)
app.include_router(runs.router)
app.include_router(operators.router)
app.include_router(datasets.router)
app.include_router(workflows_direct.router)
app.include_router(workflow_versions.router)
app.include_router(templates.router)
app.include_router(users.router)
app.include_router(model_api.router)
app.include_router(knowledge.router)
app.include_router(monitor.router)
app.include_router(labeling.router)
app.include_router(training.router)
app.include_router(orchestration.router)
app.include_router(algo_api.router)
app.include_router(platform_api.router)
app.include_router(compute.router)
app.include_router(annot_api.router)
app.include_router(chat_api.router)
app.include_router(model_lib_api.router)
app.include_router(dash_api.router)
app.include_router(readiness.router)
app.include_router(experiments.router)
app.include_router(schedules.router)
app.include_router(model_registry_api.router)
app.include_router(spot_weld_quality_api.router)


@app.get("/api/health")
def health_check():
    """Return API health status."""
    return {"status": "ok"}


