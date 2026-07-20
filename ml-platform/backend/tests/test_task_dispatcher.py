import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, sentinel

from app.tasks.dispatcher import CeleryTaskDispatcher, LocalTaskDispatcher


class TestTaskDispatcher(unittest.TestCase):
    def test_local_dispatcher_enqueues_and_reports_completion(self):
        calls = []
        dispatcher = LocalTaskDispatcher(lambda run_id: calls.append(run_id))
        task_id = dispatcher.enqueue_workflow("run-1")
        thread = dispatcher._tasks[task_id]
        thread.join(timeout=2)
        self.assertEqual(calls, ["run-1"])
        self.assertEqual(dispatcher.get_status(task_id), "finished")

    def test_celery_cancel_binds_async_result_to_task_app(self):
        task = SimpleNamespace(app=sentinel.celery_app)
        result = MagicMock()
        with patch("celery.result.AsyncResult", return_value=result) as async_result:
            CeleryTaskDispatcher(task).cancel("task-1", terminate=True)

        async_result.assert_called_once_with("task-1", app=sentinel.celery_app)
        result.revoke.assert_called_once_with(terminate=True, signal="SIGTERM")


if __name__ == "__main__":
    unittest.main()
