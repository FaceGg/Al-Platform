import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.database import get_db, SessionLocal
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.run import WorkflowRun, NodeRun
from app.models.workflow_version import WorkflowVersion
from app.models.user import User
from app.schemas.run import RunResponse
from app.api.auth import get_current_user
from app.engine.dag_executor import DAGExecutor
from app.engine.registry import OperatorRegistry
from app.engine.run_control import RunCancelled, RunControl
from app.engine.run_state import TERMINAL_RUN_STATUSES, transition_run_status
from app.websocket.manager import manager
import asyncio
import logging

logger = logging.getLogger(__name__)
_main_loop = None

router = APIRouter(tags=["runs"])


def _duration_ms(started_at: datetime | None, finished_at: datetime) -> int | None:
    if started_at is None:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    return int((finished_at - started_at).total_seconds() * 1000)


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
    """Execute workflow in background using a fresh DB session."""
    import time
    time.sleep(0.5)  # Wait for frontend WebSocket to connect
    db = SessionLocal()
    try:
        workflow_run = db.query(WorkflowRun).filter(WorkflowRun.id == uuid.UUID(workflow_run_id)).first()
        if not workflow_run:
            return

        run_id = workflow_run_id
        workflow = db.query(Workflow).filter(Workflow.id == workflow_run.workflow_id).first()
        if not workflow:
            raise RuntimeError("Workflow not found")

        nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).all()
        edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).all()

        if not nodes:
            _broadcast_from_thread(main_loop, run_id, {
                "type": "run_completed", "run_id": run_id,
                "status": "failed", "error": "No nodes in workflow"
            })
            workflow_run.status = "failed"
            workflow_run.error_message = "No nodes in workflow"
            workflow_run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        dag_nodes = []
        for n in nodes:
            dag_nodes.append({
                "id": str(n.id),
                "operator_id": n.operator_id,
                "label": n.label or "",
                "params": n.params or {},
            })

        dag_edges = []
        for e in edges:
            dag_edges.append({
                "source": str(e.source_node_id),
                "target": str(e.target_node_id),
                "source_port": e.source_port or "",
                "target_port": e.target_port or "",
            })

        executor = DAGExecutor(dag_nodes, dag_edges)

        def status_callback(
            run_id: str, node_id: str, status: str, result: dict = None, metadata: dict = None,
        ):
            """Called by DAG executor for each node status change."""
            try:
                attempt = int((metadata or {}).get("attempt", 1))
                nr = db.query(NodeRun).filter(
                    NodeRun.run_id == workflow_run.id,
                    NodeRun.node_id == uuid.UUID(node_id),
                    NodeRun.attempt == attempt,
                ).first()
                if nr is None:
                    nr = NodeRun(
                        run_id=workflow_run.id,
                        node_id=uuid.UUID(node_id),
                        attempt=attempt,
                        status=status,
                        started_at=datetime.now(timezone.utc) if status == "running" else None,
                    )
                    db.add(nr)
                nr.status = status
                nr.result = result
                if result and result.get("error"):
                    nr.error_message = result["error"]
                    nr.error_code = result.get("error_code")
                    nr.error_details = {"node_id": node_id, "attempt": attempt}
                if status in ("completed", "failed", "timed_out", "cancelled", "skipped"):
                    nr.finished_at = datetime.now(timezone.utc)
                    nr.duration_ms = _duration_ms(nr.started_at, nr.finished_at)
                db.commit()
            except Exception:
                db.rollback()

            payload = {
                "type": "node_status", "node_id": node_id, "status": status,
                "run_id": run_id, "attempt": int((metadata or {}).get("attempt", 1)),
            }
            if result:
                payload["result"] = result
            _broadcast_from_thread(main_loop, run_id, payload)

        workflow_run.started_at = datetime.now(timezone.utc)
        workflow_run.status = "running"
        db.commit()

        _broadcast_from_thread(main_loop, run_id, {
            "type": "node_status", "node_id": "__wf__", "status": "running", "run_id": run_id,
        })

        def cancel_requested():
            with SessionLocal() as control_db:
                status = control_db.query(WorkflowRun.status).filter(
                    WorkflowRun.id == workflow_run.id,
                ).scalar()
                return status == "cancel_requested"

        result = executor.execute(run_id, status_callback, RunControl(cancel_requested))

        workflow_run.status = "completed"
        workflow_run.finished_at = datetime.now(timezone.utc)
        db.commit()

        _broadcast_from_thread(main_loop, run_id, {
            "type": "run_completed", "run_id": run_id, "status": "completed",
            "result": {"message": "Workflow execution completed"}
        })

    except RunCancelled:
        try:
            wr = db.query(WorkflowRun).filter(WorkflowRun.id == uuid.UUID(workflow_run_id)).first()
            if wr:
                wr.status = "cancelled"
                wr.cancelled_at = datetime.now(timezone.utc)
                wr.finished_at = wr.cancelled_at
                db.commit()
            _broadcast_from_thread(main_loop, workflow_run_id, {
                "type": "run_completed", "run_id": workflow_run_id, "status": "cancelled",
            })
        except Exception:
            db.rollback()
    except Exception as e:
        logger.exception(f"Workflow {workflow_run_id} failed: {e}")
        try:
            wr = db.query(WorkflowRun).filter(WorkflowRun.id == uuid.UUID(workflow_run_id)).first()
            if wr:
                wr.status = "failed"
                wr.error_message = str(e)
                wr.error_code = "NODE_TIMED_OUT" if isinstance(e.__cause__, TimeoutError) else "NODE_EXECUTION_FAILED"
                wr.error_details = {"exception_type": type(e.__cause__ or e).__name__}
                wr.logs = [*(wr.logs or []), {
                    "level": "error", "message": str(e), "code": wr.error_code,
                }]
                wr.finished_at = datetime.now(timezone.utc)
                db.commit()
            _broadcast_from_thread(main_loop, workflow_run_id, {
                "type": "run_completed", "run_id": workflow_run_id,
                "status": "failed", "error": str(e)
            })
        except Exception:
            pass
    finally:
        db.close()


