from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.user import User
from app.schemas.workflow import WorkflowSave
from app.api.auth import get_current_user
from app.api.project_security import audit_service, resolve_workflow_access
from app.services.audit import AuditIntent

router = APIRouter(prefix="/api/workflows", tags=["workflows_direct"])
PROJECT_WRITE_ACTIONS = {
    "PUT /api/workflows/{workflow_id}": "workflow.update",
    "DELETE /api/workflows/{workflow_id}": "workflow.delete",
}


def _to_uuid(value: str, id_map: dict[str, UUID]) -> UUID:
    """Convert a client-side ID or UUID string to a UUID object using id_map."""
    # First try the id_map (client-side IDs like "n1", "node_xxx")
    if value in id_map:
        return id_map[value]
    # Try parsing as UUID directly (for server-generated UUID strings)
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(400, f"Invalid node reference: {value}")


@router.get("/{workflow_id}")
def get_workflow_direct(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    wf, _ = resolve_workflow_access(db, workflow_id, current_user.id)
    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == UUID(workflow_id)).all()
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == UUID(workflow_id)).all()
    return {
        "id": str(wf.id),
        "project_id": str(wf.project_id),
        "name": wf.name,
        "description": wf.description,
        "type": wf.type,
        "nodes": [
            {"id": str(n.id), "operator_id": n.operator_id, "label": n.label or "",
             "position_x": n.position_x, "position_y": n.position_y, "params": n.params or {}}
            for n in nodes
        ],
        "edges": [
            {"id": str(e.id), "source_node_id": str(e.source_node_id), "source_port": e.source_port or "output",
             "target_node_id": str(e.target_node_id), "target_port": e.target_port or "input"}
            for e in edges
        ],
    }


@router.put("/{workflow_id}")
def save_workflow_direct(
    workflow_id: str,
    data: WorkflowSave,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    wf, access = resolve_workflow_access(db, workflow_id, current_user.id)
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="resource.update",
        intent=AuditIntent(
            project_id=wf.project_id,
            action="workflow.update",
            resource_type="workflow",
            resource_id=str(wf.id),
            changes=data.model_dump(exclude_none=True),
        ),
        allowed_changes={"name", "description"},
    ):
        if data.name:
            wf.name = data.name
        if data.description is not None:
            wf.description = data.description

        db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf.id).delete()
        db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf.id).delete()
        db.flush()

        id_map: dict[str, UUID] = {}
        for n in data.nodes:
            node = WorkflowNode(
                workflow_id=wf.id,
                operator_id=n.operator_id,
                label=n.label,
                position_x=n.position.x,
                position_y=n.position.y,
                params=n.params or {},
            )
            db.add(node)
            db.flush()
            id_map[n.id] = node.id

        for e in data.edges:
            edge = WorkflowEdge(
                workflow_id=wf.id,
                source_node_id=_to_uuid(e.source, id_map),
                source_port=e.source_port,
                target_node_id=_to_uuid(e.target, id_map),
                target_port=e.target_port,
            )
            db.add(edge)

    return {"message": "Workflow saved"}


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow_direct(
    workflow_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    wf, access = resolve_workflow_access(db, workflow_id, current_user.id)
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="resource.delete",
        intent=AuditIntent(
            project_id=wf.project_id,
            action="workflow.delete",
            resource_type="workflow",
            resource_id=str(wf.id),
        ),
        allowed_changes=set(),
    ):
        db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf.id).delete()
        db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf.id).delete()
        db.delete(wf)
    return Response(status_code=204)
