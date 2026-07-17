"""In-process run event publisher."""

from collections.abc import Callable


class LocalRunEventPublisher:
    def __init__(self, publish: Callable[[str, dict], None]):
        self._publish = publish

    def publish(self, run_id: str, payload: dict) -> None:
        self._publish(run_id, payload)
