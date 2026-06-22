import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.database import get_db, SessionLocal
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.run import WorkflowRun, NodeRun
from app.models.user import User
from app.schemas.run import RunResponse
from app.api.auth import get_current_user
from app.engine.dag_executor import DAGExecutor
from app.engine.registry import OperatorRegistry
from app.websocket.manager import manager
import asyncio
import logging

logger = logging.getLogger(__name__)
# Main event loop (captured at import time in main thread)
_main_loop = None
try:
    _main_loop = asyncio.get_event_loop()
except RuntimeError:
    pass

router = APIRouter(tags=["runs"])


def _broadcast_from_thread(loop, run_id: str, payload: dict):
    """Thread-safe broadcast to WebSocket clients."""
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
            workflow_run.finished_at = datetime.utcnow()
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

        def status_callback(run_id: str, node_id: str, status: str, result: dict = None):
            """Called by DAG executor for each node status change."""
            try:
                nr = NodeRun(
                    run_id=workflow_run.id,
                    node_id=uuid.UUID(node_id),
                    status=status,
                    result=result,
                    started_at=datetime.utcnow() if status == "running" else None,
                    finished_at=datetime.utcnow() if status in ("completed", "failed") else None,
                )
                db.add(nr)
                db.commit()
            except Exception:
                db.rollback()

            payload = {"type": "node_status", "node_id": node_id, "status": status, "run_id": run_id}
            if result:
                payload["result"] = result
            _broadcast_from_thread(main_loop, run_id, payload)

        workflow_run.started_at = datetime.utcnow()
        workflow_run.status = "running"
        db.commit()

        _broadcast_from_thread(main_loop, run_id, {
            "type": "node_status", "node_id": "__wf__", "status": "running", "run_id": run_id,
        })

        result = executor.execute(run_id, status_callback)

        workflow_run.status = "completed"
        workflow_run.finished_at = datetime.utcnow()
        db.commit()

        _broadcast_from_thread(main_loop, run_id, {
            "type": "run_completed", "run_id": run_id, "status": "completed",
            "result": {"message": "Workflow execution completed"}
        })

    except Exception as e:
        logger.exception(f"Workflow {workflow_run_id} failed: {e}")
        try:
            wr = db.query(WorkflowRun).filter(WorkflowRun.id == uuid.UUID(workflow_run_id)).first()
            if wr:
                wr.status = "failed"
                wr.error_message = str(e)
                wr.finished_at = datetime.utcnow()
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

    workflow_run = WorkflowRun(
        workflow_id=uuid.UUID(workflow_id),
        status="pending",
        triggered_by=current_user.id,
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


@router.websocket("/ws/runs/{run_id}")
async def run_websocket(websocket: WebSocket, run_id: str):
    await manager.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(run_id, websocket)



