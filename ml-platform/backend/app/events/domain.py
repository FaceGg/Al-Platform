"""Safe domain-event contract for production inference workflows."""

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, Protocol
from uuid import UUID, uuid4

from sqlalchemy.orm import Session


SAFE_EVENT_TYPES = frozenset({
    "rollout.started",
    "rollout.failed",
    "rollout.completed",
    "rollback.completed",
    "runtime.load_failed",
    "rate_limit.threshold_exceeded",
    "inference.error_rate.threshold_exceeded",
})

SAFE_PAYLOAD_KEYS = frozenset({
    "revision_id",
    "deployment_id",
    "model_version_ids",
    "error_code",
    "step",
})


@dataclass(frozen=True)
class DomainEvent:
    event_id: UUID
    idempotency_key: str
    event_type: str
    severity: str
    occurred_at: datetime
    project_id: UUID | None
    actor_id: UUID | None
    resource_type: str
    resource_id: str | None
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.event_type not in SAFE_EVENT_TYPES:
            raise ValueError("DOMAIN_EVENT_TYPE_INVALID")
        safe_payload = {
            key: value for key, value in self.payload.items() if key in SAFE_PAYLOAD_KEYS
        }
        object.__setattr__(self, "payload", MappingProxyType(safe_payload))


class DomainEventRecorder(Protocol):
    def record(self, db: Session, event: DomainEvent) -> None:
        raise NotImplementedError


class NullDomainEventRecorder:
    def record(self, db: Session, event: DomainEvent) -> None:
        return None


def create_domain_event(
    *,
    idempotency_key: str,
    event_type: str,
    severity: str,
    occurred_at: datetime,
    project_id: UUID | None,
    actor_id: UUID | None,
    resource_type: str,
    resource_id: str | None,
    payload: Mapping[str, object],
) -> DomainEvent:
    """Create an immutable event while filtering payload to safe fields."""
    return DomainEvent(
        event_id=uuid4(),
        idempotency_key=idempotency_key,
        event_type=event_type,
        severity=severity,
        occurred_at=occurred_at,
        project_id=project_id,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload,
    )
