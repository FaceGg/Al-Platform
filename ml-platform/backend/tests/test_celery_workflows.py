import unittest
import uuid
import subprocess
import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from app.tasks.workflow_tasks import (
    claim_run,
    execute_workflow_task,
    heartbeat_run,
    utcnow,
)
from app.tasks.recovery import reconcile_stale_runs


class FakeRun:
    def __init__(self, status, task_id=None, worker_id=None, heartbeat_at=None):
        self.status = status
        self.task_id = task_id
        self.worker_id = worker_id
        self.heartbeat_at = heartbeat_at


class FakeQuery:
    def __init__(self, run):
        self.run = run
        self.locked = False
    def with_for_update(self):
        self.locked = True
        return self
    def filter(self, *args): return self
    def first(self): return self.run


class FakeDB:
    def __init__(self, run): self.run = run
    def query(self, model): return FakeQuery(self.run)
    def commit(self): pass


class TestCeleryWorkflowClaims(unittest.TestCase):
    def test_worker_import_registers_builtin_operators(self):
        command = (
            "import app.tasks.workflow_tasks; "
            "from app.engine.registry import OperatorRegistry; "
            "assert OperatorRegistry.get('condition') is not None"
        )
        result = subprocess.run(
            [sys.executable, "-c", command],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fresh_running_task_is_not_claimed_twice(self):
        run = FakeRun("running", "task-1", "worker-1", utcnow())
        self.assertFalse(claim_run(FakeDB(run), uuid.uuid4(), "task-2", "worker-2"))

    def test_stale_running_task_can_be_reclaimed(self):
        run = FakeRun("running", "task-1", "worker-1", utcnow() - timedelta(minutes=5))
        self.assertTrue(claim_run(FakeDB(run), uuid.uuid4(), "task-2", "worker-2"))
        self.assertEqual(run.task_id, "task-2")

    def test_claim_locks_run_row_before_state_transition(self):
        run = FakeRun("pending")
        db = FakeDB(run)
        query = FakeQuery(run)
        db.query = lambda _model: query

        self.assertTrue(claim_run(db, uuid.uuid4(), "task-1", "worker-1"))
        self.assertTrue(query.locked)

    def test_stale_run_is_reconciled_to_hard_timeout(self):
        run = FakeRun("running", "task-1", "worker-1", utcnow() - timedelta(minutes=10))
        class DB(FakeDB):
            def query(self, model):
                return SimpleNamespace(
                    filter=lambda *args: SimpleNamespace(all=lambda: [run]),
                )
        self.assertEqual(reconcile_stale_runs(DB(run), set(), timedelta(minutes=5)), 1)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "TASK_HARD_TIMEOUT")

    def test_stale_cancel_request_is_reconciled_to_cancelled(self):
        run = FakeRun(
            "cancel_requested",
            "task-1",
            "worker-1",
            utcnow() - timedelta(minutes=10),
        )
        class DB(FakeDB):
            def query(self, model):
                return SimpleNamespace(
                    filter=lambda *args: SimpleNamespace(all=lambda: [run]),
                )

        self.assertEqual(
            reconcile_stale_runs(DB(run), set(), timedelta(minutes=5)),
            1,
        )
        self.assertEqual(run.status, "cancelled")

    @patch("app.tasks.workflow_tasks.build_event_publisher")
    @patch("app.tasks.workflow_tasks.execute_workflow_run")
    @patch("app.tasks.workflow_tasks.claim_run", return_value=True)
    @patch("app.tasks.workflow_tasks.SessionLocal")
    def test_worker_executes_claimed_workflow_through_real_service(
        self,
        session_local,
        _claim_run,
        execute_workflow_run,
        build_event_publisher,
    ):
        db = MagicMock()
        session_local.return_value.__enter__.return_value = db
        publisher = build_event_publisher.return_value
        run_id = str(uuid.uuid4())

        result = execute_workflow_task.run(run_id)

        execute_workflow_run.assert_called_once_with(
            run_id,
            event_publisher=publisher,
        )
        publisher.close.assert_called_once_with()
        self.assertEqual(result, {"status": "completed", "run_id": run_id})

    def test_heartbeat_refreshes_claimed_run(self):
        run = FakeRun("running", "task-1", "worker-1", None)
        db = FakeDB(run)
        session_factory = MagicMock()
        session_factory.return_value.__enter__.return_value = db

        stop_event = MagicMock()
        stop_event.is_set.return_value = False
        stop_event.wait.return_value = True
        heartbeat_run(
            uuid.uuid4(),
            "task-1",
            stop_event,
            session_factory=session_factory,
            interval_seconds=0.01,
        )

        self.assertIsNotNone(run.heartbeat_at)
        stop_event.wait.assert_called_once_with(0.01)

    @patch("app.tasks.workflow_tasks.SessionLocal")
    def test_heartbeat_resolves_default_session_factory_at_call_time(
        self,
        session_local,
    ):
        run = FakeRun("running", "task-1", "worker-1", None)
        db = FakeDB(run)
        session_local.return_value.__enter__.return_value = db
        stop_event = MagicMock()
        stop_event.is_set.return_value = False
        stop_event.wait.return_value = True

        heartbeat_run(
            uuid.uuid4(),
            "task-1",
            stop_event,
            interval_seconds=0.01,
        )

        session_local.assert_called_once_with()
        self.assertIsNotNone(run.heartbeat_at)


if __name__ == "__main__": unittest.main()
