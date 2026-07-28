"""Transactional persistence for frozen domain events."""

from sqlalchemy.orm import Session

from app.events.domain import DomainEvent, to_storage_payload
from app.models.notifications import NotificationOutbox


class OutboxDomainEventRecorder:
    """Write domain events inside the caller-owned business transaction."""

    def record(self, db: Session, event: DomainEvent) -> None:
        with db.no_autoflush:
            duplicate = db.query(NotificationOutbox).filter(
                NotificationOutbox.event_id == event.event_id,
                NotificationOutbox.idempotency_key == event.idempotency_key,
            ).first()
        if duplicate is not None:
            return

        db.add(NotificationOutbox(
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            event_type=event.event_type,
            severity="critical" if event.severity == "error" else event.severity,
            occurred_at=event.occurred_at.replace(tzinfo=None),
            project_id=event.project_id,
            actor_id=event.actor_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            payload=to_storage_payload(event.payload),
            status="pending",
        ))
        db.flush()
