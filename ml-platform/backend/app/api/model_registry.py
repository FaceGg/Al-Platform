"""Project-scoped model registry and basic inference API."""

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.api.project_security import audit_service, require_project_access, resolve_project_access
from app.database import SessionLocal, get_db
from app.models.artifact import Artifact
from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
from app.models.user import User
from app.schemas.model_registry import (
    DeploymentCreate,
    LifecycleComment,
    OnnxVersionCreate,
    PlatformVersionCreate,
    PredictRequest,
    RegisteredModelCreate,
    VersionCreate,
)
from app.services.artifact_service import ArtifactAccessError, build_artifact_service
from app.services.audit import AuditIntent
from app.services.inference_deployment import InferenceDeploymentError, InferenceDeploymentService
from app.services.inference_runtime_client import InferenceRuntimeClient
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
    "DELETE /api/registered-models/{model_id}": "registered_model.delete",
    "DELETE /api/inference-deployments/{deployment_id}": "inference_deployment.delete",
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

    @router.delete("/api/registered-models/{model_id}")
    def delete_model(model_id: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        model, access = _registry_access(db, model_id, current_user.id)
        deleted_model_id = str(model.id)
        try:
            with audit_service(db).project_action(
                db, request=request, actor=current_user, access=access,
                permission="model.register",
                intent=AuditIntent(project_id=model.project_id, action="registered_model.delete", resource_type="registered_model", resource_id=deleted_model_id, changes={"name": model.name}),
                allowed_changes={"name"},
            ):
                deployment_exists = (
                    db.query(InferenceDeployment.id)
                    .join(ModelVersion, InferenceDeployment.model_version_id == ModelVersion.id)
                    .filter(ModelVersion.registered_model_id == model.id)
                    .first()
                )
                if deployment_exists is not None:
                    raise ModelRegistryError("MODEL_DEPLOYMENT_EXISTS")
                for version in list(model.versions):
                    db.delete(version)
                db.delete(model)
        except ModelRegistryError as error:
            _error(error)
        return {"id": deleted_model_id}

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

    @router.delete("/api/inference-deployments/{deployment_id}")
    def delete_deployment(deployment_id: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        deployment, access = _deployment_access(db, deployment_id, current_user.id)
        deleted_deployment_id = str(deployment.id)
        try:
            with audit_service(db).project_action(
                db, request=request, actor=current_user, access=access,
                permission="deployment.create",
                intent=AuditIntent(project_id=deployment.project_id, action="inference_deployment.delete", resource_type="inference_deployment", resource_id=deleted_deployment_id, changes={"name": deployment.name}),
                allowed_changes={"name"},
            ):
                if deployment.desired_state != "stopped" or deployment.observed_state != "stopped":
                    raise InferenceDeploymentError("DEPLOYMENT_NOT_STOPPED")
                db.delete(deployment)
        except InferenceDeploymentError as error:
            _error(error)
        return {"id": deleted_deployment_id}

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

    return router


router = build_model_registry_router()
