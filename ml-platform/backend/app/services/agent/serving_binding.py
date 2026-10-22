"""Deployment-reference binding for serving graphs (spec v0.9 §12.2/§12.3).

Closed-loop retrain swaps rotate ``deployments.model_version_id``; serving
graphs that bind a deployment id resolve the CURRENT joblib artifact at
invoke time and therefore follow the swap without republishing. Static
artifact binding stays available for frozen snapshots.
"""

from __future__ import annotations

import uuid


def resolve_deployment_model_artifact(artifact_service, project_id, deployment_id: str) -> str:
    """deployment → current model version → model library joblib artifact."""
    db = artifact_service.db
    from app.models.model_library import ModelLibrary
    from app.models.model_registry import InferenceDeployment, ModelVersion

    try:
        deployment_uuid = uuid.UUID(str(deployment_id))
    except (TypeError, ValueError, AttributeError) as error:
        raise RuntimeError("deployment id is not a valid uuid: %s" % deployment_id) from error
    deployment = (
        db.query(InferenceDeployment)
        .filter(
            InferenceDeployment.id == deployment_uuid,
            InferenceDeployment.project_id == project_id,
        )
        .first()
    )
    if deployment is None:
        raise RuntimeError("deployment not found in project: %s" % deployment_id)
    version = (
        db.query(ModelVersion)
        .filter(ModelVersion.id == deployment.model_version_id)
        .first()
    )
    if version is None or version.source_model_library_id is None:
        raise RuntimeError(
            "deployment current model version has no platform joblib source; "
            "bind model_artifact_id instead"
        )
    library = (
        db.query(ModelLibrary)
        .filter(ModelLibrary.id == version.source_model_library_id)
        .first()
    )
    if library is None or not library.model_artifact_id:
        raise RuntimeError("deployment model library entry has no joblib artifact")
    return str(library.model_artifact_id)


def bound_artifact_id(context, params) -> str:
    """Operator-facing entry: static artifact id unless a deployment is bound."""
    artifact_id = str(params.get("model_artifact_id") or "").strip()
    deployment_id = str(params.get("deployment_id") or "").strip()
    if deployment_id:
        return resolve_deployment_model_artifact(
            context.artifact_service, context.project_id, deployment_id
        )
    return artifact_id
