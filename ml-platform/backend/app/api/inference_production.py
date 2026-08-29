"""Deployment-scoped API-key inference endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from threading import Lock
from time import monotonic, perf_counter
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.models.model_registry import InferenceApiKey, InferenceDeployment, ModelVersion
from app.schemas.model_registry import ProductionPredictRequest, ProductionPredictResponse
from app.services.inference_api_keys import (
    USAGE_TOUCH_INTERVAL_SECONDS,
    InferenceApiKeyError,
    InferenceApiKeyService,
)
from app.services.inference_deployment import InferenceDeploymentError, InferenceDeploymentService
from app.services.inference_observability import InferenceObservability
from app.services.inference_rate_limit import RateLimitBackendUnavailable, RedisTokenBucket
from app.services.inference_rollout import InferenceRolloutError, WeightedTargetRouter
from app.services.inference_runtime_client import InferenceRuntimeClient


MAX_PREDICTION_BODY_BYTES = 1024 * 1024
logger = logging.getLogger(__name__)
_TELEMETRY_EXECUTOR = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="inference-telemetry",
)
_API_KEY_TOUCH_LOCK = Lock()
_API_KEY_TOUCH_TIMES: dict[str, float] = {}


def _claim_api_key_touch(api_key_id) -> bool:
    """Throttle best-effort usage metadata writes per backend process."""
    key = str(api_key_id)
    now = monotonic()
    with _API_KEY_TOUCH_LOCK:
        previous = _API_KEY_TOUCH_TIMES.get(key)
        if previous is not None and now - previous < USAGE_TOUCH_INTERVAL_SECONDS:
            return False
        _API_KEY_TOUCH_TIMES[key] = now
        if len(_API_KEY_TOUCH_TIMES) > 4096:
            cutoff = now - USAGE_TOUCH_INTERVAL_SECONDS
            for item_key, item_time in tuple(_API_KEY_TOUCH_TIMES.items()):
                if item_time < cutoff:
                    _API_KEY_TOUCH_TIMES.pop(item_key, None)
        return True


class PredictionBodyLimitRoute(APIRoute):
    """Reject oversized requests before FastAPI attempts JSON parsing."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def limited(request):
            raw_length = request.headers.get("content-length")
            try:
                if raw_length is not None and int(raw_length) > MAX_PREDICTION_BODY_BYTES:
                    return _error(413, "INFERENCE_LIMIT_EXCEEDED")
            except ValueError:
                return _error(413, "INFERENCE_LIMIT_EXCEEDED")

            chunks = []
            received = 0
            async for chunk in request.stream():
                received += len(chunk)
                if received > MAX_PREDICTION_BODY_BYTES:
                    return _error(413, "INFERENCE_LIMIT_EXCEEDED")
                chunks.append(chunk)
            request._body = b"".join(chunks)
            return await handler(request)

        return limited


def _error(status: int, code: str, *, headers=None):
    return JSONResponse(
        status_code=status,
        content={"detail": {"code": code, "message": code}},
        headers=headers,
    )


def _runtime_error(error) -> str:
    code = getattr(error, "code", "INFERENCE_RUNTIME_UNAVAILABLE")
    allowed = {
        "DEPLOYMENT_NOT_READY", "MODEL_VERSION_NOT_FOUND",
        "STABLE_REVISION_NOT_FOUND", "TARGET_WEIGHTS_INVALID",
    }
    return code if isinstance(code, str) and (code.startswith("INFERENCE_") or code in allowed) else "INFERENCE_RUNTIME_UNAVAILABLE"


def _runtime_status(code: str) -> int:
    if code == "INFERENCE_SCHEMA_MISMATCH":
        return 422
    if code == "INFERENCE_LIMIT_EXCEEDED":
        return 413
    if code == "DEPLOYMENT_NOT_READY":
        return 409
    return 503


@lru_cache(maxsize=1)
def _default_deployment_service():
    """Build one thread-safe runtime client per backend process.

    The inference endpoint is synchronous, so constructing a deployment service
    for every request also rebuilt its HTTP connection pool and Redis-adjacent
    runtime state.  Caching this immutable service keeps connection reuse real
    while each request still receives its own SQLAlchemy session.
    """
    secret = settings.resolved_inference_internal_secret
    if not settings.inference_runtime_url or secret is None:
        return None
    return InferenceDeploymentService(
        InferenceRuntimeClient(
            settings.inference_runtime_url,
            secret.get_secret_value(),
            load_timeout_seconds=settings.inference_load_timeout_seconds,
            predict_timeout_seconds=settings.inference_predict_timeout_seconds,
        ),
        SessionLocal,
    )


