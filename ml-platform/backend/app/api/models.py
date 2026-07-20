from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.project import Project
from app.models.artifact import Artifact
from app.models.user import User
from app.api.auth import get_current_user
from app.services.artifact_service import build_artifact_service

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/projects/{project_id}/models")
def list_project_models(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == UUID(project_id), Project.owner_id == current_user.id).first()
    if not project:
        raise HTTPException(404, "Project not found")
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
    artifact = db.query(Artifact).join(Project).filter(
        Artifact.id == UUID(model_id),
        Artifact.type == "model",
        Project.owner_id == current_user.id,
    ).first()
    if not artifact:
        raise HTTPException(404, "Model not found")
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    artifact = db.query(Artifact).join(Project).filter(
        Artifact.id == UUID(model_id),
        Artifact.type == "model",
        Project.owner_id == current_user.id,
    ).first()
    if not artifact:
        raise HTTPException(404, "Model not found")
    build_artifact_service(db).delete_content(artifact)
    db.delete(artifact)
    db.commit()
    return {"message": "Model deleted"}
