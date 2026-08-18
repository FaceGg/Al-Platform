"""Internal authenticated FastAPI surface for ONNX Runtime."""

import hmac

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.inference_runtime.runtime import RuntimeErrorCode, RuntimeRegistry


MAX_BODY_BYTES = 1024 * 1024


def _status_for(code: str) -> int:
    if code == "DEPLOYMENT_SPEC_CONFLICT":
        return 409
    if code in {
        "INFERENCE_SCHEMA_MISMATCH",
        "DEPLOYMENT_SPEC_INVALID",
        "MODEL_SCHEMA_INVALID",
    }:
        return 422
    if code == "INFERENCE_LIMIT_EXCEEDED":
        return 413
    if code == "DEPLOYMENT_NOT_READY":
        return 409
    return 503


def create_runtime_app(*, registry: RuntimeRegistry, internal_token: str) -> FastAPI:
    if len(internal_token) < 32:
        raise ValueError("Inference internal token must contain at least 32 characters")
    app = FastAPI(title="ML Platform Inference Runtime")

    @app.middleware("http")
    async def body_limit(request: Request, call_next):
        if request.url.path.endswith("/predict"):
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > MAX_BODY_BYTES:
                        return JSONResponse(
                            status_code=413,
                            content={"detail": {"code": "INFERENCE_LIMIT_EXCEEDED"}},
                        )
                except ValueError:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": {"code": "INFERENCE_LIMIT_EXCEEDED"}},
                    )
        return await call_next(request)

    def authorize(x_inference_internal_token: str | None = Header(default=None)):
        candidate = x_inference_internal_token or ""
        if not hmac.compare_digest(candidate, internal_token):
            raise HTTPException(
                status_code=401,
                detail={"code": "INFERENCE_UNAUTHORIZED"},
            )

    @app.exception_handler(RuntimeErrorCode)
    async def runtime_error(_request: Request, error: RuntimeErrorCode):
        return JSONResponse(
            status_code=_status_for(error.code),
            content={"detail": {"code": error.code}},
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/internal/deployments")
    def deployments(_auth=Header(default=None, alias="X-Inference-Internal-Token")):
        authorize(_auth)
        return {"items": registry.list()}

    @app.put("/internal/deployments/{runtime_key:path}")
    def load(runtime_key: str, specification: dict, _auth=Header(default=None, alias="X-Inference-Internal-Token")):
        authorize(_auth)
        declared_runtime_key = specification.get("runtime_key")
        if declared_runtime_key is None:
            declared_runtime_key = specification.get("deployment_id")
        if str(declared_runtime_key) != runtime_key:
            raise RuntimeErrorCode("DEPLOYMENT_SPEC_INVALID")
        existing = {
            item["runtime_key"]: item for item in registry.list()
        }.get(runtime_key)
        loaded = registry.load(specification)
        return {
            "runtime_key": loaded.runtime_key,
            "deployment_id": loaded.deployment_id,
            "revision_id": loaded.revision_id,
            "model_version_id": loaded.model_version_id,
            "already_loaded": existing is not None,
        }

    @app.delete("/internal/deployments/{runtime_key:path}")
    def unload(runtime_key: str, _auth=Header(default=None, alias="X-Inference-Internal-Token")):
        authorize(_auth)
        existing = {
            item["runtime_key"]: item for item in registry.list()
        }.get(runtime_key)
        removed = registry.unload(runtime_key)
        return {
            "runtime_key": runtime_key,
            "deployment_id": (existing or {}).get("deployment_id", runtime_key),
            "already_absent": not removed,
        }

    @app.post("/internal/deployments/{runtime_key:path}/predict")
    def predict(runtime_key: str, payload: dict, _auth=Header(default=None, alias="X-Inference-Internal-Token")):
        authorize(_auth)
        if set(payload) != {"records"}:
            raise RuntimeErrorCode("INFERENCE_SCHEMA_MISMATCH")
        return registry.predict(runtime_key, payload["records"])

    return app


def build_runtime_app():
    from app.config import settings
    from app.storage.factory import create_artifact_storage

    secret = settings.resolved_inference_internal_secret
    if secret is None:
        raise RuntimeError("INFERENCE_INTERNAL_SECRET is required")
    registry = RuntimeRegistry(create_artifact_storage(settings))
    return create_runtime_app(
        registry=registry,
        internal_token=secret.get_secret_value(),
    )
