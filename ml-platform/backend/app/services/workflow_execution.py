"""Workflow execution shared by local threads and Celery workers."""

import logging
import uuid
from datetime import datetime, timezone

import app.operators  # noqa: F401 (register built-in operators in workers)
from app.database import SessionLocal
from app.engine.dag_executor import DAGExecutor
from app.engine.run_control import RunCancelled, RunControl
from app.events.base import NullRunEventPublisher, RunEventPublisher
from app.models.run import NodeRun, WorkflowRun
from app.models.workflow import Workflow, WorkflowEdge, WorkflowNode
from app.services.artifact_service import build_artifact_service


logger = logging.getLogger(__name__)


def _duration_ms(started_at: datetime | None, finished_at: datetime) -> int | None:
    if started_at is None:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    return int((finished_at - started_at).total_seconds() * 1000)


def execute_workflow_run(
    run_id: str,
    session_factory=SessionLocal,
    event_publisher: RunEventPublisher | None = None,
) -> None:
    """Load and execute one persisted workflow run."""
    publisher = event_publisher or NullRunEventPublisher()
    db = session_factory()
    try:
        workflow_run = db.query(WorkflowRun).filter(
            WorkflowRun.id == uuid.UUID(run_id),
        ).first()
        if workflow_run is None:
            raise RuntimeError("Workflow run not found")
        _execute_loaded_workflow(db, workflow_run, publisher, session_factory)
    finally:
        db.close()


def _execute_loaded_workflow(db, workflow_run, publisher, session_factory) -> None:
    run_id = str(workflow_run.id)
    try:
        workflow = db.query(Workflow).filter(
            Workflow.id == workflow_run.workflow_id,
        ).first()
        if workflow is None:
            raise RuntimeError("Workflow not found")

        nodes = db.query(WorkflowNode).filter(
            WorkflowNode.workflow_id == workflow.id,
        ).all()
        edges = db.query(WorkflowEdge).filter(
            WorkflowEdge.workflow_id == workflow.id,
        ).all()
        if not nodes:
            workflow_run.status = "failed"
            workflow_run.error_message = "No nodes in workflow"
            workflow_run.finished_at = datetime.now(timezone.utc)
            db.commit()
            publisher.publish(run_id, {
                "type": "run_completed",
                "status": "failed",
                "error": "No nodes in workflow",
            })
            return

        dag_nodes = [{
            "id": str(node.id),
            "operator_id": node.operator_id,
            "label": node.label or "",
            "params": node.params or {},
        } for node in nodes]
        dag_edges = [{
            "source": str(edge.source_node_id),
            "target": str(edge.target_node_id),
            "source_port": edge.source_port or "",
            "target_port": edge.target_port or "",
        } for edge in edges]
        executor = DAGExecutor(
            dag_nodes,
            dag_edges,
            artifact_service=build_artifact_service(db),
            project_id=str(workflow.project_id),
            workflow_id=str(workflow.id),
        )

        def status_callback(
            callback_run_id: str,
            node_id: str,
            status: str,
            result: dict | None = None,
            metadata: dict | None = None,
        ) -> None:
            attempt = int((metadata or {}).get("attempt", 1))
            try:
                node_run = db.query(NodeRun).filter(
                    NodeRun.run_id == workflow_run.id,
                    NodeRun.node_id == uuid.UUID(node_id),
                    NodeRun.attempt == attempt,
                ).first()
                if node_run is None:
                    node_run = NodeRun(
                        run_id=workflow_run.id,
                        node_id=uuid.UUID(node_id),
                        attempt=attempt,
                        status=status,
                        started_at=(
                            datetime.now(timezone.utc)
                            if status == "running"
                            else None
                        ),
                    )
                    db.add(node_run)
                node_run.status = status
                node_run.result = result
                if result and result.get("error"):
                    node_run.error_message = result["error"]
                    node_run.error_code = result.get("error_code")
                    node_run.error_details = {
                        "node_id": node_id,
                        "attempt": attempt,
                    }
                if status in {
                    "completed", "failed", "timed_out", "cancelled", "skipped",
                }:
                    node_run.finished_at = datetime.now(timezone.utc)
                    node_run.duration_ms = _duration_ms(
                        node_run.started_at,
                        node_run.finished_at,
                    )
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Failed to persist node status for run %s", run_id)

            payload = {
                "type": "node_status",
                "node_id": node_id,
                "status": status,
                "attempt": attempt,
            }
            if result:
                payload["result"] = result
            publisher.publish(callback_run_id, payload)

        workflow_run.started_at = workflow_run.started_at or datetime.now(timezone.utc)
        workflow_run.status = "running"
        db.commit()
        publisher.publish(run_id, {
            "type": "node_status",
            "node_id": "__wf__",
            "status": "running",
        })

        def cancel_requested() -> bool:
            with session_factory() as control_db:
                status = control_db.query(WorkflowRun.status).filter(
                    WorkflowRun.id == workflow_run.id,
                ).scalar()
                return status == "cancel_requested"

        executor.execute(run_id, status_callback, RunControl(cancel_requested))
        workflow_run.status = "completed"
        workflow_run.finished_at = datetime.now(timezone.utc)
        db.commit()
        publisher.publish(run_id, {
            "type": "run_completed",
            "status": "completed",
            "result": {"message": "Workflow execution completed"},
        })
    except RunCancelled:
        workflow_run.status = "cancelled"
        workflow_run.cancelled_at = datetime.now(timezone.utc)
        workflow_run.finished_at = workflow_run.cancelled_at
        db.commit()
        publisher.publish(run_id, {
            "type": "run_completed",
            "status": "cancelled",
        })
    except Exception as error:
        logger.exception("Workflow %s failed: %s", run_id, error)
        db.rollback()
        current_run = db.query(WorkflowRun).filter(
            WorkflowRun.id == workflow_run.id,
        ).first()
        if current_run is not None:
            cause = error.__cause__ or error
            current_run.status = "failed"
            current_run.error_message = str(error)
            current_run.error_code = (
                "NODE_TIMED_OUT"
                if isinstance(error.__cause__, TimeoutError)
                else "NODE_EXECUTION_FAILED"
            )
            current_run.error_details = {"exception_type": type(cause).__name__}
            current_run.logs = [*(current_run.logs or []), {
                "level": "error",
                "message": str(error),
                "code": current_run.error_code,
            }]
            current_run.finished_at = datetime.now(timezone.utc)
            db.commit()
        publisher.publish(run_id, {
            "type": "run_completed",
            "status": "failed",
            "error": str(error),
        })
