import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.experiment import Experiment
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectList
from app.api.auth import get_current_user
from app.services.project_access import ProjectAccessService
from app.services.audit import AuditIntent
from app.api.project_security import (
    audit_service,
    require_project_access,
    resolve_project_access,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])
PROJECT_WRITE_ACTIONS = {
    "POST /api/projects": "project.create",
    "PUT /api/projects/{project_id}": "project.update",
    "DELETE /api/projects/{project_id}": "project.delete",
    "POST /api/projects/batch-delete": "project.batch_delete",
}


@router.get("", response_model=ProjectList)
def list_projects(
    sort_by: str = Query(default="created_at", pattern="^(name|created_at)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProjectAccessService()
    column = Project.name if sort_by == "name" else Project.created_at
    ordering = column.asc() if sort_order == "asc" else column.desc()
    projects = service.accessible_project_query(db, current_user.id).order_by(ordering).all()
    items = [{
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "owner_id": project.owner_id,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "project_role": service.resolve(db, project.id, current_user.id).role.value,
    } for project in projects]
    return {"items": items, "total": len(items)}


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    data: ProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(name=data.name, description=data.description, owner_id=current_user.id)
    db.add(project)
    db.flush()
    access = resolve_project_access(db, project.id, current_user.id)
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="project.update",
        intent=AuditIntent(
            project_id=project.id,
            action="project.create",
            resource_type="project",
            resource_id=str(project.id),
            changes={"name": data.name, "description": data.description},
        ),
        allowed_changes={"name", "description"},
    ):
        pass
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return require_project_access(db, project_id, current_user.id, "project.read").project


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    data: ProjectUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = resolve_project_access(db, project_id, current_user.id)
    project = access.project if access is not None else None
    intent_id = project.id if project is not None else uuid.UUID(project_id)
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="project.update",
        intent=AuditIntent(
            project_id=intent_id,
            action="project.update",
            resource_type="project",
            resource_id=str(intent_id),
            changes=data.model_dump(exclude_none=True),
        ),
        allowed_changes={"name", "description"},
    ):
        if data.name is not None:
            project.name = data.name
        if data.description is not None:
            project.description = data.description
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = resolve_project_access(db, project_id, current_user.id)
    project = access.project if access is not None else None
    intent_id = project.id if project is not None else uuid.UUID(project_id)
    # Manually clean up related records for existing DB schema compatibility
    from app.models.training import TrainingJob
    from app.models.platform_models import Dataset, OrchestrationApp
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="project.delete",
        intent=AuditIntent(
            project_id=intent_id,
            action="project.delete",
            resource_type="project",
            resource_id=str(intent_id),
        ),
        allowed_changes=set(),
    ):
        db.query(TrainingJob).filter(TrainingJob.project_id == project.id).delete()
        db.query(Experiment).filter(Experiment.project_id == project.id).delete()
        db.query(Dataset).filter(Dataset.project_id == project.id).update({"project_id": None})
        db.query(OrchestrationApp).filter(OrchestrationApp.project_id == project.id).update({"project_id": None})
        db.delete(project)


from pydantic import BaseModel
from typing import List

class BatchDeleteRequest(BaseModel):
    ids: List[str]

@router.post("/batch-delete", status_code=200)
def batch_delete_projects(
    data: BatchDeleteRequest,
    request: Request,
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
        access = resolve_project_access(db, uid, current_user.id)
        if access is None:
            continue
        project = access.project
        with audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="project.delete",
            intent=AuditIntent(
                project_id=project.id,
                action="project.batch_delete",
                resource_type="project",
                resource_id=str(project.id),
            ),
            allowed_changes=set(),
        ):
            db.query(TrainingJob).filter(TrainingJob.project_id == project.id).delete()
            db.query(Experiment).filter(Experiment.project_id == project.id).delete()
            db.query(Dataset).filter(Dataset.project_id == project.id).update({"project_id": None})
            db.query(OrchestrationApp).filter(OrchestrationApp.project_id == project.id).update({"project_id": None})
            db.delete(project)
        deleted += 1
    return {"deleted": deleted}
