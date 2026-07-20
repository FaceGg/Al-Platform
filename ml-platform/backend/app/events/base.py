"""Run event publisher protocols."""

from typing import Protocol


class RunEventPublisher(Protocol):
    def publish(self, run_id: str, payload: dict) -> None: ...


class NullRunEventPublisher:
    def publish(self, run_id: str, payload: dict) -> None:
        return None