@lru_cache(maxsize=1)
def _default_rate_limiter():
    """Build one thread-safe Redis client/pool per backend process."""
    url = settings.redis_events_url
    if url is None:
        return None
    try:
        from redis import Redis
        return RedisTokenBucket(Redis.from_url(url.get_secret_value(), decode_responses=True))
    except Exception:
        return None


def _persist_observation(
    request_id,
    deployment_id,
    revision_id,
    model_version_id,
    api_key_id,
    batch_size,
    duration_ms,
    status,
    error_code=None,
):
    """Persist telemetry after response so DB aggregation cannot inflate p95."""
    try:
        with SessionLocal() as db:
            InferenceObservability().record_request(
                db,
                request_id,
                deployment_id,
                revision_id,
                model_version_id,
                api_key_id,
                batch_size,
                duration_ms,
                status,
                error_code,
                aggregate=True,
            )
            db.commit()

            # Do not hold the API-key row lock while the minute bucket is locked.
            # High-volume telemetry otherwise deadlocks on the two tables.
            if _claim_api_key_touch(api_key_id):
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                cutoff = now - timedelta(seconds=USAGE_TOUCH_INTERVAL_SECONDS)
                db.query(InferenceApiKey).filter(
                    InferenceApiKey.id == api_key_id,
                    or_(
                        InferenceApiKey.last_used_at.is_(None),
                        InferenceApiKey.last_used_at < cutoff,
                    ),
                ).update(
                    {InferenceApiKey.last_used_at: now},
                    synchronize_session=False,
                )
                db.commit()
    except Exception:
        logger.exception("inference telemetry persistence failed")


def _schedule_observation(
    background_tasks: BackgroundTasks,
    *,
    request_id,
    deployment_id,
    revision_id,
    model_version_id,
    api_key_id,
    batch_size,
    duration_ms,
    status,
    error_code=None,
):
    background_tasks.add_task(
        _TELEMETRY_EXECUTOR.submit,
        _persist_observation,
        request_id,
        deployment_id,
        revision_id,
        model_version_id,
        api_key_id,
        batch_size,
        duration_ms,
        status,
        error_code,
    )


