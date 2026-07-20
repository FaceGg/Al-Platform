from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.workflow import Workflow, WorkflowEdge, WorkflowNode
from app.models.workflow_version import WorkflowVersion
from app.api.project_security import audit_service, resolve_workflow_access
from app.services.audit import AuditIntent


router = APIRouter(prefix="/api/workflows", tags=["workflow_versions"])
PROJECT_WRITE_ACTIONS = {
    "POST /api/workflows/{workflow_id}/publish": "workflow.publish",
    "POST /api/workflows/{workflow_id}/versions/{version_number}/restore": "workflow.restore",
}


def _get_workflow(db: Session, workflow_id: str) -> Workflow:
    workflow = db.query(Workflow).filter(Workflow.id == UUID(workflow_id)).first()
    if workflow is None:
        raise HTTPException(404, "Workflow not found")
    return workflow


def _snapshot(db: Session, workflow: Workflow) -> tuple[list[dict], list[dict]]:
    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).all()
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).all()
    node_data = [{
        "id": str(node.id),
        "operator_id": node.operator_id,
        "label": node.label or "",
        "position": {"x": node.position_x, "y": node.position_y},
        "params": node.params or {},
    } for node in nodes]
    edge_data = [{
        "id": str(edge.id),
        "source": str(edge.source_node_id),
        "source_port": edge.source_port or "",
        "target": str(edge.target_node_id),
        "target_port": edge.target_port or "",
    } for edge in edges]
    return node_data, edge_data


def _serialize(version: WorkflowVersion, include_snapshot: bool = False) -> dict:
    result = {
        "id": str(version.id),
        "workflow_id": str(version.workflow_id),
        "version": version.version,
        "name": version.name,
        "description": version.description or "",
        "published_by": str(version.published_by) if version.published_by else None,
        "published_at": version.published_at.isoformat() if version.published_at else None,
    }
    if include_snapshot:
        result["nodes"] = version.nodes_snapshot or []
        result["edges"] = version.edges_snapshot or []
    return result


@router.post("/{workflow_id}/publish", status_code=201)
def publish_workflow(
    workflow_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow, access = resolve_workflow_access(db, workflow_id, current_user.id)
    current = db.query(func.max(WorkflowVersion.version)).filter(
        WorkflowVersion.workflow_id == workflow.id,
    ).scalar() or 0
    nodes, edges = _snapshot(db, workflow)
    version = WorkflowVersion(
        workflow_id=workflow.id,
        version=current + 1,
        name=workflow.name,
        description=workflow.description or "",
        nodes_snapshot=nodes,
        edges_snapshot=edges,
        published_by=current_user.id,
    )
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="resource.update",
        intent=AuditIntent(
            project_id=workflow.project_id,
            action="workflow.publish",
            resource_type="workflow",
            resource_id=str(workflow.id),
            changes={"version": version.version},
        ),
        allowed_changes={"version"},
    ):
        db.add(version)
    db.refresh(version)
    return _serialize(version, include_snapshot=True)


@router.get("/{workflow_id}/versions")
def list_versions(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow, _ = resolve_workflow_access(db, workflow_id, current_user.id)
    versions = db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == workflow.id,
    ).order_by(WorkflowVersion.version.desc()).all()
    return {"items": [_serialize(version) for version in versions], "total": len(versions)}


@router.get("/{workflow_id}/versions/{version_number}")
def get_version(
    workflow_id: str,
    version_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow, _ = resolve_workflow_access(db, workflow_id, current_user.id)
    version = db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == workflow.id,
        WorkflowVersion.version == version_number,
    ).first()
    if version is None:
        raise HTTPException(404, "Workflow version not found")
    return _serialize(version, include_snapshot=True)


@router.delete("/{workflow_id}/versions/{version_number}", status_code=204)
def delete_version(
    workflow_id: str,
    version_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = _get_workflow(db, workflow_id)
    version = db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == workflow.id,
        WorkflowVersion.version == version_number,
    ).first()
    if version is None:
        raise HTTPException(404, "Workflow version not found")
    db.delete(version)
    db.commit()


@router.post("/{workflow_id}/versions/{version_number}/restore")
def restore_version(
    workflow_id: str,
    version_number: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow, access = resolve_workflow_access(db, workflow_id, current_user.id)
    version = db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == workflow.id,
        WorkflowVersion.version == version_number,
    ).first()
    if version is None:
        raise HTTPException(404, "Workflow version not found")

    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="resource.update",
        intent=AuditIntent(
            project_id=workflow.project_id,
            action="workflow.restore",
            resource_type="workflow",
            resource_id=str(workflow.id),
            changes={"version": version.version},
        ),
        allowed_changes={"version"},
    ):
        db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).delete()
        db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).delete()
        db.flush()
        node_ids = {}
        for item in version.nodes_snapshot or []:
            node = WorkflowNode(
                workflow_id=workflow.id,
                operator_id=item["operator_id"],
                label=item.get("label", ""),
                position_x=item.get("position", {}).get("x", 0),
                position_y=item.get("position", {}).get("y", 0),
                params=item.get("params", {}),
            )
            db.add(node)
            db.flush()
            node_ids[item["id"]] = node.id
        for item in version.edges_snapshot or []:
            db.add(WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=node_ids[item["source"]],
                source_port=item.get("source_port", ""),
                target_node_id=node_ids[item["target"]],
                target_port=item.get("target_port", ""),
            ))
        workflow.name = version.name
        workflow.description = version.description or ""
    return {"message": "Workflow version restored", "version": version.version}