@router.post("/api/workflows/{workflow_id}/run", status_code=201)
def start_run(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(Workflow.id == uuid.UUID(workflow_id)).first()
    if not workflow:
        raise HTTPException(404, "Workflow not found")

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
        workflow_id=uuid.UUID(workflow_id),
        status="pending",
        triggered_by=current_user.id,
        workflow_version=_matching_workflow_version(db, workflow.id, nodes, edges),
        workflow_snapshot={"nodes": validation_nodes, "edges": validation_edges},
        logs=[{"level": "info", "message": "Run created"}],
    )
    db.add(workflow_run)
    db.commit()
    db.refresh(workflow_run)

    # Capture event loop from main thread for WebSocket broadcast
    main_loop = _main_loop

    import threading
    thread = threading.Thread(
        target=_run_workflow,
        args=(str(workflow_run.id), main_loop),
        daemon=True,
    )
    thread.start()

    return {"run_id": str(workflow_run.id), "status": workflow_run.status}


@router.get("/api/runs/{run_id}", response_model=RunResponse)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = db.query(WorkflowRun).filter(WorkflowRun.id == uuid.UUID(run_id)).first()
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/api/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = db.query(WorkflowRun).filter(WorkflowRun.id == uuid.UUID(run_id)).first()
    if run is None:
        raise HTTPException(404, "Run not found")
    if run.status in TERMINAL_RUN_STATUSES:
        return {"run_id": str(run.id), "status": run.status}
    if run.status != "cancel_requested":
        run.status = transition_run_status(run.status, "cancel_requested")
        run.cancel_requested_at = datetime.now(timezone.utc)
        run.logs = [*(run.logs or []), {"level": "info", "message": "Cancellation requested"}]
        db.commit()
    return {"run_id": str(run.id), "status": run.status}


@router.websocket("/ws/runs/{run_id}")
async def run_websocket(websocket: WebSocket, run_id: str):
    await manager.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(run_id, websocket)



