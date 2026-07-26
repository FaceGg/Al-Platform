"""Project-scoped model registry and basic inference API."""

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.api.project_security import audit_service, require_project_access, resolve_project_access
from app.database import SessionLocal, get_db
from app.models.artifact import Artifact
from app.models.model_registry import (
    DeploymentRollout, InferenceDeployment, ModelCard,
    ModelVersion, RegisteredModel,
)
from app.models.user import User
from app.schemas.model_registry import (
    DeploymentCreate,
    ApiKeyCreate,
    LifecycleComment,
    MetricQuery,
    ModelCardGuidanceUpdate,
    OnnxVersionCreate,
    PlatformVersionCreate,
    PredictRequest,
    RequestLogQuery,
    RegisteredModelCreate,
    RolloutCommand,
    RolloutCreate,
    VersionCreate,
)
from app.services.artifact_service import ArtifactAccessError, build_artifact_service
from app.services.audit import AuditIntent
from app.services.inference_deployment import InferenceDeploymentError, InferenceDeploymentService
from app.services.inference_api_keys import InferenceApiKeyError, InferenceApiKeyService
from app.services.inference_observability import InferenceObservability, InferenceObservabilityError
from app.services.inference_rollout import InferenceRolloutError, InferenceRolloutService
from app.services.inference_runtime_client import InferenceRuntimeClient
from app.services.model_cards import ModelCardError, ModelCardService
from app.services.model_registry import ModelRegistryError, ModelRegistryService


PROJECT_WRITE_ACTIONS = {
    "POST /api/projects/{project_id}/registered-models": "registered_model.create",
    "POST /api/projects/{project_id}/model-artifacts": "model_artifact.upload",
    "POST /api/registered-models/{model_id}/versions": "model_version.register",
    "POST /api/model-versions/{version_id}/approve": "model_version.approve",
    "POST /api/model-versions/{version_id}/reject": "model_version.reject",
    "POST /api/model-versions/{version_id}/archive": "model_version.archive",
    "POST /api/projects/{project_id}/inference-deployments": "inference_deployment.create",
    "POST /api/inference-deployments/{deployment_id}/start": "inference_deployment.start",
    "POST /api/inference-deployments/{deployment_id}/stop": "inference_deployment.stop",
}


def _error(error):
    code = getattr(error, "code", "MODEL_REGISTRY_FAILED")
    status = 409
    if code.endswith("NOT_FOUND"):
        status = 404
    elif code in {"MODEL_SCHEMA_INVALID", "MODEL_NAME_INVALID", "DEPLOYMENT_NAME_INVALID"}:
        status = 422
    elif code == "INFERENCE_LIMIT_EXCEEDED":
        status = 413
    raise HTTPException(status, {"code": code, "message": code})


def _model_view(model):
    latest = max(model.versions, key=lambda item: item.version_number, default=None)
    return {
        "id": str(model.id), "project_id": str(model.project_id),
        "name": model.name, "description": model.description,
        "latest_version": latest.version_number if latest else None,
        "latest_approval_status": latest.approval_status if latest else None,
        "created_at": model.created_at.isoformat() if model.created_at else None,
    }


