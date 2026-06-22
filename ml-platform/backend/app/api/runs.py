import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.models.run import WorkflowRun, NodeRun
from app.models.user import User
from app.schemas.run import RunResponse
from app.api.auth import get_current_user
from app.engine.dag_executor import DAGExecutor
from app.engine.registry import OperatorRegistry
from app.websocket.manager import manager

router = APIRouter(tags=["runs"])


def _run_workflow(workflow_run: WorkflowRun, db: Session):
    """Execute workflow in background and update run status."""
    try:
        run_id = str(workflow_run.id)
        workflow = db.query(Workflow).filter(Workflow.id == workflow_run.workflow_id).first()
        if not workflow:
            raise RuntimeError("Workflow not found")

        nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).all()
        edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).all()

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

        def status_callback(run_id: str, node_id: str, status: str):
            nonlocal db
            try:
                nr = NodeRun(
                    run_id=workflow_run.id,
                    node_id=uuid.UUID(node_id),
                    status=status,
                    started_at=datetime.utcnow() if status in ("running",) else None,
                    finished_at=datetime.utcnow() if status in ("completed", "failed") else None,
                )
                db.add(nr)
                db.commit()

                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(manager.broadcast(run_id, {"type": "node_status", "node_id": node_id, "status": status, "run_id": run_id}))
                except RuntimeError:
                    pass
            except Exception:
                db.rollback()

        workflow_run.started_at = datetime.utcnow()
        workflow_run.status = "running"
        db.commit()

        status_callback(run_id, "__workflow__", "running")

        result = executor.execute(run_id, status_callback)

        workflow_run.status = "completed"
        workflow_run.finished_at = datetime.utcnow()
        db.commit()

        status_callback(run_id, "__workflow__", "completed")

    except Exception as e:
        try:
            workflow_run.status = "failed"
            workflow_run.error_message = str(e)
            workflow_run.finished_at = datetime.utcnow()
            db.commit()
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(manager.broadcast(str(workflow_run.id), {"type": "run_completed", "run_id": str(workflow_run.id), "status": "failed", "error": str(e)}))
            except RuntimeError:
                pass
        except Exception:
            pass


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

    import threading
    thread = threading.Thread(target=_run_workflow, args=(workflow_run, db), daemon=True)
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
