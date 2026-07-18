"""HTTP adapters for centralized project authorization and auditing."""

import uuid

from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.models.run import WorkflowRun
from app.models.workflow import Workflow
from app.services.audit import AuditService
from app.services.project_access import ProjectAccessError, ProjectAccessService


def project_uuid(value) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(404, {"code": "PROJECT_NOT_FOUND"})


def access_error(error: ProjectAccessError):
    status = 404 if error.hidden else 403
    raise HTTPException(status, {"code": error.code, "message": str(error)})


def resolve_project_access(db, project_id, user_id):
    return ProjectAccessService().resolve(db, project_uuid(project_id), user_id)


def require_project_access(db, project_id, user_id, permission):
    try:
        return ProjectAccessService().require(
            db, project_uuid(project_id), user_id, permission,
        )
    except ProjectAccessError as error:
        access_error(error)


def resolve_workflow_access(db, workflow_id, user_id):
    try:
        workflow_uuid = uuid.UUID(str(workflow_id))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(404, "Workflow not found")
    workflow = db.query(Workflow).filter(Workflow.id == workflow_uuid).first()
    if workflow is None:
        raise HTTPException(404, "Workflow not found")
    access = ProjectAccessService().resolve(db, workflow.project_id, user_id)
    if access is None:
        access_error(ProjectAccessError("PROJECT_NOT_FOUND", hidden=True))
    return workflow, access


def require_workflow_access(db, workflow_id, user_id, permission):
    workflow, access = resolve_workflow_access(db, workflow_id, user_id)
    try:
        ProjectAccessService().require(db, workflow.project_id, user_id, permission)
    except ProjectAccessError as error:
        access_error(error)
    return workflow, access


def resolve_run_access(db, run_id, user_id):
    try:
        run_uuid = uuid.UUID(str(run_id))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(404, "Run not found")
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run_uuid).first()
    if run is None:
        raise HTTPException(404, "Run not found")
    access = ProjectAccessService().resolve(db, run.workflow.project_id, user_id)
    if access is None:
        access_error(ProjectAccessError("PROJECT_NOT_FOUND", hidden=True))
    return run, access


def audit_service(db) -> AuditService:
    return AuditService(sessionmaker(bind=db.get_bind()))
