import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectList
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=ProjectList)
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = db.query(Project).filter(Project.owner_id == current_user.id).all()
    return {"items": items, "total": len(items)}


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(name=data.name, description=data.description, owner_id=current_user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == uuid.UUID(project_id), Project.owner_id == current_user.id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    data: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == uuid.UUID(project_id), Project.owner_id == current_user.id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == uuid.UUID(project_id), Project.owner_id == current_user.id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    # Manually clean up related records for existing DB schema compatibility
    from app.models.training import TrainingJob
    from app.models.platform_models import Dataset, OrchestrationApp
    db.query(TrainingJob).filter(TrainingJob.project_id == project.id).delete()
    db.query(Dataset).filter(Dataset.project_id == project.id).update({"project_id": None})
    db.query(OrchestrationApp).filter(OrchestrationApp.project_id == project.id).update({"project_id": None})
    db.delete(project)
    db.commit()


from pydantic import BaseModel
from typing import List

class BatchDeleteRequest(BaseModel):
    ids: List[str]

@router.post("/batch-delete", status_code=200)
def batch_delete_projects(
    data: BatchDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.training import TrainingJob
    from app.models.platform_models import Dataset, OrchestrationApp
    deleted = 0
    for pid_str in data.ids:
        try:
            uid = uuid.UUID(pid_str)
        except ValueError:
            continue
        project = db.query(Project).filter(
            Project.id == uid, Project.owner_id == current_user.id
        ).first()
        if not project:
            continue
        db.query(TrainingJob).filter(TrainingJob.project_id == project.id).delete()
        db.query(Dataset).filter(Dataset.project_id == project.id).update({"project_id": None})
        db.query(OrchestrationApp).filter(OrchestrationApp.project_id == project.id).update({"project_id": None})
        db.delete(project)
        deleted += 1
    db.commit()
    return {"deleted": deleted}
