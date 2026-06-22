from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.user import User
from app.schemas.workflow import WorkflowSave
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/workflows", tags=["workflows_direct"])


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
    wf = db.query(Workflow).filter(Workflow.id == UUID(workflow_id)).first()
    if not wf:
        raise HTTPException(404, "Workflow not found")
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    wf = db.query(Workflow).filter(Workflow.id == UUID(workflow_id)).first()
    if not wf:
        raise HTTPException(404, "Workflow not found")
    if data.name:
        wf.name = data.name

    # Delete existing nodes and edges
    db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == UUID(workflow_id)).delete()
    db.query(WorkflowNode).filter(WorkflowNode.workflow_id == UUID(workflow_id)).delete()
    db.flush()

    # Create new nodes, track client-id -> UUID mapping
    id_map: dict[str, UUID] = {}
    for n in data.nodes:
        node = WorkflowNode(
            workflow_id=UUID(workflow_id),
            operator_id=n.operator_id,
            label=n.label,
            position_x=n.position.x,
            position_y=n.position.y,
            params=n.params or {},
        )
        db.add(node)
        db.flush()
        id_map[n.id] = node.id

    # Create edges using id_map for resolution
    for e in data.edges:
        edge = WorkflowEdge(
            workflow_id=UUID(workflow_id),
            source_node_id=_to_uuid(e.source, id_map),
            source_port=e.source_port,
            target_node_id=_to_uuid(e.target, id_map),
            target_port=e.target_port,
        )
        db.add(edge)

    db.commit()
    return {"message": "Workflow saved"}
