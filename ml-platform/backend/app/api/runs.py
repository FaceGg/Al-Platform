import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.run import WorkflowRun
from app.models.workflow_version import WorkflowVersion
from app.models.user import User
from app.schemas.run import RunResponse
from app.api.auth import get_current_user
from app.engine.dag_executor import DAGExecutor
from app.engine.run_state import TERMINAL_RUN_STATUSES, transition_run_status
from app.events.local import LocalRunEventPublisher
from app.services.workflow_execution import execute_workflow_run
from app.tasks.dispatcher import CeleryTaskDispatcher, LocalTaskDispatcher, TaskDispatcher
from app.websocket.manager import manager
from app.api.project_security import audit_service, resolve_run_access, resolve_workflow_access
from app.services.audit import AuditIntent
import asyncio
import logging

logger = logging.getLogger(__name__)
_main_loop = None

router = APIRouter(tags=["runs"])
PROJECT_WRITE_ACTIONS = {
    "POST /api/workflows/{workflow_id}/run": "workflow_run.start",
    "POST /api/runs/{run_id}/cancel": "workflow_run.cancel",
}


def get_task_dispatcher() -> TaskDispatcher:
    if settings.task_backend == "celery":
        from app.tasks.workflow_tasks import execute_workflow_task

        return CeleryTaskDispatcher(execute_workflow_task)
    return LocalTaskDispatcher(lambda run_id: _run_workflow(run_id, _main_loop))


def _snapshot_signature(nodes: list[dict], edges: list[dict]) -> dict:
    node_index = {str(node["id"]): index for index, node in enumerate(nodes)}
    normalized_nodes = [{
        "operator_id": node.get("operator_id", ""),
        "label": node.get("label", ""),
        "params": node.get("params", {}),
        "position": node.get("position", {}),
    } for node in nodes]
    normalized_edges = sorted([{
        "source": node_index.get(str(edge.get("source"))),
        "source_port": edge.get("source_port", ""),
        "target": node_index.get(str(edge.get("target"))),
        "target_port": edge.get("target_port", ""),
    } for edge in edges], key=lambda edge: (
        edge["source"] if edge["source"] is not None else -1,
        edge["target"] if edge["target"] is not None else -1,
        edge["source_port"], edge["target_port"],
    ))
    return {"nodes": normalized_nodes, "edges": normalized_edges}


def _matching_workflow_version(db: Session, workflow_id, nodes, edges) -> int | None:
    live_nodes = [{
        "id": str(node.id), "operator_id": node.operator_id, "label": node.label or "",
        "params": node.params or {},
        "position": {"x": node.position_x, "y": node.position_y},
    } for node in nodes]
    live_edges = [{
        "source": str(edge.source_node_id), "source_port": edge.source_port or "",
        "target": str(edge.target_node_id), "target_port": edge.target_port or "",
    } for edge in edges]
    live_signature = _snapshot_signature(live_nodes, live_edges)
    versions = db.query(WorkflowVersion).filter(
        WorkflowVersion.workflow_id == workflow_id,
    ).order_by(WorkflowVersion.version.desc()).all()
    for version in versions:
        if _snapshot_signature(
            version.nodes_snapshot or [], version.edges_snapshot or [],
        ) == live_signature:
            return version.version
    return None


def _broadcast_from_thread(loop, run_id: str, payload: dict):
    """Thread-safe broadcast to WebSocket clients."""
    if loop is None or loop.is_closed():
        return
    try:
        asyncio.run_coroutine_threadsafe(manager.broadcast(run_id, payload), loop)
    except Exception:
        pass


def _run_workflow(workflow_run_id: str, main_loop):
    publisher = LocalRunEventPublisher(
        lambda run_id, payload: _broadcast_from_thread(
            main_loop,
            run_id,
            payload,
        ),
    )
    execute_workflow_run(workflow_run_id, event_publisher=publisher)


@router.post("/api/workflows/{workflow_id}/run", status_code=201)
def start_run(
    workflow_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    dispatcher: TaskDispatcher = Depends(get_task_dispatcher),
):
    workflow, access = resolve_workflow_access(db, workflow_id, current_user.id)
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="execution.operate",
        intent=AuditIntent(
            project_id=workflow.project_id,
            action="workflow_run.start",
            resource_type="workflow_run",
            changes={"workflow_id": str(workflow.id)},
        ),
        allowed_changes={"workflow_id"},
    ):
        nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).all()
        edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).all()
        if not nodes:
            raise HTTPException(400, {
                "code": "WORKFLOW_EMPTY", "message": "Workflow must contain at least one node",
            })
        validation_nodes = [{
            "id": str(node.id), "operator_id": node.operator_id,
            "label": node.label or "", "params": node.params or {},
        } for node in nodes]
        validation_edges = [{
            "source": str(edge.source_node_id), "target": str(edge.target_node_id),
            "source_port": edge.source_port or "", "target_port": edge.target_port or "",
        } for edge in edges]
        validation_errors = DAGExecutor(validation_nodes, validation_edges).validate()
        if validation_errors:
            raise HTTPException(400, {
                "code": "WORKFLOW_INVALID", "message": "Workflow validation failed",
                "errors": validation_errors,
            })

        workflow_run = WorkflowRun(
            workflow_id=workflow.id,
            status="pending",
            triggered_by=current_user.id,
            workflow_version=_matching_workflow_version(db, workflow.id, nodes, edges),
            workflow_snapshot={"nodes": validation_nodes, "edges": validation_edges},
            logs=[{"level": "info", "message": "Run created"}],
        )
        db.add(workflow_run)
        db.flush()
    db.refresh(workflow_run)

    try:
        dispatcher.enqueue_workflow(str(workflow_run.id))
    except Exception as error:
        logger.exception("Failed to enqueue workflow run %s", workflow_run.id)

    return {"run_id": str(workflow_run.id), "status": workflow_run.status}


@router.get("/api/runs/{run_id}", response_model=RunResponse)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run, _ = resolve_run_access(db, run_id, current_user.id)
    return run


@router.post("/api/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    dispatcher: TaskDispatcher = Depends(get_task_dispatcher),
):
    run, access = resolve_run_access(db, run_id, current_user.id)
    with audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="execution.operate",
        intent=AuditIntent(
            project_id=run.workflow.project_id,
            action="workflow_run.cancel",
            resource_type="workflow_run",
            resource_id=str(run.id),
            changes={"previous_status": run.status},
        ),
        allowed_changes={"previous_status"},
    ):
        if run.status not in TERMINAL_RUN_STATUSES and run.status != "cancel_requested":
            run.status = transition_run_status(run.status, "cancel_requested")
            run.cancel_requested_at = datetime.now(timezone.utc)
            run.logs = [*(run.logs or []), {"level": "info", "message": "Cancellation requested"}]
    task_id = run.task_id
    if task_id:
        try:
            dispatcher.cancel(task_id, terminate=True)
        except Exception:
            logger.exception("Failed to revoke workflow task %s", task_id)
    return {"run_id": str(run.id), "status": run.status}


@router.websocket("/ws/runs/{run_id}")
async def run_websocket(websocket: WebSocket, run_id: str):
    await manager.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(run_id, websocket)



