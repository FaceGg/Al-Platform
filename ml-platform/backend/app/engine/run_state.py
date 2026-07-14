from dataclasses import dataclass
from typing import Any


RUN_STATUSES = frozenset({
    "pending", "running", "cancel_requested", "completed", "failed", "cancelled",
})
NODE_STATUSES = frozenset({
    "pending", "running", "completed", "failed", "timed_out", "cancelled", "skipped",
})
TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})

_RUN_TRANSITIONS = {
    "pending": {"running", "cancel_requested", "failed"},
    "running": {"completed", "failed", "cancel_requested"},
    "cancel_requested": {"cancelled"},
}


class InvalidStateTransition(ValueError):
    pass


def transition_run_status(current: str, target: str) -> str:
    if current == target:
        return current
    if target not in _RUN_TRANSITIONS.get(current, set()):
        raise InvalidStateTransition(f"Cannot transition run from '{current}' to '{target}'")
    return target


@dataclass(frozen=True)
class ExecutionPolicy:
    timeout_seconds: float = 300
    max_retries: int = 0
    retry_delay_seconds: float = 0

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> "ExecutionPolicy":
        policy = cls(
            timeout_seconds=float(params.get("timeout_seconds", 300)),
            max_retries=int(params.get("max_retries", 0)),
            retry_delay_seconds=float(params.get("retry_delay_seconds", 0)),
        )
        if policy.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if policy.max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if policy.retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must not be negative")
        return policy
