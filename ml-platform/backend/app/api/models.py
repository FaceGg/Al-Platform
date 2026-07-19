from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.project import Project
from app.models.artifact import Artifact
from app.models.user import User
from app.api.auth import get_current_user
from app.services.artifact_service import build_artifact_service
from app.api.project_security import audit_service, require_project_access, resolve_project_access
from app.services.audit import AuditIntent

router = APIRouter(prefix="/api", tags=["models"])
PROJECT_WRITE_ACTIONS = {
    "DELETE /api/models/{model_id}": "model.delete",
}


@router.get("/projects/{project_id}/models")
def list_project_models(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = require_project_access(
        db, project_id, current_user.id, "project.read",
    ).project
    artifacts = db.query(Artifact).filter(
        Artifact.project_id == UUID(project_id),
        Artifact.type == "model",
    ).all()
    return [
        {
            "id": str(a.id),
            "name": a.name,
            "type": a.type,
            "file_size": a.file_size,
            "format": a.format,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in artifacts
    ]


@router.get("/models/{model_id}")
def get_model_detail(
    model_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(Artifact).filter(
        Artifact.id == UUID(model_id),
        Artifact.type == "model",
    ).first()
    if not artifact:
        raise HTTPException(404, "Model not found")
    require_project_access(db, artifact.project_id, current_user.id, "project.read")
    return {
        "id": str(artifact.id),
        "project_id": str(artifact.project_id),
        "name": artifact.name,
        "type": artifact.type,
        "file_size": artifact.file_size,
        "format": artifact.format,
        "metadata": artifact.metadata_,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
    }


@router.delete("/models/{model_id}")
def delete_model(
    model_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(Artifact).filter(
        Artifact.id == UUID(model_id),
        Artifact.type == "model",
    ).first()
    if not artifact:
        raise HTTPException(404, "Model not found")
    access = resolve_project_access(db, artifact.project_id, current_user.id)
    storage_uri = artifact.storage_uri
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="resource.delete",
        intent=AuditIntent(
            project_id=artifact.project_id, action="model.delete",
            resource_type="model", resource_id=str(artifact.id),
        ),
        allowed_changes=set(),
    ):
        db.delete(artifact)
    try:
        build_artifact_service(db).storage.delete(storage_uri)
    except Exception:
        pass
    return {"message": "Model deleted"}
