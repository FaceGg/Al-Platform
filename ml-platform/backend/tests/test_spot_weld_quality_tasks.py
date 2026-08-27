import unittest
from threading import Event
from unittest.mock import patch


class TestSpotWeldQualityTasks(unittest.TestCase):
    def test_celery_worker_discovers_spot_weld_quality_task(self):
        from app.tasks.celery_app import celery_app

        self.assertIn("app.tasks.spot_weld_quality_tasks", celery_app.conf.include)
        self.assertIn("ml_platform.execute_spot_weld_quality", celery_app.tasks)

    def test_dispatcher_returns_celery_task_id(self):
        from app.tasks.spot_weld_quality_tasks import CeleryQualityDispatcher

        class FakeTask:
            def delay(self, run_id):
                self.run_id = run_id
                return type("Result", (), {"id": "quality-task-1"})()

        dispatcher = CeleryQualityDispatcher(task=FakeTask())
        self.assertEqual(dispatcher.enqueue("run-1"), "quality-task-1")

    @patch("celery.result.AsyncResult")
    def test_celery_dispatcher_revokes_active_task(self, async_result):
        from app.tasks.spot_weld_quality_tasks import CeleryQualityDispatcher

        task = type("FakeTask", (), {"app": object()})()
        dispatcher = CeleryQualityDispatcher(task=task)

        dispatcher.cancel("quality-task-1")

        async_result.assert_called_once_with("quality-task-1", app=task.app)
        async_result.return_value.revoke.assert_called_once_with(terminate=True, signal="SIGTERM")

    def test_task_failure_has_stable_code(self):
        from app.tasks.spot_weld_quality_tasks import execute_spot_weld_quality_task

        with patch("app.tasks.spot_weld_quality_tasks._execute_task", return_value={
            "status": "failed", "error_code": "QUALITY_RUN_NOT_FOUND",
        }):
            outcome = execute_spot_weld_quality_task.run("not-a-run")
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["error_code"], "QUALITY_RUN_NOT_FOUND")

    def test_local_dispatcher_waits_for_explicit_start_after_queue_commit(self):
        from app.tasks.spot_weld_quality_tasks import LocalQualityDispatcher

        completed = Event()
        calls = []

        def execute(run_id, *, worker_id, task_id):
            calls.append((run_id, worker_id, task_id))
            completed.set()
            return {"status": "completed"}

        dispatcher = LocalQualityDispatcher(execute=execute)
        task_id = dispatcher.enqueue("run-1")

        self.assertTrue(task_id.startswith("local:"))
        self.assertFalse(completed.wait(0.1))
        dispatcher.start(task_id)
        self.assertTrue(completed.wait(1))
        self.assertEqual(calls, [("run-1", "local", task_id)])

    def test_local_dispatcher_does_not_start_cancelled_pending_task(self):
        from app.tasks.spot_weld_quality_tasks import LocalQualityDispatcher

        completed = Event()
        dispatcher = LocalQualityDispatcher(execute=lambda *_args, **_kwargs: completed.set())
        task_id = dispatcher.enqueue("run-1")

        dispatcher.cancel(task_id)
        dispatcher.start(task_id)

        self.assertFalse(completed.wait(0.1))

    def test_local_dispatcher_exposes_running_task_cancellation(self):
        from app.tasks.spot_weld_quality_tasks import LocalQualityDispatcher

        started = Event()
        release = Event()
        cancelled = Event()

        def execute(_run_id, *, worker_id, task_id, cancellation_requested):
            started.set()
            release.wait(1)
            if cancellation_requested():
                cancelled.set()

        dispatcher = LocalQualityDispatcher(execute=execute)
        task_id = dispatcher.enqueue("run-1")
        dispatcher.start(task_id)

        self.assertTrue(started.wait(1))
        dispatcher.cancel(task_id)
        release.set()
        self.assertTrue(cancelled.wait(1))


if __name__ == "__main__":
    unittest.main()
