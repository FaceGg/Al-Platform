"""Transactional persistence for frozen domain events."""

from datetime import datetime, timezone
from hashlib import sha256
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


def _record_annotation_event(db: Session, event: DomainEvent):
    dialect = db.get_bind().dialect.name
    statement_factory = postgresql_insert if dialect == "postgresql" else sqlite_insert
    db.execute(statement_factory(NotificationOutbox).values(
        id=uuid4(),
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
        event_type=event.event_type,
        severity=event.severity,
        occurred_at=event.occurred_at.replace(tzinfo=None),
        project_id=event.project_id,
        actor_id=event.actor_id,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        payload=to_storage_payload(event.payload),
        status="pending",
    ).on_conflict_do_nothing(index_elements=[NotificationOutbox.idempotency_key]))
    return db.query(NotificationOutbox.event_id).filter(
        NotificationOutbox.idempotency_key == event.idempotency_key,
    ).scalar()


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
    event_id = _record_annotation_event(db, event)
    if db.query(InAppNotification.id).filter(
        InAppNotification.event_id == event_id,
        InAppNotification.recipient_user_id == recipient_user_id,
    ).first() is not None:
        return
    values = {
        "id": uuid4(),
        "recipient_user_id": recipient_user_id,
        "project_id": project_id,
        "event_id": event_id,
        "event_type": event_type,
        "deduplication_key": sha256(f"{event_type}:{return_batch_id}:{recipient_user_id}".encode()).hexdigest(),
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


def emit_annotation_comment_notification(
    db: Session,
    *,
    project_id,
    actor_id,
    recipient_user_id,
    comment_id,
    event_type: str,
    status: str | None = None,
    parent_comment_id=None,
    transition_id=None,
) -> None:
    event = create_domain_event(
        idempotency_key=f"{event_type}:{comment_id}:{transition_id or status or 'created'}",
        event_type=event_type,
        severity="info",
        occurred_at=datetime.now(timezone.utc),
        project_id=project_id,
        actor_id=actor_id,
        resource_type="annotation_comment",
        resource_id=str(comment_id),
        payload={
            "comment_id": str(comment_id),
            "parent_comment_id": str(parent_comment_id) if parent_comment_id else None,
            "status": status,
        },
    )
    event_id = _record_annotation_event(db, event)
    if db.query(InAppNotification.id).filter(
        InAppNotification.event_id == event_id,
        InAppNotification.recipient_user_id == recipient_user_id,
    ).first() is not None:
        return
    dialect = db.get_bind().dialect.name
    statement_factory = postgresql_insert if dialect == "postgresql" else sqlite_insert
    title = "Annotation comment updated"
    body = "An annotation comment received a reply." if event_type.endswith("replied") else "An annotation comment status changed."
    db.execute(statement_factory(InAppNotification).values(
        id=uuid4(),
        recipient_user_id=recipient_user_id,
        project_id=project_id,
        event_id=event_id,
        event_type=event_type,
        deduplication_key=sha256(f"{event.idempotency_key}:{recipient_user_id}".encode()).hexdigest(),
        severity="info",
        title=title,
        body=body,
        payload=to_storage_payload(event.payload),
    ).on_conflict_do_nothing(index_elements=[InAppNotification.deduplication_key]))
    db.flush()