def _version_view(version):
    return {
        "id": str(version.id),
        "registered_model_id": str(version.registered_model_id),
        "version_number": version.version_number,
        "source_kind": version.source_kind,
        "framework": version.framework,
        "algorithm": version.algorithm,
        "feature_schema": version.feature_schema,
        "output_schema": version.output_schema,
        "metrics": version.metrics,
        "conversion_metadata": version.conversion_metadata,
        "approval_status": version.approval_status,
        "approval_comment": version.approval_comment,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


def _deployment_view(deployment):
    return {
        "id": str(deployment.id), "project_id": str(deployment.project_id),
        "name": deployment.name, "model_version_id": str(deployment.model_version_id),
        "desired_state": deployment.desired_state,
        "observed_state": deployment.observed_state,
        "last_error_code": deployment.last_error_code,
        "last_checked_at": deployment.last_checked_at.isoformat() if deployment.last_checked_at else None,
        "created_at": deployment.created_at.isoformat() if deployment.created_at else None,
    }


def _release_view(release):
    return {
        "id": str(release.id), "deployment_id": str(release.deployment_id),
        "from_revision_id": str(release.from_revision_id) if release.from_revision_id else None,
        "to_revision_id": str(release.to_revision_id), "state": release.state,
        "current_step": release.current_step, "lock_version": release.lock_version,
        "step_schedule": release.step_schedule, "thresholds": release.thresholds,
        "last_error_code": release.last_error_code,
        "created_at": release.created_at, "started_at": release.started_at,
        "completed_at": release.completed_at,
    }


def _api_key_view(key):
    return {
        "id": str(key.id), "prefix": key.prefix, "scopes": list(key.scopes),
        "expires_at": key.expires_at, "last_used_at": key.last_used_at,
        "revoked_at": key.revoked_at, "created_at": key.created_at,
    }


def _card_view(card):
    return {
        "id": str(card.id), "model_version_id": str(card.model_version_id),
        "operational_guidance": card.operational_guidance,
        "guidance_revision": card.guidance_revision,
        "approval_status": card.approval_status, "release_status": card.release_status,
        "created_at": card.created_at, "updated_at": card.updated_at,
    }


def _registry_access(db, model_id, user_id):
    try:
        uid = UUID(str(model_id))
    except ValueError:
        raise HTTPException(404, {"code": "REGISTERED_MODEL_NOT_FOUND"})
    model = db.query(RegisteredModel).filter(RegisteredModel.id == uid).first()
    if model is None:
        raise HTTPException(404, {"code": "REGISTERED_MODEL_NOT_FOUND"})
    access = resolve_project_access(db, model.project_id, user_id)
    if access is None:
        raise HTTPException(404, {"code": "REGISTERED_MODEL_NOT_FOUND"})
    return model, access


def _version_access(db, version_id, user_id):
    try:
        uid = UUID(str(version_id))
    except ValueError:
        raise HTTPException(404, {"code": "MODEL_VERSION_NOT_FOUND"})
    version = db.query(ModelVersion).filter(ModelVersion.id == uid).first()
    if version is None:
        raise HTTPException(404, {"code": "MODEL_VERSION_NOT_FOUND"})
    access = resolve_project_access(db, version.registered_model.project_id, user_id)
    if access is None:
        raise HTTPException(404, {"code": "MODEL_VERSION_NOT_FOUND"})
    return version, access


def _deployment_access(db, deployment_id, user_id):
    try:
        uid = UUID(str(deployment_id))
    except ValueError:
        raise HTTPException(404, {"code": "INFERENCE_DEPLOYMENT_NOT_FOUND"})
    deployment = db.query(InferenceDeployment).filter(InferenceDeployment.id == uid).first()
    if deployment is None:
        raise HTTPException(404, {"code": "INFERENCE_DEPLOYMENT_NOT_FOUND"})
    access = resolve_project_access(db, deployment.project_id, user_id)
    if access is None:
        raise HTTPException(404, {"code": "INFERENCE_DEPLOYMENT_NOT_FOUND"})
    return deployment, access


def _default_services(db):
    from app.config import settings
    artifact_service = build_artifact_service(db)
    registry = ModelRegistryService(
        artifact_service=artifact_service,
        conversion_timeout_seconds=settings.inference_conversion_timeout_seconds,
    )
    secret = settings.resolved_inference_internal_secret
    if settings.inference_runtime_url and secret is not None:
        client = InferenceRuntimeClient(
            settings.inference_runtime_url,
            secret.get_secret_value(),
            load_timeout_seconds=settings.inference_load_timeout_seconds,
            predict_timeout_seconds=settings.inference_predict_timeout_seconds,
        )
        deployment = InferenceDeploymentService(client, SessionLocal)
    else:
        deployment = None
    return registry, deployment


def build_model_registry_router(
    *, registry_service=None, deployment_service=None, session_factory=None,
):
    router = APIRouter(tags=["model_registry"])

    def services(db):
        if registry_service is not None and deployment_service is not None:
            return registry_service, deployment_service
        default_registry, default_deployment = _default_services(db)
        return registry_service or default_registry, deployment_service or default_deployment

    @router.get("/api/projects/{project_id}/registered-models")
    def list_models(project_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        require_project_access(db, project_id, current_user.id, "project.read")
        items = db.query(RegisteredModel).filter(RegisteredModel.project_id == project_id).order_by(RegisteredModel.created_at.desc()).all()
        return {"items": [_model_view(item) for item in items], "total": len(items)}

    @router.post("/api/projects/{project_id}/registered-models", status_code=201)
    def create_model(project_id: UUID, data: RegisteredModelCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        access = resolve_project_access(db, project_id, current_user.id)
        registry, _ = services(db)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="model.register",
            intent=AuditIntent(project_id=project_id, action="registered_model.create", resource_type="registered_model", changes={"name": data.name}),
            allowed_changes={"name"},
        ):
            model = registry.create_registered_model(db, project_id=project_id, actor_id=current_user.id, name=data.name, description=data.description)
        return _model_view(model)

    @router.post("/api/projects/{project_id}/model-artifacts", status_code=201)
    def upload_onnx(project_id: UUID, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        access = resolve_project_access(db, project_id, current_user.id)
        filename = Path(file.filename or "").name
        if not filename.lower().endswith(".onnx"):
            raise HTTPException(422, {"code": "MODEL_SOURCE_UNSUPPORTED"})
        artifact_service = build_artifact_service(db) if registry_service is None else registry_service.artifact_service
        uri = None
        try:
            with audit_service(db).project_action(
                db, request=request, actor=current_user, access=access,
                permission="model.register",
                intent=AuditIntent(project_id=project_id, action="model_artifact.upload", resource_type="model_artifact", changes={"filename": filename}),
                allowed_changes={"filename"},
            ):
                artifact = artifact_service.create_from_stream(project_id, file.file, filename, "model", metadata={"source": "upload"}, max_bytes=256 * 1024 * 1024, commit=False)
                uri = artifact.storage_uri
        except Exception:
            if uri:
                artifact_service.storage.delete(uri)
            raise
        return {"id": str(artifact.id), "name": artifact.name, "format": artifact.format, "file_size": artifact.file_size, "sha256": (artifact.metadata_ or {}).get("sha256")}

    @router.get("/api/registered-models/{model_id}")
    def model_detail(model_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        model, _access = _registry_access(db, model_id, current_user.id)
        return {**_model_view(model), "versions": [_version_view(item) for item in sorted(model.versions, key=lambda value: value.version_number, reverse=True)]}

    @router.get("/api/registered-models/{model_id}/versions")
    def list_versions(model_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        model, _access = _registry_access(db, model_id, current_user.id)
        items = sorted(model.versions, key=lambda value: value.version_number, reverse=True)
        return {"items": [_version_view(item) for item in items], "total": len(items)}

    @router.post("/api/registered-models/{model_id}/versions", status_code=201)
    def register_version(model_id: str, data: VersionCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        model, access = _registry_access(db, model_id, current_user.id)
        registry, _ = services(db)
        compensation_uri = None
        try:
            with audit_service(db).project_action(
                db, request=request, actor=current_user, access=access,
                permission="model.register",
                intent=AuditIntent(project_id=model.project_id, action="model_version.register", resource_type="model_version", changes={"source_kind": data.source_kind}),
                allowed_changes={"source_kind"},
            ):
                if isinstance(data, PlatformVersionCreate):
                    version = registry.register_platform_version(db, model_id=model.id, source_model_library_id=data.source_model_library_id, actor_id=current_user.id, commit=False)
                    generated = db.query(Artifact).filter(
                        Artifact.id == version.onnx_artifact_id,
                    ).one()
                    compensation_uri = generated.storage_uri
                else:
                    version = registry.register_onnx_version(db, model_id=model.id, source_artifact_id=data.source_artifact_id, actor_id=current_user.id, feature_schema=[item.model_dump() for item in data.feature_schema], output_schema=data.output_schema.model_dump(), commit=False)
        except (ModelRegistryError, ArtifactAccessError) as error:
            if compensation_uri:
                registry.compensate_version_artifact(compensation_uri)
            _error(error)
        except Exception:
            if compensation_uri:
                registry.compensate_version_artifact(compensation_uri)
            raise
        return _version_view(version)

    @router.get("/api/model-versions/{version_id}")
    def version_detail(version_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        version, _access = _version_access(db, version_id, current_user.id)
        return _version_view(version)

    def lifecycle(version_id, data, request, db, current_user, action, audit_action):
        version, access = _version_access(db, version_id, current_user.id)
        registry, _ = services(db)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="model.approve",
            intent=AuditIntent(project_id=version.registered_model.project_id, action=audit_action, resource_type="model_version", resource_id=str(version.id), changes={"comment": data.comment}),
            allowed_changes={"comment"},
        ):
            try:
                version = getattr(registry, action)(db, version.id, current_user.id, data.comment, commit=False)
            except ModelRegistryError as error:
                _error(error)
        return _version_view(version)

    @router.post("/api/model-versions/{version_id}/approve")
    def approve(version_id: str, data: LifecycleComment, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        return lifecycle(version_id, data, request, db, current_user, "approve", "model_version.approve")

    @router.post("/api/model-versions/{version_id}/reject")
    def reject(version_id: str, data: LifecycleComment, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        return lifecycle(version_id, data, request, db, current_user, "reject", "model_version.reject")

    @router.post("/api/model-versions/{version_id}/archive")
    def archive(version_id: str, data: LifecycleComment, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        return lifecycle(version_id, data, request, db, current_user, "archive", "model_version.archive")

    @router.get("/api/projects/{project_id}/inference-deployments")
    def list_deployments(project_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        require_project_access(db, project_id, current_user.id, "project.read")
        items = db.query(InferenceDeployment).filter(InferenceDeployment.project_id == project_id).order_by(InferenceDeployment.created_at.desc()).all()
        return {"items": [_deployment_view(item) for item in items], "total": len(items)}

    @router.post("/api/projects/{project_id}/inference-deployments", status_code=201)
    def create_deployment(project_id: UUID, data: DeploymentCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        access = resolve_project_access(db, project_id, current_user.id)
        _, deployment_service_value = services(db)
        if deployment_service_value is None:
            raise HTTPException(503, {"code": "INFERENCE_RUNTIME_UNAVAILABLE"})
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="deployment.create",
            intent=AuditIntent(project_id=project_id, action="inference_deployment.create", resource_type="inference_deployment", changes={"name": data.name, "model_version_id": str(data.model_version_id)}),
            allowed_changes={"name", "model_version_id"},
        ):
            try:
                deployment = deployment_service_value.create(db, project_id=project_id, version_id=data.model_version_id, actor_id=current_user.id, name=data.name, commit=False)
            except InferenceDeploymentError as error:
                _error(error)
        return _deployment_view(deployment)

    @router.get("/api/inference-deployments/{deployment_id}")
    def deployment_detail(deployment_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        deployment, _access = _deployment_access(db, deployment_id, current_user.id)
        return _deployment_view(deployment)

    def operate(deployment_id, request, db, current_user, action, audit_action):
        deployment, access = _deployment_access(db, deployment_id, current_user.id)
        _, deployment_service_value = services(db)
        if deployment_service_value is None:
            raise HTTPException(503, {"code": "INFERENCE_RUNTIME_UNAVAILABLE"})
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="inference.operate",
            intent=AuditIntent(project_id=deployment.project_id, action=audit_action, resource_type="inference_deployment", resource_id=str(deployment.id), changes={"desired_state": "running" if action == "start" else "stopped"}),
            allowed_changes={"desired_state"},
        ):
            pass
        try:
            result = getattr(deployment_service_value, action)(db, deployment.id)
        except InferenceDeploymentError as error:
            _error(error)
        return _deployment_view(result)

    @router.post("/api/inference-deployments/{deployment_id}/start")
    def start(deployment_id: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        return operate(deployment_id, request, db, current_user, "start", "inference_deployment.start")

    @router.post("/api/inference-deployments/{deployment_id}/stop")
    def stop(deployment_id: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        return operate(deployment_id, request, db, current_user, "stop", "inference_deployment.stop")

    @router.post("/api/inference-deployments/{deployment_id}/predict")
    def predict(deployment_id: str, data: PredictRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        deployment, _access = _deployment_access(db, deployment_id, current_user.id)
        require_project_access(db, deployment.project_id, current_user.id, "inference.operate")
        _, deployment_service_value = services(db)
        if deployment_service_value is None:
            raise HTTPException(503, {"code": "INFERENCE_RUNTIME_UNAVAILABLE"})
        try:
            return deployment_service_value.predict(db, deployment.id, data.records)
        except InferenceDeploymentError as error:
            _error(error)

    def rollout_service_for(db):
        _, deployment_service_value = services(db)
        if deployment_service_value is None:
            raise HTTPException(503, {"code": "INFERENCE_RUNTIME_UNAVAILABLE"})
        return InferenceRolloutService(deployment_service_value.runtime)

    def release_access(db, deployment_id, release_id, user_id):
        deployment, access = _deployment_access(db, deployment_id, user_id)
        try:
            release_uuid = UUID(str(release_id))
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(404, {"code": "ROLLOUT_NOT_FOUND"})
        release = db.query(DeploymentRollout).filter(
            DeploymentRollout.id == release_uuid,
            DeploymentRollout.deployment_id == deployment.id,
        ).first()
        if release is None:
            raise HTTPException(404, {"code": "ROLLOUT_NOT_FOUND"})
        return deployment, access, release

    def rollout_error(error):
        code = error.code
        status = 404 if code.endswith("NOT_FOUND") else 409
        raise HTTPException(status, {"code": code, "message": code})

    @router.get("/api/inference-deployments/{deployment_id}/releases")
    def list_releases(deployment_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        deployment, _access = _deployment_access(db, deployment_id, current_user.id)
        require_project_access(db, deployment.project_id, current_user.id, "project.read")
        releases = db.query(DeploymentRollout).filter(
            DeploymentRollout.deployment_id == deployment.id,
        ).order_by(DeploymentRollout.created_at.desc()).all()
        return {"items": [_release_view(item) for item in releases], "total": len(releases)}

    @router.get("/api/inference-deployments/{deployment_id}/releases/{release_id}")
    def release_detail(deployment_id: str, release_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        deployment, _access, release = release_access(db, deployment_id, release_id, current_user.id)
        require_project_access(db, deployment.project_id, current_user.id, "project.read")
        return _release_view(release)

    @router.post("/api/inference-deployments/{deployment_id}/releases", status_code=201)
    def create_release(deployment_id: str, data: RolloutCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        deployment, access = _deployment_access(db, deployment_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="inference.operate",
            intent=AuditIntent(project_id=deployment.project_id, action="inference_release.create", resource_type="deployment_rollout", resource_id=str(deployment.id), changes={"strategy": data.strategy}),
            allowed_changes={"strategy"},
        ):
            try:
                release = rollout_service_for(db).create_candidate(
                    db, deployment.id, current_user.id,
                    [item.model_dump() for item in data.targets], data.strategy,
                    data.step_schedule,
                    {key: value for key, value in {
                        "max_error_rate": data.max_error_rate, "max_p95_ms": data.max_p95_ms,
                    }.items() if value is not None} or None,
                )
            except InferenceRolloutError as error:
                rollout_error(error)
        return _release_view(release)

    def command_release(deployment_id, release_id, data, request, db, current_user, command):
        deployment, access, release = release_access(db, deployment_id, release_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="inference.operate",
            intent=AuditIntent(project_id=deployment.project_id, action=f"inference_release.{command}", resource_type="deployment_rollout", resource_id=str(release.id), changes={}),
            allowed_changes=set(),
        ):
            try:
                release = getattr(rollout_service_for(db), command)(
                    db, release.id, data.expected_lock_version,
                )
            except InferenceRolloutError as error:
                rollout_error(error)
        return _release_view(release)

    @router.post("/api/inference-deployments/{deployment_id}/releases/{release_id}/pause")
    def pause_release(deployment_id: str, release_id: str, data: RolloutCommand, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        return command_release(deployment_id, release_id, data, request, db, current_user, "pause")

    @router.post("/api/inference-deployments/{deployment_id}/releases/{release_id}/resume")
    def resume_release(deployment_id: str, release_id: str, data: RolloutCommand, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        return command_release(deployment_id, release_id, data, request, db, current_user, "resume")

    @router.post("/api/inference-deployments/{deployment_id}/releases/{release_id}/rollback")
    def rollback_release(deployment_id: str, release_id: str, data: RolloutCommand, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        return command_release(deployment_id, release_id, data, request, db, current_user, "rollback")

    @router.get("/api/inference-deployments/{deployment_id}/api-keys")
    def list_api_keys(deployment_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        deployment, _access = _deployment_access(db, deployment_id, current_user.id)
        require_project_access(db, deployment.project_id, current_user.id, "inference.operate")
        items = InferenceApiKeyService().list_for_deployment(db, deployment.id)
        return {"items": [_api_key_view(item) for item in items], "total": len(items)}

    @router.post("/api/inference-deployments/{deployment_id}/api-keys", status_code=201)
    def create_api_key(deployment_id: str, data: ApiKeyCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        deployment, access = _deployment_access(db, deployment_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access,
            permission="inference.operate",
            intent=AuditIntent(project_id=deployment.project_id, action="inference_api_key.create", resource_type="inference_api_key", resource_id=str(deployment.id), changes={"scopes": data.scopes}),
            allowed_changes={"scopes"},
        ):
            try:
                created = InferenceApiKeyService().create(db, deployment.id, current_user.id, data.scopes, data.expires_at)
            except InferenceApiKeyError as error:
                raise HTTPException(422, {"code": error.code, "message": error.code})
        return {**_api_key_view(created.record), "plaintext": created.plaintext}

    def key_access(db, key_id, user_id):
        try:
            key_uuid = UUID(str(key_id))
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(404, {"code": "INFERENCE_API_KEY_NOT_FOUND"})
        from app.models.model_registry import InferenceApiKey
        key = db.query(InferenceApiKey).filter(InferenceApiKey.id == key_uuid).first()
        if key is None:
            raise HTTPException(404, {"code": "INFERENCE_API_KEY_NOT_FOUND"})
        deployment, access = _deployment_access(db, key.deployment_id, user_id)
        return key, deployment, access

    @router.post("/api/inference-api-keys/{key_id}/rotate")
    def rotate_api_key(key_id: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        key, deployment, access = key_access(db, key_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access, permission="inference.operate",
            intent=AuditIntent(project_id=deployment.project_id, action="inference_api_key.rotate", resource_type="inference_api_key", resource_id=str(key.id), changes={}), allowed_changes=set(),
        ):
            created = InferenceApiKeyService().rotate(db, key.id, current_user.id)
        return {**_api_key_view(created.record), "plaintext": created.plaintext}

    @router.post("/api/inference-api-keys/{key_id}/revoke")
    def revoke_api_key(key_id: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        key, deployment, access = key_access(db, key_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access, permission="inference.operate",
            intent=AuditIntent(project_id=deployment.project_id, action="inference_api_key.revoke", resource_type="inference_api_key", resource_id=str(key.id), changes={}), allowed_changes=set(),
        ):
            record = InferenceApiKeyService().revoke(db, key.id, current_user.id)
        return _api_key_view(record)

    @router.get("/api/inference-deployments/{deployment_id}/request-logs")
    def request_logs(deployment_id: str, query: RequestLogQuery = Depends(), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        deployment, _access = _deployment_access(db, deployment_id, current_user.id)
        require_project_access(db, deployment.project_id, current_user.id, "project.read")
        try:
            items = InferenceObservability().query_logs(db, deployment.id, query.since, query.until, page=query.page, page_size=query.page_size)
        except InferenceObservabilityError as error:
            raise HTTPException(422, {"code": error.code, "message": error.code})
        return {"items": items, "page": query.page, "page_size": query.page_size}

    @router.get("/api/inference-deployments/{deployment_id}/metrics")
    def metrics(deployment_id: str, query: MetricQuery = Depends(), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        deployment, _access = _deployment_access(db, deployment_id, current_user.id)
        require_project_access(db, deployment.project_id, current_user.id, "project.read")
        observer = InferenceObservability()
        try:
            buckets = observer.query_metrics(db, deployment.id, query.since, query.until, page=query.page, page_size=query.page_size)
        except InferenceObservabilityError as error:
            raise HTTPException(422, {"code": error.code, "message": error.code})
        return {"items": [
            {"bucket_start": item.bucket_start, "request_count": item.request_count, "success_count": item.success_count, "error_count": item.error_count, "limited_count": item.limited_count, "load_failure_count": item.load_failure_count, "latency_buckets": item.latency_buckets, "traffic_weights": item.traffic_weights}
            for item in buckets
        ], "summary": observer.summarize_metrics(buckets), "page": query.page, "page_size": query.page_size}

    def card_access(db, card_id, user_id):
        try:
            card_uuid = UUID(str(card_id))
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(404, {"code": "MODEL_CARD_NOT_FOUND"})
        card = db.query(ModelCard).filter(ModelCard.id == card_uuid).first()
        if card is None:
            raise HTTPException(404, {"code": "MODEL_CARD_NOT_FOUND"})
        version, access = _version_access(db, card.model_version_id, user_id)
        return card, version, access

    @router.get("/api/model-versions/{version_id}/model-card")
    def model_card(version_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        version, _access = _version_access(db, version_id, current_user.id)
        require_project_access(db, version.registered_model.project_id, current_user.id, "project.read")
        card = ModelCardService().ensure_for_version(db, version)
        db.commit()
        return _card_view(card)

    @router.patch("/api/model-cards/{card_id}/guidance")
    def update_model_card_guidance(card_id: str, data: ModelCardGuidanceUpdate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        card, version, access = card_access(db, card_id, current_user.id)
        with audit_service(db).project_action(
            db, request=request, actor=current_user, access=access, permission="model.approve",
            intent=AuditIntent(project_id=version.registered_model.project_id, action="model_card.guidance.update", resource_type="model_card", resource_id=str(card.id), changes={"operational_guidance": data.operational_guidance}), allowed_changes={"operational_guidance"},
        ):
            try:
                card = ModelCardService().update_guidance(db, card.id, data.operational_guidance)
            except ModelCardError as error:
                raise HTTPException(422, {"code": error.code, "message": error.code})
        return _card_view(card)

    @router.get("/api/model-cards/{card_id}/export")
    def export_model_card(card_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        card, version, _access = card_access(db, card_id, current_user.id)
        require_project_access(db, version.registered_model.project_id, current_user.id, "project.read")
        try:
            return ModelCardService().export(db, card.id)
        except ModelCardError as error:
            raise HTTPException(404, {"code": error.code, "message": error.code})

    return router


router = build_model_registry_router()
