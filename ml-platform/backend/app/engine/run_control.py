import time
from collections.abc import Callable


class RunCancelled(RuntimeError):
    pass


class RunControl:
    def __init__(self, cancel_requested: Callable[[], bool] | None = None):
        self._cancel_requested = cancel_requested or (lambda: False)

    def check_cancelled(self) -> None:
        if self._cancel_requested():
            raise RunCancelled("Workflow run cancelled")

    def is_cancel_requested(self) -> bool:
        return self._cancel_requested()

    def wait(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.check_cancelled()
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
