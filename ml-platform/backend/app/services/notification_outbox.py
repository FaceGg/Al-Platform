"""Transactional persistence for frozen domain events."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.events.domain import DomainEvent, create_domain_event, to_storage_payload
from app.models.notifications import InAppNotification, NotificationOutbox


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


def emit_annotation_return_notification(
    db: Session,
    *,
    project_id,
    actor_id,
    recipient_user_id,
    return_batch_id,
    event_type: str,
) -> None:
    """Persist a safe outbox event and its immediate in-app recipient notice."""
    event = create_domain_event(
        idempotency_key=f"{event_type}:{return_batch_id}",
        event_type=event_type,
        severity="info",
        occurred_at=datetime.now(timezone.utc),
        project_id=project_id,
        actor_id=actor_id,
        resource_type="annotation_return_batch",
        resource_id=str(return_batch_id),
        payload={"return_batch_id": str(return_batch_id)},
    )
    OutboxDomainEventRecorder().record(db, event)
    values = {
        "id": uuid4(),
        "recipient_user_id": recipient_user_id,
        "project_id": project_id,
        "event_id": event.event_id,
        "event_type": event_type,
        "deduplication_key": f"{event_type}:{return_batch_id}:{recipient_user_id}",
        "severity": "info",
        "title": "Annotation return updated",
        "body": "An annotation return batch has been updated.",
        "payload": {"return_batch_id": str(return_batch_id)},
    }
    dialect = db.get_bind().dialect.name
    statement_factory = postgresql_insert if dialect == "postgresql" else sqlite_insert
    db.execute(statement_factory(InAppNotification).values(**values).on_conflict_do_nothing(
        index_elements=[InAppNotification.deduplication_key],
    ))
    db.flush()
