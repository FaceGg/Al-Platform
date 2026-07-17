from fastapi import APIRouter, HTTPException
from redis import Redis

from app.config import settings
from app.database import engine
from app.services.readiness_service import ReadinessService
from app.storage.factory import create_artifact_storage
from app.tasks.celery_app import celery_app

router = APIRouter(tags=["health"])


def build_readiness_service(app_settings=settings) -> ReadinessService:
    redis_client = None
    task_app = None
    if app_settings.task_backend == "celery":
        task_app = celery_app
        if app_settings.redis_events_url is not None:
            redis_client = Redis.from_url(
                app_settings.redis_events_url.get_secret_value(),
                decode_responses=False,
            )
    storage = create_artifact_storage(app_settings)
    return ReadinessService(
        engine,
        app_settings,
        redis_client=redis_client,
        celery_app=task_app,
        storage=storage,
    )


@router.get("/api/ready")
def readiness():
    service = build_readiness_service()
    try:
        result = service.check_all()
    finally:
        if service.redis_client is not None:
            service.redis_client.close()
    if not result["ready"]:
        raise HTTPException(status_code=503, detail=result)
    return result
