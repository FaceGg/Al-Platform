"""Central project role resolution and permission enforcement."""

from dataclasses import dataclass
from enum import Enum

from sqlalchemy import and_, or_

from app.models.access import ProjectMember
from app.models.project import Project


class ProjectRole(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    OPERATOR = "operator"
    VIEWER = "viewer"


PERMISSIONS = frozenset({
    "project.read",
    "project.update",
    "project.delete",
    "member.manage",
    "resource.create",
    "resource.update",
    "resource.delete",
    "execution.operate",
    "schedule.manage",
    "schedule.operate",
    "audit.read",
    "model.register",
    "model.approve",
    "deployment.create",
    "inference.operate",
    "notification.read",
    "notification.manage",
})

ROLE_PERMISSIONS = {
    ProjectRole.OWNER: PERMISSIONS,
    ProjectRole.EDITOR: frozenset({
        "project.read",
        "resource.create",
        "resource.update",
        "resource.delete",
        "execution.operate",
        "schedule.manage",
        "schedule.operate",
        "model.register",
        "model.approve",
        "deployment.create",
        "inference.operate",
        "notification.read",
        "notification.manage",
    }),
    ProjectRole.OPERATOR: frozenset({
        "project.read",
        "execution.operate",
        "schedule.operate",
        "inference.operate",
        "notification.read",
    }),
    ProjectRole.VIEWER: frozenset({"project.read", "notification.read"}),
}


class ProjectAccessError(Exception):
    def __init__(self, code: str, *, hidden: bool):
        super().__init__(code)
        self.code = code
        self.hidden = hidden


@dataclass(frozen=True)
class ProjectAccess:
    project: Project
    role: ProjectRole


class ProjectAccessService:
    def resolve(self, db, project_id, user_id) -> ProjectAccess | None:
        project = db.query(Project).filter(Project.id == project_id).first()
        if project is None:
            return None
        if project.owner_id == user_id:
            return ProjectAccess(project=project, role=ProjectRole.OWNER)
        membership = db.query(ProjectMember).filter(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user_id,
        ).first()
        if membership is None:
            return None
        return ProjectAccess(
            project=project,
            role=ProjectRole(membership.role),
        )

    def require(self, db, project_id, user_id, permission: str) -> ProjectAccess:
        if permission not in PERMISSIONS:
            raise ValueError(f"Unknown project permission: {permission}")
        access = self.resolve(db, project_id, user_id)
        if access is None:
            raise ProjectAccessError("PROJECT_NOT_FOUND", hidden=True)
        if permission not in ROLE_PERMISSIONS[access.role]:
            raise ProjectAccessError("PROJECT_PERMISSION_DENIED", hidden=False)
        return access

    @staticmethod
    def accessible_project_query(db, user_id):
        return (
            db.query(Project)
            .outerjoin(
                ProjectMember,
                and_(
                    ProjectMember.project_id == Project.id,
                    ProjectMember.user_id == user_id,
                ),
            )
            .filter(or_(
                Project.owner_id == user_id,
                ProjectMember.user_id == user_id,
            ))
            .distinct()
        )
