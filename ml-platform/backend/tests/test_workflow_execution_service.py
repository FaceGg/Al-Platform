"""Tests for app.services.workflow_execution.

Covers the _duration_ms helper and the execute_workflow_run error paths
that the task-layer tests do not assert directly.
"""
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, ".")

from app.services import workflow_execution
from app.services.workflow_execution import _duration_ms, execute_workflow_run


class TestDurationMs(unittest.TestCase):
    def test_returns_none_when_started_at_is_none(self):
        self.assertIsNone(_duration_ms(None, datetime.now(timezone.utc)))

    def test_naive_datetimes_treated_as_utc(self):
        started = datetime(2026, 7, 22, 10, 0, 0)
        finished = datetime(2026, 7, 22, 10, 0, 1, 500000)
        self.assertEqual(_duration_ms(started, finished), 1500)

    def test_aware_datetimes(self):
        started = datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc)
        finished = started + timedelta(seconds=2, milliseconds=250)
        self.assertEqual(_duration_ms(started, finished), 2250)

    def test_mixed_awareness(self):
        started = datetime(2026, 7, 22, 10, 0, 0)  # naive
        finished = datetime(2026, 7, 22, 10, 0, 3, tzinfo=timezone.utc)
        self.assertEqual(_duration_ms(started, finished), 3000)

    def test_negative_duration_when_finished_before_started(self):
        started = datetime(2026, 7, 22, 10, 0, 5)
        finished = datetime(2026, 7, 22, 10, 0, 0)
        self.assertEqual(_duration_ms(started, finished), -5000)


class TestExecuteWorkflowRunErrors(unittest.TestCase):
    """Use an in-memory SQLite DB to exercise the persistence error paths."""

    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.database import Base
        from app.models.user import User
        from app.models.project import Project
        from app.models.workflow import Workflow
        from app.models.run import WorkflowRun

        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)

        with cls.Session() as db:
            cls.user = User(username="wfe-owner", password_hash="hash")
            db.add(cls.user)
            db.flush()
            cls.project = Project(name="WFE project", owner_id=cls.user.id)
            db.add(cls.project)
            db.flush()
            cls.workflow = Workflow(
                project_id=cls.project.id,
                name="WFE workflow",
                created_by=cls.user.id,
            )
            db.add(cls.workflow)
            db.flush()
            # Run attached to a workflow that has NO nodes.
            cls.run_no_nodes = WorkflowRun(
                workflow_id=cls.workflow.id,
                status="pending",
                triggered_by=cls.user.id,
            )
            db.add(cls.run_no_nodes)
            db.commit()
            cls.run_no_nodes_id = str(cls.run_no_nodes.id)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def test_raises_when_run_not_found(self):
        missing_id = str(uuid.uuid4())
        events = []
        publisher = _CapturingPublisher(events)
        with self.assertRaises(RuntimeError) as ctx:
            execute_workflow_run(
                missing_id,
                session_factory=self.Session,
                event_publisher=publisher,
            )
        self.assertIn("not found", str(ctx.exception))
        self.assertEqual(events, [])

    def test_run_with_no_nodes_is_marked_failed(self):
        events = []
        publisher = _CapturingPublisher(events)
        execute_workflow_run(
            self.run_no_nodes_id,
            session_factory=self.Session,
            event_publisher=publisher,
        )
        # The run should be persisted as failed and a run_completed event emitted.
        with self.Session() as db:
            from app.models.run import WorkflowRun
            run = db.query(WorkflowRun).filter(
                WorkflowRun.id == uuid.UUID(self.run_no_nodes_id),
            ).first()
            self.assertEqual(run.status, "failed")
            self.assertEqual(run.error_message, "No nodes in workflow")

        completed = [e for e in events if e["payload"].get("type") == "run_completed"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["payload"]["status"], "failed")

    def test_passes_persisted_workflow_id_to_executor(self):
        from app.models.run import WorkflowRun
        from app.models.workflow import Workflow, WorkflowNode

        with self.Session() as db:
            workflow = Workflow(
                project_id=self.project.id,
                name="WFE executor workflow",
                created_by=self.user.id,
            )
            db.add(workflow)
            db.flush()
            node = WorkflowNode(
                workflow_id=workflow.id,
                operator_id="csv_import",
                label="Import",
                position_x=0,
                position_y=0,
                params={},
            )
            workflow_run = WorkflowRun(
                workflow_id=workflow.id,
                status="pending",
                triggered_by=self.user.id,
            )
            db.add_all([node, workflow_run])
            db.commit()
            run_id = str(workflow_run.id)
            workflow_id = str(workflow.id)

        with patch("app.services.workflow_execution.DAGExecutor") as executor_class:
            executor_class.return_value.execute.return_value = {}
            execute_workflow_run(
                run_id,
                session_factory=self.Session,
                event_publisher=_CapturingPublisher([]),
            )

        self.assertEqual(
            executor_class.call_args.kwargs["workflow_id"],
            workflow_id,
        )


class _CapturingPublisher:
    """RunEventPublisher implementation that records publish() calls."""

    def __init__(self, sink):
        self.sink = sink

    def publish(self, run_id, payload):
        self.sink.append({"run_id": run_id, "payload": payload})


class TestModuleImportsOperators(unittest.TestCase):
    """workflow_execution imports app.operators to register built-ins in workers."""

    def test_module_exposes_execute_workflow_run(self):
        self.assertTrue(callable(workflow_execution.execute_workflow_run))


if __name__ == "__main__":
    unittest.main()
