"""FastAPI application entry point."""

GENERICIZATION_BRIDGE_ONLY = True

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis import asyncio as redis_async
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.database_migrations import ensure_schema_compatibility
from app.database_schema import require_current_schema
from app.events.subscriber import RedisRunEventSubscriber
from app.events.domain import DomainEventRecorder, NullDomainEventRecorder
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security import RequestSecurityMiddleware
from app.websocket.manager import manager
from app.services.project_access import ProjectAccessError
from app.services.resource_access import ResourceAccessError
from app.services.notification_outbox import OutboxDomainEventRecorder
from app.services.security import expand_local_dev_origins
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
from app.models import platform_audit as platform_audit_models  # noqa: F401 (register models)
from app.models import notifications as notification_models  # noqa: F401 (register models)
from app.models import spot_weld_quality as spot_weld_quality_models  # noqa: F401 (register models)
from app.models import annotator as annotator_models  # noqa: F401 (register models)

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

logger = logging.getLogger(__name__)

# Import API routers
from app.api import auth, projects, workflows, runs, operators, datasets, workflows_direct, workflow_versions, templates
from app.api import users, models as model_api
from app.api import knowledge, monitor, labeling, training, orchestration
from app.api import algorithm as algo_api, platform_api, compute, annotations as annot_api, chat as chat_api
from app.api import generic_tasks as generic_tasks_api, annotation_task_state as annotation_task_state_api
from app.api import model_library as model_lib_api, dashboard as dash_api, readiness, experiments, schedules
from app.api import project_access as project_access_api
from app.api import model_registry as model_registry_api
from app.api import inference_production as inference_production_api
from app.api import platform_security as platform_security_api
from app.api import notifications as notifications_api
from app.api import spot_weld_quality as spot_weld_quality_api
from app.api import annotator_internal as annotator_internal_api
from app.api import annotation_returns as annotation_returns_api
from app.api import model_exports as model_exports_api
from app.api import kubernetes_clusters as kubernetes_clusters_api
from app.api import kubernetes_jobs as kubernetes_jobs_api
from app.api import notebooks as notebooks_api
from app.api import images as images_api
from app.api import cluster_governance as cluster_governance_api
from app.api import demo_loop as demo_loop_api
from app.api import llm_profiles as llm_profiles_api
from app.api import announcements as announcements_api
from app.api import prompt_templates as prompt_templates_api
from app.api import chat_tools_api
from app.api import knowledge_center_api
from app.api import agent_center as agent_center_api
from app.api import agent_extras

logger = logging.getLogger(__name__)


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
    domain_event_recorder: DomainEventRecorder | None = None,
) -> None:
    """Configure optional runtime database dependencies for an application."""
    target_app.state.settings = app_settings
    target_app.state.engine = db_engine
    target_app.state.session_factory = session_factory
    target_app.state.domain_event_recorder = (
        NullDomainEventRecorder() if domain_event_recorder is None else domain_event_recorder
    )


def _runtime_dependencies(target_app: FastAPI):
    app_settings = getattr(target_app.state, "settings", None)
    db_engine = getattr(target_app.state, "engine", None)
    session_factory = getattr(target_app.state, "session_factory", None)
    return (
        settings if app_settings is None else app_settings,
        engine if db_engine is None else db_engine,
        SessionLocal if session_factory is None else session_factory,
    )


def _log_event_subscriber_exit(task: "asyncio.Task") -> None:
    """订阅任务只被 create_task 持有，异常死亡须留下日志痕迹。"""
    if task.cancelled():
        logger.info("run event subscriber task cancelled")
        return
    error = task.exception()
    if error is not None:
        logger.error("run event subscriber task terminated: %r", error)
    else:
        logger.info("run event subscriber task stopped")


async def start_event_subscriber(app_settings):
    """Start the Redis-to-WebSocket bridge when event Redis is configured."""
    redis_events_url = getattr(app_settings, "redis_events_url", None)
    if redis_events_url is None:
        return None
    resolved = redis_events_url.get_secret_value().strip()
    if not resolved:
        # 作业级 env 可能泄漏空串（如标准 e2e 段未配事件 Redis）——视同未配置，
        # 否则订阅器会对空地址无限重连刷错。
        return None
    redis_client = redis_async.Redis.from_url(
        resolved,
        decode_responses=False,
    )
    stop_event = asyncio.Event()
    subscriber = RedisRunEventSubscriber(redis_client, manager)
    task = asyncio.create_task(subscriber.run(stop_event))
    task.add_done_callback(_log_event_subscriber_exit)
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


