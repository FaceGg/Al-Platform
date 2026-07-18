"""Local and pluggable workflow task dispatchers."""

import threading
from collections.abc import Callable
from typing import Protocol


class TaskDispatcher(Protocol):
    def enqueue_workflow(self, run_id: str, timeout_seconds: int | None = None) -> str: ...
    def cancel(self, task_id: str, terminate: bool = False) -> None: ...
    def get_status(self, task_id: str) -> str: ...


class LocalTaskDispatcher:
    def __init__(self, execute: Callable[[str], None]):
        self.execute = execute
        self._tasks: dict[str, threading.Thread] = {}

    def enqueue_workflow(self, run_id: str, timeout_seconds: int | None = None) -> str:
        thread = threading.Thread(target=self.execute, args=(run_id,), daemon=True)
        thread.start()
        task_id = f"local:{thread.ident or run_id}"
        self._tasks[task_id] = thread
        return task_id

    def cancel(self, task_id: str, terminate: bool = False) -> None:
        return None

    def get_status(self, task_id: str) -> str:
        thread = self._tasks.get(task_id)
        if thread is None:
            return "unknown"
        return "running" if thread.is_alive() else "finished"


class CeleryTaskDispatcher:
    def __init__(self, task):
        self.task = task
        self.app = getattr(task, "app", None)
        self._results = {}

    def enqueue_workflow(self, run_id: str, timeout_seconds: int | None = None) -> str:
        if timeout_seconds is None:
            result = self.task.delay(run_id)
        else:
            result = self.task.apply_async(
                args=[run_id],
                time_limit=timeout_seconds,
            )
        self._results[result.id] = result
        return result.id

    def cancel(self, task_id: str, terminate: bool = False) -> None:
        from celery.result import AsyncResult
        AsyncResult(task_id, app=self.app).revoke(
            terminate=terminate,
            signal="SIGTERM",
        )

    def get_status(self, task_id: str) -> str:
        result = self._results.get(task_id)
        if result is None:
            from celery.result import AsyncResult
            result = AsyncResult(task_id, app=self.app)
        return str(result.state).lower()
