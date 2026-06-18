from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.project import Project
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.user import User
from app.schemas.workflow import WorkflowCreate, WorkflowSave, WorkflowResponse, NodeResponse, EdgeResponse
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/projects", tags=["workflows"])


def _build_workflow_response(workflow: Workflow) -> WorkflowResponse:
    return WorkflowResponse(
        id=workflow.id,
        project_id=workflow.project_id,
        name=workflow.name,
        description=workflow.description,
        type=workflow.type,
        nodes=[NodeResponse.model_validate(n) for n in workflow.nodes],
        edges=[EdgeResponse.model_validate(e) for e in workflow.edges],
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


@router.get("/{project_id}/workflows")
def list_workflows(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id, Project.owner_id == current_user.id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    workflows = db.query(Workflow).filter(Workflow.project_id == project_id).all()
    return [{"id": str(w.id), "name": w.name, "description": w.description, "created_at": w.created_at.isoformat() if w.created_at else None} for w in workflows]


@router.post("/{project_id}/workflows", response_model=WorkflowResponse, status_code=201)
def create_workflow(
    project_id: str,
    data: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id, Project.owner_id == current_user.id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    workflow = Workflow(
        project_id=UUID(project_id),
        name=data.name,
        description=data.description,
        created_by=current_user.id,
    )
    db.add(workflow)
    db.flush()

    client_id_map = {}
    for node_data in data.nodes:
        node = WorkflowNode(
            workflow_id=workflow.id,
            operator_id=node_data.operator_id,
            label=node_data.label,
            position_x=node_data.position.x,
            position_y=node_data.position.y,
            params=node_data.params,
        )
        db.add(node)
        db.flush()
        client_id_map[node_data.id] = node.id

    for edge_data in data.edges:
        edge = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id=client_id_map.get(edge_data.source, UUID(edge_data.source)),
            source_port=edge_data.source_port,
            target_node_id=client_id_map.get(edge_data.target, UUID(edge_data.target)),
            target_port=edge_data.target_port,
        )
        db.add(edge)

    db.commit()
    db.refresh(workflow)
    return _build_workflow_response(workflow)


@router.get("/{project_id}/workflows/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(
        Workflow.id == workflow_id,
        Workflow.project_id == project_id,
    ).first()
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    return _build_workflow_response(workflow)


@router.put("/{project_id}/workflows/{workflow_id}", response_model=WorkflowResponse)
def save_workflow(
    project_id: str,
    workflow_id: str,
    data: WorkflowSave,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(
        Workflow.id == workflow_id,
        Workflow.project_id == project_id,
    ).first()
    if not workflow:
        raise HTTPException(404, "Workflow not found")

    if data.name is not None:
        workflow.name = data.name
    if data.description is not None:
        workflow.description = data.description

    # Delete existing nodes and edges
    db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).delete()
    db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).delete()
    db.flush()

    # Create new nodes and map client IDs
    client_id_map = {}
    for node_data in data.nodes:
        node = WorkflowNode(
            workflow_id=workflow.id,
            operator_id=node_data.operator_id,
            label=node_data.label,
            position_x=node_data.position.x,
            position_y=node_data.position.y,
            params=node_data.params,
        )
        db.add(node)
        db.flush()
        client_id_map[node_data.id] = node.id

    for edge_data in data.edges:
        edge = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id=client_id_map.get(edge_data.source, edge_data.source),
            source_port=edge_data.source_port,
            target_node_id=client_id_map.get(edge_data.target, edge_data.target),
            target_port=edge_data.target_port,
        )
        db.add(edge)

    db.commit()
    db.refresh(workflow)
    return _build_workflow_response(workflow)


@router.delete("/{project_id}/workflows/{workflow_id}", status_code=204)
def delete_workflow(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(
        Workflow.id == workflow_id,
        Workflow.project_id == project_id,
    ).first()
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    db.delete(workflow)
    db.commit()
