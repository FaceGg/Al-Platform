import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload
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

# Tables whose rows outlive the project and are kept with project_id=NULL
# (legacy/global records): the project FK is nullable on all of them.
_PROJECT_DETACH_TABLES = {"datasets", "orchestration_apps", "audit_events"}


def _project_deletion_clause(table, project_table, project_id, dependents, broken, memo):
    """Build the WHERE clause selecting this table's rows owned by the project.

    Tables with a direct projects FK filter on it; transitive tables delete
    the rows whose parent rows are being deleted. Broken (cycle-detached)
    edges are ignored because those references were already nulled out.
    """
    if table in memo:
        return memo[table]
    direct = next((fk for fk in table.foreign_keys if fk.column.table is project_table), None)
    if direct is not None:
        clause = direct.parent == project_id
    else:
        alternatives = []
        for fk in table.foreign_keys:
            parent = fk.column.table
            if parent is table or parent not in dependents:
                continue
            if (table.name, fk.parent.name) in broken:
                continue
            parent_pk = list(parent.primary_key)
            if len(parent_pk) != 1:
                raise RuntimeError(f"composite primary key on {parent.name}")
            parent_clause = _project_deletion_clause(parent, project_table, project_id, dependents, broken, memo)
            alternatives.append(fk.parent.in_(select(parent_pk[0]).where(parent_clause)))
        if not alternatives:
            raise RuntimeError(f"no deletion path resolves {table.name}")
        clause = or_(*alternatives) if len(alternatives) > 1 else alternatives[0]
    memo[table] = clause
    return clause


def _strongly_connected_groups(dependents, edges):
    """Tarjan SCC over the dependent-table FK graph."""
    index = {}
    low = {}
    on_stack = set()
    stack = []
    groups = []
    counter = [0]

    def visit(table):
        index[table] = low[table] = counter[0]
        counter[0] += 1
        stack.append(table)
        on_stack.add(table)
        for parent, _column in edges.get(table, set()):
            if parent not in index:
                visit(parent)
                low[table] = min(low[table], low[parent])
            elif parent in on_stack:
                low[table] = min(low[table], index[parent])
        if low[table] == index[table]:
            group = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                group.append(member)
                if member is table:
                    break
            groups.append(group)

    for table in sorted(dependents, key=lambda item: item.name):
        if table not in index:
            visit(table)
    return groups


def _purge_project(db: Session, project: Project) -> None:
    """Hard-delete every row transitively referencing the project, children first.

    The cleanup used to be a hand-written list of a few tables, so any newer
    project-scoped table (artifacts, annotation tasks, dataset versions, ...)
    broke DELETE with a foreign key error. The plan is derived from SQLAlchemy
    metadata at call time so new project-scoped tables are picked up
    automatically. Circular FK groups (e.g. model_library <-> training_jobs)
    are broken by nulling the nullable in-group references of the rows about
    to be deleted; a non-nullable in-group reference is a schema error. Core
    statements bypass ORM event guards (e.g. frozen dataset rows) — deleting
    the project is the explicit hard boundary. Storage files behind deleted
    artifacts are left orphaned on the storage backend.
    """
    from app.database import Base
    project_table = Project.__table__
    project_id = project.id

    references = {}
    for table in Base.metadata.tables.values():
        parents = {fk.column.table for fk in table.foreign_keys if fk.column.table is not table}
        if parents:
            references[table] = parents

    dependents = {table for table, parents in references.items() if project_table in parents}
    while True:
        discovered = {
            table for table, parents in references.items()
            if table not in dependents and parents & dependents
        }
        if not discovered:
            break
        dependents |= discovered

    edges = {
        table: {
            (fk.column.table, fk.parent)
            for fk in table.foreign_keys
            if fk.column.table is not table and fk.column.table in dependents
        }
        for table in dependents
    }

    broken = set()
    for group in _strongly_connected_groups(dependents, edges):
        if len(group) < 2:
            continue
        members = set(group)
        for table in group:
            for parent, column in edges[table]:
                if parent not in members:
                    continue
                if not column.nullable:
                    raise RuntimeError(
                        f"cannot break circular project reference on {table.name}.{column.name}"
                    )
                broken.add((table.name, column.name))

    for table in dependents:
        for parent, column in list(edges[table]):
            if (table.name, column.name) in broken:
                edges[table].discard((parent, column))

    ordered = []
    pending = set(dependents)
    # children first: a table is ready once every dependent table referencing
    # it has already been deleted, so no dangling parent rows remain when the
    # deletion clause subqueries are evaluated
    children = {table: set() for table in dependents}
    for table in dependents:
        for parent, _column in edges[table]:
            children[parent].add(table)
    while pending:
        ready = sorted(
            (table for table in pending if not (children[table] & pending)),
            key=lambda item: item.name,
        )
        if not ready:
            raise RuntimeError("circular foreign keys among project dependents")
        ordered.extend(ready)
        pending.difference_update(ready)

    memo: dict = {}
    for table in ordered:
        direct = next((fk for fk in table.foreign_keys if fk.column.table is project_table), None)
        if table.name in _PROJECT_DETACH_TABLES and direct is not None:
            db.execute(
                table.update().where(direct.parent == project_id).values({direct.parent.name: None})
            )
            continue
        clause = _project_deletion_clause(table, project_table, project_id, dependents, broken, memo)
        db.execute(table.delete().where(clause))
    db.flush()


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
    projects = (
        service.accessible_project_query(db, current_user.id)
        .options(joinedload(Project.owner))
        .order_by(ordering)
        .all()
    )
    items = [{
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "owner_id": project.owner_id,
        "creator_username": project.owner.username if project.owner is not None else None,
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
    access = require_project_access(db, project_id, current_user.id, "project.read")
    return ProjectResponse.model_validate(access.project).model_copy(
        update={"project_role": access.role.value},
    )


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
        _purge_project(db, project)
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
            _purge_project(db, project)
            db.delete(project)
        deleted += 1
    return {"deleted": deleted}