def build_inference_production_router(
    *,
    api_key_service=None,
    rate_limiter=None,
    observability=None,
    deployment_service=None,
):
    router = APIRouter(tags=["inference_production"], route_class=PredictionBodyLimitRoute)

    def dependencies():
        return (
            api_key_service or InferenceApiKeyService(),
            rate_limiter if rate_limiter is not None else _default_rate_limiter(),
            observability or InferenceObservability(
                log_retention_days=settings.inference_log_retention_days,
            ),
            deployment_service or _default_deployment_service(),
        )

    @router.post(
        "/api/v1/inference/{deployment_id}/predict",
        response_model=ProductionPredictResponse,
    )
    def predict(
        deployment_id: UUID,
        data: ProductionPredictRequest,
        request: Request,
        background_tasks: BackgroundTasks,
        x_inference_api_key: str | None = Header(default=None, alias="X-Inference-Api-Key"),
        x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
        db: Session = Depends(get_db),
    ):
        key_service, limiter, observation, deployment_service_value = dependencies()
        try:
            api_key = key_service.verify(
                db, x_inference_api_key, deployment_id=deployment_id,
                scope="inference.predict", touch_last_used=False,
            )
        except InferenceApiKeyError as error:
            code = error.code if error.code in {
                "INFERENCE_API_KEY_INVALID", "INFERENCE_API_KEY_EXPIRED",
                "INFERENCE_API_KEY_REVOKED", "INFERENCE_API_KEY_OUT_OF_SCOPE",
            } else "INFERENCE_API_KEY_INVALID"
            return _error(401, code)
        deployment = db.query(InferenceDeployment).filter(
            InferenceDeployment.id == deployment_id,
        ).first()
        if deployment is None:
            return _error(404, "INFERENCE_DEPLOYMENT_NOT_FOUND")
        request_id = getattr(request.state, "request_id", None)
        if request_id is None:
            try:
                request_id = UUID(x_request_id) if x_request_id else uuid4()
            except (TypeError, ValueError, AttributeError):
                request_id = uuid4()
        request_id = str(request_id)
        if len(data.records) > 100:
            return _error(413, "INFERENCE_LIMIT_EXCEEDED")
        if limiter is None:
            return _error(503, "RATE_LIMIT_BACKEND_UNAVAILABLE")
        try:
            decision = limiter.consume(
                f"inference:{deployment_id}:{api_key.id}",
                capacity=settings.inference_rate_limit_capacity,
                refill_per_second=settings.inference_rate_limit_refill_per_second,
            )
        except RateLimitBackendUnavailable:
            return _error(503, "RATE_LIMIT_BACKEND_UNAVAILABLE")
        if not decision.allowed:
            try:
                if isinstance(observation, InferenceObservability):
                    _schedule_observation(
                        background_tasks,
                        request_id=request_id,
                        deployment_id=deployment.id,
                        revision_id=None,
                        model_version_id=None,
                        api_key_id=api_key.id,
                        batch_size=len(data.records),
                        duration_ms=0,
                        status="limited",
                        error_code="INFERENCE_RATE_LIMITED",
                    )
                else:
                    observation.record_request(
                        db, request_id, deployment.id, None, None, api_key.id,
                        len(data.records), 0, "limited", "INFERENCE_RATE_LIMITED",
                        aggregate=False,
                    )
            except Exception:
                db.rollback()
            return _error(429, "INFERENCE_RATE_LIMITED", headers={"Retry-After": str(decision.retry_after_seconds)})
        if deployment_service_value is None:
            return _error(503, "INFERENCE_RUNTIME_UNAVAILABLE")
        started = perf_counter()
        revision_id = model_version_id = None
        try:
            if deployment.desired_state != "running" or deployment.observed_state != "running":
                raise InferenceDeploymentError("DEPLOYMENT_NOT_READY")
            routed = WeightedTargetRouter().select_active(deployment, request_id)
            revision_id, model_version_id = routed.revision_id, routed.model_version_id
            version = db.query(ModelVersion).filter(ModelVersion.id == model_version_id).first()
            if version is None:
                raise InferenceDeploymentError("MODEL_VERSION_NOT_FOUND")
            result = deployment_service_value.runtime.predict(
                f"{revision_id}:{model_version_id}", data.records,
            )
            duration_ms = max(0, int((perf_counter() - started) * 1000))
            if isinstance(observation, InferenceObservability):
                _schedule_observation(
                    background_tasks,
                    request_id=request_id,
                    deployment_id=deployment.id,
                    revision_id=revision_id,
                    model_version_id=model_version_id,
                    api_key_id=api_key.id,
                    batch_size=len(data.records),
                    duration_ms=duration_ms,
                    status="success",
                )
            else:
                observation.record_request(
                    db, request_id, deployment.id, revision_id, model_version_id, api_key.id,
                    len(data.records), duration_ms, "success", aggregate=False,
                )
            return {
                "request_id": request_id,
                "deployment_id": str(deployment.id),
                "revision_id": str(revision_id),
                "model_version_id": str(model_version_id),
                "version_number": int(version.version_number),
                "predictions": result.get("predictions"),
                "probabilities": result.get("probabilities"),
                "duration_ms": result.get("duration_ms", duration_ms),
            }
        except InferenceDeploymentError as error:
            code = _runtime_error(error)
        except InferenceRolloutError as error:
            code = error.code
        except Exception as error:
            code = _runtime_error(error)
        duration_ms = max(0, int((perf_counter() - started) * 1000))
        try:
            if isinstance(observation, InferenceObservability):
                _schedule_observation(
                    background_tasks,
                    request_id=request_id,
                    deployment_id=deployment.id,
                    revision_id=revision_id,
                    model_version_id=model_version_id,
                    api_key_id=api_key.id,
                    batch_size=len(data.records),
                    duration_ms=duration_ms,
                    status="error",
                    error_code=code,
                )
            else:
                observation.record_request(
                    db, request_id, deployment.id, revision_id, model_version_id, api_key.id,
                    len(data.records), duration_ms, "error", code, aggregate=False,
                )
        except Exception:
            db.rollback()
        return _error(_runtime_status(code), code)

    return router


router = build_inference_production_router()
