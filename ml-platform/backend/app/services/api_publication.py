"""Idempotent publication of executable platform resources as internal APIs."""

import uuid
from datetime import datetime, timezone

from app.models.api_model import PlatformAPI
from app.models.model_registry import InferenceDeployment
from app.services.project_access import ProjectAccessError, ProjectAccessService


class APIPublicationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _deployment(db, deployment_id: str | uuid.UUID, actor_id: uuid.UUID) -> InferenceDeployment:
    try:
        source_uuid = deployment_id if isinstance(deployment_id, uuid.UUID) else uuid.UUID(str(deployment_id))
    except (TypeError, ValueError) as error:
        raise APIPublicationError("DEPLOYMENT_NOT_FOUND", "Deployment not found") from error
    deployment = db.query(InferenceDeployment).filter(InferenceDeployment.id == source_uuid).first()
    if deployment is None:
        raise APIPublicationError("DEPLOYMENT_NOT_FOUND", "Deployment not found")
    try:
        ProjectAccessService().require(db, deployment.project_id, actor_id, "inference.operate")
    except ProjectAccessError as error:
        code = "DEPLOYMENT_NOT_FOUND" if error.hidden else "DEPLOYMENT_PERMISSION_DENIED"
        raise APIPublicationError(code, "Deployment is not accessible") from error
    return deployment


def publish_deployment(db, deployment_id: str | uuid.UUID, actor_id: uuid.UUID) -> PlatformAPI:
    deployment = _deployment(db, deployment_id, actor_id)
    if deployment.desired_state != "running" or deployment.observed_state != "running":
        raise APIPublicationError("DEPLOYMENT_NOT_READY", "Only running deployments can be published")
    version = deployment.model_version
    api_version = f"v{version.version_number}"
    existing = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "model",
        PlatformAPI.source_id == deployment.id,
        PlatformAPI.version == api_version,
    ).first()
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.status = "published"
        existing.published_at = now
        existing.last_error = None
        db.commit()
        db.refresh(existing)
        return existing
    api = PlatformAPI(
        name=deployment.name, api_type="model", algorithm_type=version.algorithm or "",
        endpoint=f"/api/inference-deployments/{deployment.id}/predict", method="POST",
        version=api_version, status="published", source_kind="model", source_id=deployment.id,
        description=f"Inference API for deployment {deployment.name}",
        request_schema={"records": version.feature_schema or []}, response_schema=version.output_schema or {},
        owner_id=actor_id, is_public=False, published_at=now,
    )
    db.add(api)
    db.commit()
    db.refresh(api)
    return api


def unpublish_deployment(db, deployment_id: str | uuid.UUID, actor_id: uuid.UUID) -> PlatformAPI:
    deployment = _deployment(db, deployment_id, actor_id)
    api = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "model", PlatformAPI.source_id == deployment.id,
    ).order_by(PlatformAPI.created_at.desc()).first()
    if api is None:
        raise APIPublicationError("API_NOT_FOUND", "Published deployment API not found")
    api.status = "offline"
    db.commit()
    db.refresh(api)
    return api


def sync_deployment_publication(
    db,
    deployment_id: str | uuid.UUID,
    actor_id: uuid.UUID,
    *,
    running: bool,
) -> PlatformAPI | None:
    """Synchronize the API catalog after a committed runtime state change."""
    if running:
        return publish_deployment(db, deployment_id, actor_id)

    deployment = _deployment(db, deployment_id, actor_id)
    api = db.query(PlatformAPI).filter(
        PlatformAPI.source_kind == "model",
        PlatformAPI.source_id == deployment.id,
    ).order_by(PlatformAPI.created_at.desc()).first()
    if api is None:
        return None
    api.status = "offline"
    db.commit()
    db.refresh(api)
    return api