def ensure_default_admin(session_factory, app_settings=None) -> None:
    """Create the bootstrap administrator without startup races.

    初始口令只从 ML_PLATFORM_ADMIN_INITIAL_PASSWORD（settings.
    admin_initial_password）读取，源码不落任何凭据字面量。仅当库中
    尚无 admin 时才需要口令：production 未配置则拒绝引导（fail-closed，
    不创建不可控账号；已部署环境 admin 已存在，升级重启不受影响）；
    本地开发未配置则跳过引导并提示，避免弱口令默认值。lifespan 会传入
    注入式 settings，与其它运行时依赖的注入口径一致。
    """
    from passlib.context import CryptContext

    from app.models.user import User

    runtime_settings = app_settings if app_settings is not None else settings
    db = session_factory()
    try:
        if db.query(User).filter(User.username == "admin").first():
            return
        configured = getattr(runtime_settings, "admin_initial_password", None)
        password = configured.get_secret_value() if configured is not None else None
        if not password or not password.strip():
            if getattr(runtime_settings, "app_mode", "local") == "production":
                raise RuntimeError(
                    "ML_PLATFORM_ADMIN_INITIAL_PASSWORD must be set to bootstrap "
                    "the initial administrator in production"
                )
            logger.warning(
                "bootstrap: ML_PLATFORM_ADMIN_INITIAL_PASSWORD not set; skipping "
                "initial admin creation (set it before first start, or register "
                "the first user and promote it)"
            )
            return
        pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
        db.add(User(
            username="admin",
            password_hash=pwd_ctx.hash(password),
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


def repair_orphaned_project_owners(db) -> int:
    """Transfer legacy projects without a valid owner to the platform admin."""
    from app.models.project import Project
    from app.models.user import User

    admin = db.query(User).filter(
        User.username == "admin",
        User.role == "admin",
    ).first()
    if admin is None:
        return 0

    orphaned_project_ids = [
        project_id
        for (project_id,) in db.query(Project.id).outerjoin(
            User,
            Project.owner_id == User.id,
        ).filter(or_(
            Project.owner_id.is_(None),
            User.id.is_(None),
        )).all()
    ]
    if not orphaned_project_ids:
        return 0

    db.query(Project).filter(Project.id.in_(orphaned_project_ids)).update(
        {Project.owner_id: admin.id},
        synchronize_session=False,
    )
    db.commit()
    return len(orphaned_project_ids)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create database tables on startup and clean up on shutdown."""
    app_settings, db_engine, session_factory = _runtime_dependencies(app)
    initialize_database(app_settings, db_engine)
    ensure_default_admin(session_factory, app_settings=app_settings)
    try:
        from app.services.llm_gateway import bootstrap_default_llm_profile

        bootstrap_default_llm_profile(session_factory)
    except Exception:  # noqa: BLE001 - bootstrap must never block app startup
        logger.warning("LLM profile env bootstrap failed", exc_info=True)
    # A-10：启动期清扫僵尸 running run（存活期间由 beat 60s 周期兜底）；
    # 本地无 celery 时 inspect 无响应属正常，异常不阻塞启动
    try:
        from app.tasks.recovery import sweep_stale_workflow_runs_startup

        reconciled = sweep_stale_workflow_runs_startup()
        if reconciled:
            logger.info("startup swept %s stale workflow runs", reconciled)
    except Exception:  # noqa: BLE001 - 清扫失败不阻塞启动
        logger.warning("startup workflow-run sweep failed", exc_info=True)
    with session_factory() as db:
        repair_orphaned_project_owners(db)
        recover_orphaned_local_quality_runs(db)
        # 启动期清扫进程重启遗留的 running 状态 AgentRun（依据 heartbeat_at）。
        from app.services.agent.executor import recover_stale_agent_runs

        recover_stale_agent_runs(
            db,
            stale_after=timedelta(seconds=getattr(
                app_settings,
                "agent_run_stale_after_seconds",
                settings.agent_run_stale_after_seconds,
            )),
        )
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
            tensorboard_manager = getattr(app.state, "tensorboard_process_manager", None)
            if tensorboard_manager is not None:
                tensorboard_manager.close()
            db_engine.dispose()


def _allowed_origins() -> frozenset[str]:
    configured = {
        settings.frontend_origin,
        settings.annotator_public_origin,
        *(
            value.strip()
            for value in settings.frontend_origin_aliases.split(",")
            if value.strip()
        ),
    }
    if settings.app_mode == "local":
        return expand_local_dev_origins(configured)
    return frozenset(configured)


_ALLOWED_ORIGINS = _allowed_origins()


app = FastAPI(
    title="AI模型训练编排平台",
    description="Web-based visual AI model training orchestration platform",
    version="0.2.0",
    lifespan=lifespan,
)
app.state.domain_event_recorder = OutboxDomainEventRecorder()

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    RequestSecurityMiddleware,
    allowed_origins=_ALLOWED_ORIGINS,
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


@app.exception_handler(ResourceAccessError)
async def resource_access_exception_handler(
    request: Request, error: ResourceAccessError,
):
    return JSONResponse(
        status_code=404,
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
app.include_router(training.spec_router)
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
app.include_router(inference_production_api.router)
app.include_router(platform_security_api.router)
app.include_router(notifications_api.router)
# Generic task routes are registered before the deprecated industry route so
# the closed legacy write path cannot shadow the new platform boundary.
app.include_router(generic_tasks_api.router)
app.include_router(annotation_task_state_api.router)
app.include_router(annotation_returns_api.router)
app.include_router(model_exports_api.router)
app.include_router(kubernetes_clusters_api.router)
app.include_router(kubernetes_jobs_api.router)
app.include_router(notebooks_api.router)
app.include_router(images_api.router)
app.include_router(cluster_governance_api.router)
app.include_router(demo_loop_api.router)
app.include_router(llm_profiles_api.router)
app.include_router(announcements_api.router)
app.include_router(prompt_templates_api.router)
app.include_router(chat_tools_api.router)
app.include_router(knowledge_center_api.router)
app.include_router(agent_center_api.router)
app.include_router(agent_extras.router)
app.include_router(spot_weld_quality_api.router)
app.include_router(spot_weld_quality_api.all_runs_router)
app.include_router(annotator_internal_api.router)


@app.get("/api/health")
def health_check():
    """Return API health status."""
    return {"status": "ok"}


