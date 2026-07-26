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
    def test_week9_rollout_tasks_are_registered_with_beat_schedules(self):
        from app.tasks.celery_app import celery_app

        for task_name in (
            "ml_platform.advance_inference_rollout",
            "ml_platform.rollback_inference_rollout",
            "ml_platform.reconcile_inference_rollouts",
            "ml_platform.prune_inference_telemetry",
        ):
            with self.subTest(task_name=task_name):
                self.assertIn(task_name, celery_app.tasks)
        self.assertEqual(
            celery_app.conf.beat_schedule["inference-rollout-reconciliation"]["schedule"],
            60.0,
        )
        self.assertEqual(
            celery_app.conf.beat_schedule["inference-telemetry-retention"]["task"],
            "ml_platform.prune_inference_telemetry",
        )

    def test_inference_reconciliation_is_registered_with_beat(self):
        from app.tasks.celery_app import celery_app

        self.assertIn(
            "ml_platform.reconcile_inference_deployments",
            celery_app.tasks,
        )
        self.assertEqual(
            celery_app.conf.beat_schedule["inference-deployment-reconciliation"]["task"],
            "ml_platform.reconcile_inference_deployments",
        )

    @patch("app.tasks.inference_tasks.build_inference_deployment_service")
    @patch("app.tasks.inference_tasks.SessionLocal")
    @patch("app.tasks.inference_tasks.InferenceRolloutService")
    def test_inference_deployment_reconciliation_does_not_duplicate_rollout_work(
        self,
        rollout_service,
        session_local,
        build_deployment_service,
    ):
        from app.tasks.inference_tasks import reconcile_inference_deployments

        db = MagicMock()
        session_local.return_value.__enter__.return_value = db
        deployment_service = build_deployment_service.return_value
        deployment_service.runtime = object()
        deployment_service.reconcile.return_value = {
            "loaded": 1, "unloaded": 0, "failed": 0,
        }

        result = reconcile_inference_deployments.run()

        deployment_service.reconcile.assert_called_once_with(db)
        rollout_service.assert_not_called()
        self.assertEqual(result, {"loaded": 1, "unloaded": 0, "failed": 0})

    def test_advance_rollout_task_returns_persisted_state_for_duplicate_delivery(self):
        from app.services.inference_rollout import InferenceRolloutError
        from app.tasks.inference_tasks import advance_inference_rollout

        rollout = SimpleNamespace(
            id=uuid.uuid4(), state="progressing", lock_version=4,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = rollout
        with patch("app.tasks.inference_tasks.SessionLocal") as session_local, patch(
            "app.tasks.inference_tasks.build_inference_rollout_service",
        ) as build_rollout_service:
            session_local.return_value.__enter__.return_value = db
            rollout_service = build_rollout_service.return_value
            rollout_service.advance.side_effect = [
                rollout,
                InferenceRolloutError("ROLLOUT_REVISION_CONFLICT"),
            ]

            first = advance_inference_rollout.run(str(rollout.id), 3)
            second = advance_inference_rollout.run(str(rollout.id), 3)

        expected = {
            "id": str(rollout.id),
            "state": "progressing",
            "lock_version": 4,
        }
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)

    def test_advance_rollout_task_does_not_hide_unexpected_errors(self):
        from app.tasks.inference_tasks import advance_inference_rollout

        db = MagicMock()
        with patch("app.tasks.inference_tasks.SessionLocal") as session_local, patch(
            "app.tasks.inference_tasks.build_inference_rollout_service",
        ) as build_rollout_service:
            session_local.return_value.__enter__.return_value = db
            build_rollout_service.return_value.advance.side_effect = RuntimeError(
                "unexpected runtime failure",
            )

            with self.assertRaisesRegex(RuntimeError, "unexpected runtime failure"):
                advance_inference_rollout.run(str(uuid.uuid4()), 1)

    def test_rollback_rollout_task_returns_persisted_state(self):
        from app.tasks.inference_tasks import rollback_inference_rollout

        rollout = SimpleNamespace(
            id=uuid.uuid4(), state="rolled_back", lock_version=5,
        )
        db = MagicMock()
        with patch("app.tasks.inference_tasks.SessionLocal") as session_local, patch(
            "app.tasks.inference_tasks.build_inference_rollout_service",
        ) as build_rollout_service:
            session_local.return_value.__enter__.return_value = db
            build_rollout_service.return_value.rollback.return_value = rollout

            result = rollback_inference_rollout.run(str(rollout.id), 4)

        self.assertEqual(
            result,
            {"id": str(rollout.id), "state": "rolled_back", "lock_version": 5},
        )

    def test_rollback_rollout_task_returns_only_known_stable_domain_error(self):
        from app.services.inference_rollout import InferenceRolloutError
        from app.tasks.inference_tasks import rollback_inference_rollout

        rollout_id = str(uuid.uuid4())
        db = MagicMock()
        with patch("app.tasks.inference_tasks.SessionLocal") as session_local, patch(
            "app.tasks.inference_tasks.build_inference_rollout_service",
        ) as build_rollout_service:
            session_local.return_value.__enter__.return_value = db
            build_rollout_service.return_value.rollback.side_effect = (
                InferenceRolloutError("ROLLOUT_NOT_FOUND")
            )

            result = rollback_inference_rollout.run(rollout_id, 1)

        self.assertEqual(result, {"id": rollout_id, "error_code": "ROLLOUT_NOT_FOUND"})

    def test_rollout_reconciliation_recovers_pending_then_advances(self):
        from app.tasks.inference_tasks import reconcile_inference_rollouts

        pending = SimpleNamespace(
            id=uuid.uuid4(), state="pending", lock_version=4,
        )
        progressing = SimpleNamespace(
            id=pending.id, state="progressing", lock_version=5,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.all.side_effect = [
            [pending], [progressing],
        ]
        with patch("app.tasks.inference_tasks.SessionLocal") as session_local, patch(
            "app.tasks.inference_tasks.build_inference_rollout_service",
        ) as build_rollout_service:
            session_local.return_value.__enter__.return_value = db
            rollout_service = build_rollout_service.return_value
            rollout_service.reconcile.return_value = {"loaded": 1, "failed": 0}
            rollout_service.advance.return_value = SimpleNamespace(
                id=progressing.id, state="progressing", lock_version=6,
            )

            result = reconcile_inference_rollouts.run()

        rollout_service.reconcile.assert_called_once_with(db)
        rollout_service.advance.assert_called_once_with(
            db, progressing.id, expected_lock_version=5,
        )
        self.assertEqual(
            result,
            {"loaded": 1, "failed": 0, "advanced": 1, "advance_failed": 0},
        )

    def test_rollout_reconciliation_does_not_preload_progressing_rollout(self):
        from app.tasks.inference_tasks import reconcile_inference_rollouts

        rollout = SimpleNamespace(
            id=uuid.uuid4(), state="progressing", lock_version=4,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.all.side_effect = [
            [], [rollout],
        ]
        with patch("app.tasks.inference_tasks.SessionLocal") as session_local, patch(
            "app.tasks.inference_tasks.build_inference_rollout_service",
        ) as build_rollout_service:
            session_local.return_value.__enter__.return_value = db
            rollout_service = build_rollout_service.return_value
            rollout_service.advance.return_value = SimpleNamespace(
                id=rollout.id, state="progressing", lock_version=5,
            )

            result = reconcile_inference_rollouts.run()

        rollout_service.reconcile.assert_not_called()
        rollout_service.advance.assert_called_once_with(
            db, rollout.id, expected_lock_version=4,
        )
        self.assertEqual(
            result,
            {"loaded": 0, "failed": 0, "advanced": 1, "advance_failed": 0},
        )

    def test_prune_telemetry_task_commits_retention_result(self):
        from app.tasks.inference_tasks import prune_inference_telemetry

        db = MagicMock()
        with patch("app.tasks.inference_tasks.SessionLocal") as session_local, patch(
            "app.tasks.inference_tasks.InferenceObservability",
        ) as observability:
            session_local.return_value.__enter__.return_value = db
            observability.return_value.prune.return_value = 3

            result = prune_inference_telemetry.run()

        observability.return_value.prune.assert_called_once_with(db)
        db.commit.assert_called_once_with()
        self.assertEqual(result, {"pruned": 3})

    def test_prune_telemetry_task_uses_configured_log_retention(self):
        from app.tasks.inference_tasks import prune_inference_telemetry

        db = MagicMock()
        with patch("app.tasks.inference_tasks.SessionLocal") as session_local, patch(
            "app.tasks.inference_tasks.InferenceObservability",
        ) as observability, patch(
            "app.tasks.inference_tasks.settings.inference_log_retention_days",
            17,
        ):
            session_local.return_value.__enter__.return_value = db
            observability.return_value.prune.return_value = 0

            prune_inference_telemetry.run()

        observability.assert_called_once_with(log_retention_days=17)

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
