"""Durable notification outbox claiming and delivery tasks."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.events.domain import DomainEvent
from app.models.access import ProjectMember
from app.models.notifications import (
    InAppNotification,
    NotificationDelivery,
    NotificationEndpoint,
    NotificationOutbox,
    NotificationSubscription,
)
from app.models.project import Project
from app.services.notification_channels import (
    DeliveryResult,
    NotificationChannelRouter,
)
from app.tasks.celery_app import celery_app


SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}
RETRYABLE_ERROR_CODES = frozenset({
    "WEBHOOK_TIMEOUT",
    "NOTIFICATION_TIMEOUT",
    "NOTIFICATION_PROVIDER_TIMEOUT",
    "NOTIFICATION_PROVIDER_UNAVAILABLE",
    "NOTIFICATION_PROVIDER_RETRYABLE",
    "NOTIFICATION_WECOM_RATE_LIMITED",
    "NOTIFICATION_EMAIL_RETRYABLE",
    "NOTIFICATION_EMAIL_UNAVAILABLE",
})
ERROR_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,64}$")


def _now(value: datetime | None = None) -> datetime:
    """Return a database-compatible UTC-naive timestamp."""
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    return current


def _as_uuid(value: object) -> UUID | None:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _dialect_name(db: Session) -> str:
    return db.get_bind().dialect.name


def _is_due(column, now: datetime):
    return or_(column.is_(None), column <= now)


def _outbox_claimable(now: datetime):
    stale_before = now - timedelta(seconds=settings.task_hard_timeout_seconds)
    return or_(
        and_(
            NotificationOutbox.status == "pending",
            _is_due(NotificationOutbox.next_attempt_at, now),
        ),
        and_(
            NotificationOutbox.status == "processing",
            NotificationOutbox.claimed_at.is_not(None),
            NotificationOutbox.claimed_at < stale_before,
        ),
    )


def _delivery_claimable(now: datetime):
    stale_before = now - timedelta(seconds=settings.task_hard_timeout_seconds)
    return or_(
        and_(
            NotificationDelivery.status.in_(("pending", "retry")),
            _is_due(NotificationDelivery.next_attempt_at, now),
        ),
        and_(
            NotificationDelivery.status == "processing",
            NotificationDelivery.claimed_at.is_not(None),
            NotificationDelivery.claimed_at < stale_before,
        ),
    )


def _safe_error_code(value: object) -> str:
    candidate = value if isinstance(value, str) else ""
    return candidate if ERROR_CODE_PATTERN.fullmatch(candidate) else "NOTIFICATION_DELIVERY_FAILED"


def _safe_provider_status(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 100 <= value <= 599 else None


def _delivery_key(outbox: NotificationOutbox, subscription: NotificationSubscription) -> str:
    material = f"{outbox.event_id}:{subscription.id}:{subscription.endpoint_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def next_retry_at(attempt: int, now: datetime, jitter: float) -> datetime:
    """Return the bounded exponential retry timestamp for one delivery attempt."""
    try:
        normalized_attempt = int(attempt)
    except (TypeError, ValueError):
        normalized_attempt = 0
    try:
        normalized_jitter = float(jitter)
    except (TypeError, ValueError):
        normalized_jitter = 0.0
    base = min(300, 2 ** max(0, normalized_attempt - 1))
    bounded_jitter = min(max(0.0, normalized_jitter), base / 4)
    return now + timedelta(seconds=base + bounded_jitter)


def claim_outbox(
    db: Session,
    outbox_id: object,
    *,
    now: datetime | None = None,
) -> bool:
    """Atomically transition one due pending outbox row to processing.

    This is deliberately a worker-owned transaction.  Callers must finish the
    transaction before invoking an adapter so delivery has a durable claim.
    """
    parsed_id = _as_uuid(outbox_id)
    if parsed_id is None:
        return False
    claimed_at = _now(now)
    try:
        if _dialect_name(db) == "postgresql":
            row = (
                db.query(NotificationOutbox)
                .filter(
                    NotificationOutbox.id == parsed_id,
                    _outbox_claimable(claimed_at),
                )
                .with_for_update(skip_locked=True)
                .first()
            )
            if row is None:
                db.rollback()
                return False
            row.status = "processing"
            row.claimed_at = claimed_at
            row.next_attempt_at = None
            row.attempts += 1
        else:
            updated = (
                db.query(NotificationOutbox)
                .filter(
                    NotificationOutbox.id == parsed_id,
                    _outbox_claimable(claimed_at),
                )
                .update(
                    {
                        NotificationOutbox.status: "processing",
                        NotificationOutbox.claimed_at: claimed_at,
                        NotificationOutbox.next_attempt_at: None,
                        NotificationOutbox.attempts: NotificationOutbox.attempts + 1,
                    },
                    synchronize_session="fetch",
                )
            )
            if updated != 1:
                db.rollback()
                return False
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def _claim_delivery(
    db: Session,
    delivery_id: object,
    *,
    now: datetime,
) -> str | None:
    parsed_id = _as_uuid(delivery_id)
    if parsed_id is None:
        return None
    claimed_at = _now(now)
    claim_token = str(uuid4())
    try:
        if _dialect_name(db) == "postgresql":
            row = (
                db.query(NotificationDelivery)
                .filter(
                    NotificationDelivery.id == parsed_id,
                    _delivery_claimable(claimed_at),
                )
                .with_for_update(skip_locked=True)
                .first()
            )
            if row is None:
                db.rollback()
                return None
            row.status = "processing"
            row.next_attempt_at = None
            row.attempts += 1
            row.claim_token = claim_token
            row.claimed_at = claimed_at
        else:
            updated = (
                db.query(NotificationDelivery)
                .filter(
                    NotificationDelivery.id == parsed_id,
                    _delivery_claimable(claimed_at),
                )
                .update(
                    {
                        NotificationDelivery.status: "processing",
                        NotificationDelivery.next_attempt_at: None,
                        NotificationDelivery.attempts: NotificationDelivery.attempts + 1,
                        NotificationDelivery.claim_token: claim_token,
                        NotificationDelivery.claimed_at: claimed_at,
                        NotificationDelivery.updated_at: claimed_at,
                    },
                    synchronize_session="fetch",
                )
            )
            if updated != 1:
                db.rollback()
                return None
        db.commit()
        return claim_token
    except Exception:
        db.rollback()
        raise


def _list_matching_subscriptions(
    db: Session,
    outbox: NotificationOutbox,
) -> list[NotificationSubscription]:
    if outbox.project_id is None:
        return []
    candidates = (
        db.query(NotificationSubscription)
        .join(
            NotificationEndpoint,
            NotificationEndpoint.id == NotificationSubscription.endpoint_id,
        )
        .filter(
            NotificationSubscription.project_id == outbox.project_id,
            NotificationSubscription.enabled.is_(True),
            NotificationEndpoint.project_id == outbox.project_id,
            NotificationEndpoint.enabled.is_(True),
        )
        .order_by(NotificationSubscription.created_at, NotificationSubscription.id)
        .all()
    )
    event_severity = SEVERITY_ORDER.get(outbox.severity)
    if event_severity is None:
        return []
    matching: list[NotificationSubscription] = []
    for subscription in candidates:
        event_types = subscription.event_types
        if not isinstance(event_types, (list, tuple)):
            continue
        if outbox.event_type not in event_types:
            continue
        minimum = SEVERITY_ORDER.get(subscription.minimum_severity)
        if minimum is None or event_severity < minimum:
            continue
        matching.append(subscription)
    return matching


def _fan_out_deliveries(db: Session, outbox: NotificationOutbox) -> list[UUID]:
    dialect_name = _dialect_name(db)
    for subscription in _list_matching_subscriptions(db, outbox):
        key = _delivery_key(outbox, subscription)
        values = {
            "outbox_id": outbox.id,
            "subscription_id": subscription.id,
            "endpoint_id": subscription.endpoint_id,
            "idempotency_key": key,
            "status": "pending",
        }
        if dialect_name == "postgresql":
            statement = postgresql_insert(NotificationDelivery).values(**values)
        elif dialect_name == "sqlite":
            statement = sqlite_insert(NotificationDelivery).values(**values)
        else:
            raise RuntimeError(
                "notification delivery fan-out requires PostgreSQL or SQLite"
            )
        db.execute(statement.on_conflict_do_nothing(
            index_elements=[NotificationDelivery.idempotency_key],
        ))
    db.flush()
    return [
        row.id
        for row in db.query(NotificationDelivery).filter(
            NotificationDelivery.outbox_id == outbox.id,
        ).order_by(NotificationDelivery.created_at, NotificationDelivery.id).all()
    ]


def _reconcile_outbox_status(
    db: Session,
    outbox: NotificationOutbox,
) -> str:
    deliveries = db.query(NotificationDelivery).filter(
        NotificationDelivery.outbox_id == outbox.id,
    ).all()
    if not deliveries:
        outbox.status = "sent"
        outbox.next_attempt_at = None
        return outbox.status

    retry_rows = [row for row in deliveries if row.status == "retry"]
    if retry_rows:
        outbox.status = "pending"
        retry_times = [
            row.next_attempt_at
            for row in retry_rows
            if row.next_attempt_at is not None
        ]
        outbox.next_attempt_at = min(retry_times) if retry_times else None
        outbox.last_error_code = next(
            (row.last_error_code for row in retry_rows if row.last_error_code),
            None,
        )
        return outbox.status
    if any(row.status in {"pending", "processing"} for row in deliveries):
        outbox.status = "processing"
        outbox.next_attempt_at = None
        return outbox.status
    outbox.next_attempt_at = None
    if all(row.status == "sent" for row in deliveries):
        outbox.status = "sent"
        outbox.last_error_code = None
    elif any(row.status == "dead_letter" for row in deliveries):
        outbox.status = "dead_letter"
        outbox.last_error_code = next(
            (
                row.last_error_code
                for row in deliveries
                if row.status == "dead_letter" and row.last_error_code
            ),
            None,
        )
    else:
        outbox.status = "failed"
        outbox.last_error_code = next(
            (
                row.last_error_code
                for row in deliveries
                if row.status == "failed" and row.last_error_code
            ),
            None,
        )
    return outbox.status


def _lock_outbox_for_reconciliation(
    db: Session,
    outbox_id: UUID,
) -> NotificationOutbox | None:
    """Serialize PostgreSQL delivery finalizers before deriving outbox state."""
    query = db.query(NotificationOutbox).filter(NotificationOutbox.id == outbox_id)
    if _dialect_name(db) == "postgresql":
        query = query.with_for_update()
    return query.one_or_none()


def _prepare_deliveries(
    db: Session,
    outbox_id: UUID,
    *,
    now: datetime,
) -> list[UUID]:
    outbox = db.get(NotificationOutbox, outbox_id)
    if outbox is None or outbox.status != "processing":
        return []
    delivery_ids = _fan_out_deliveries(db, outbox)
    due_delivery_ids = [
        row.id
        for row in db.query(NotificationDelivery).filter(
            NotificationDelivery.id.in_(delivery_ids),
            _delivery_claimable(now),
        ).order_by(NotificationDelivery.created_at, NotificationDelivery.id).all()
    ]
    if not due_delivery_ids:
        _reconcile_outbox_status(db, outbox)
    db.commit()
    return due_delivery_ids


def _role_recipients(
    db: Session,
    project: Project,
    subscription: NotificationSubscription,
) -> tuple[UUID, ...]:
    recipients: list[UUID] = []
    roles = subscription.recipient_roles
    normalized_roles = {
        role for role in roles
        if isinstance(role, str) and role in {"owner", "editor", "operator", "viewer"}
    } if isinstance(roles, (list, tuple)) else set()

    if "owner" in normalized_roles and project.owner_id is not None:
        recipients.append(project.owner_id)
    member_roles = normalized_roles - {"owner"}
    if member_roles:
        members = (
            db.query(ProjectMember)
            .filter(
                ProjectMember.project_id == project.id,
                ProjectMember.role.in_(member_roles),
            )
            .order_by(ProjectMember.created_at, ProjectMember.id)
            .all()
        )
        for member in members:
            if member.user_id not in recipients:
                recipients.append(member.user_id)

    explicit_values = subscription.recipient_user_ids
    explicit_ids = [
        parsed for parsed in (
            _as_uuid(value)
            for value in explicit_values
        ) if parsed is not None
    ] if isinstance(explicit_values, (list, tuple)) else []
    if explicit_ids:
        member_ids = {
            member.user_id
            for member in db.query(ProjectMember).filter(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id.in_(explicit_ids),
            ).all()
        }
        if project.owner_id is not None:
            member_ids.add(project.owner_id)
        for user_id in explicit_ids:
            if user_id in member_ids and user_id not in recipients:
                recipients.append(user_id)
    return tuple(recipients)


def _event_from_outbox(outbox: NotificationOutbox) -> DomainEvent:
    occurred_at = outbox.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    return DomainEvent(
        event_id=outbox.event_id,
        idempotency_key=outbox.idempotency_key,
        event_type=outbox.event_type,
        severity=outbox.severity,
        occurred_at=occurred_at,
        project_id=outbox.project_id,
        actor_id=outbox.actor_id,
        resource_type=outbox.resource_type,
        resource_id=outbox.resource_id,
        payload=outbox.payload if isinstance(outbox.payload, dict) else {},
    )


def _retryable(result: DeliveryResult) -> bool:
    if result.status != "retry":
        return False
    provider_status = _safe_provider_status(result.provider_status)
    if provider_status is not None:
        return provider_status == 408 or provider_status == 429 or provider_status >= 500
    return _safe_error_code(result.error_code) in RETRYABLE_ERROR_CODES


def _operator_alert_recipient(db: Session, outbox: NotificationOutbox) -> UUID | None:
    if outbox.project_id is None:
        return outbox.actor_id
    operator = (
        db.query(ProjectMember)
        .filter(
            ProjectMember.project_id == outbox.project_id,
            ProjectMember.role == "operator",
        )
        .order_by(ProjectMember.created_at, ProjectMember.id)
        .first()
    )
    if operator is not None:
        return operator.user_id
    project = db.get(Project, outbox.project_id)
    return project.owner_id if project is not None else outbox.actor_id


def _create_dead_letter_alert(
    db: Session,
    outbox: NotificationOutbox,
    delivery: NotificationDelivery,
) -> None:
    recipient_user_id = _operator_alert_recipient(db, outbox)
    if recipient_user_id is None:
        return
    values = {
        "id": uuid4(),
        "recipient_user_id": recipient_user_id,
        "project_id": outbox.project_id,
        "event_id": outbox.event_id,
        "event_type": "notification.dead_letter",
        "deduplication_key": f"notification.dead_letter:{outbox.event_id}",
        "severity": "critical",
        "title": "Notification delivery failed",
        "body": "A notification delivery reached its retry limit.",
        "payload": {
            "outbox_id": str(outbox.id),
            "delivery_id": str(delivery.id),
            "error_code": _safe_error_code(delivery.last_error_code),
        },
    }
    dialect_name = _dialect_name(db)
    if dialect_name == "postgresql":
        statement = postgresql_insert(InAppNotification).values(**values)
    elif dialect_name == "sqlite":
        statement = sqlite_insert(InAppNotification).values(**values)
    else:
        raise RuntimeError(
            "notification dead-letter deduplication requires PostgreSQL or SQLite"
        )
    db.execute(statement.on_conflict_do_nothing(
        index_elements=[InAppNotification.deduplication_key],
    ))


def _record_result(
    db: Session,
    delivery: NotificationDelivery,
    outbox: NotificationOutbox,
    result: DeliveryResult,
    *,
    claim_token: str,
    now: datetime,
    jitter: float,
) -> str:
    delivery_id = delivery.id
    outbox_id = outbox.id
    completed_at = _now(now)
    lease_attempt = delivery.attempts
    error_code = _safe_error_code(result.error_code)
    values: dict[object, object] = {
        NotificationDelivery.provider_status: _safe_provider_status(result.provider_status),
        NotificationDelivery.provider_metadata: {},
        NotificationDelivery.claim_token: None,
        NotificationDelivery.claimed_at: None,
        NotificationDelivery.updated_at: completed_at,
    }
    create_dead_letter_alert = False
    if result.status == "sent":
        values.update({
            NotificationDelivery.status: "sent",
            NotificationDelivery.last_error_code: None,
            NotificationDelivery.next_attempt_at: None,
        })
        outbox_error_code = None
    elif _retryable(result) and delivery.attempts < settings.notification_delivery_max_attempts:
        values.update({
            NotificationDelivery.status: "retry",
            NotificationDelivery.last_error_code: error_code,
            NotificationDelivery.next_attempt_at: next_retry_at(
                lease_attempt,
                completed_at,
                jitter,
            ),
        })
        outbox_error_code = error_code
    elif _retryable(result):
        values.update({
            NotificationDelivery.status: "dead_letter",
            NotificationDelivery.last_error_code: error_code,
            NotificationDelivery.next_attempt_at: None,
        })
        outbox_error_code = error_code
        create_dead_letter_alert = True
    else:
        values.update({
            NotificationDelivery.status: "failed",
            NotificationDelivery.last_error_code: error_code,
            NotificationDelivery.next_attempt_at: None,
        })
        outbox_error_code = error_code

    updated = (
        db.query(NotificationDelivery)
        .filter(
            NotificationDelivery.id == delivery_id,
            NotificationDelivery.status == "processing",
            NotificationDelivery.claim_token == claim_token,
        )
        .update(values, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        persisted_outbox = db.get(NotificationOutbox, outbox_id)
        return persisted_outbox.status if persisted_outbox is not None else "failed"

    db.expire_all()
    current_delivery = db.get(NotificationDelivery, delivery_id)
    current_outbox = _lock_outbox_for_reconciliation(db, outbox_id)
    if current_delivery is None or current_outbox is None:
        db.rollback()
        return "failed"
    current_outbox.last_error_code = outbox_error_code
    if create_dead_letter_alert:
        _create_dead_letter_alert(db, current_outbox, current_delivery)
    outcome = _reconcile_outbox_status(db, current_outbox)
    db.commit()
    return outcome


def _delivery_context(
    db: Session,
    delivery_id: UUID,
    *,
    claim_token: str,
) -> tuple[
    NotificationDelivery,
    NotificationOutbox,
    NotificationEndpoint,
    NotificationSubscription,
    DomainEvent,
    tuple[UUID, ...],
] | None:
    delivery = db.get(NotificationDelivery, delivery_id)
    if (
        delivery is None
        or delivery.status != "processing"
        or delivery.claim_token != claim_token
    ):
        return None
    outbox = db.get(NotificationOutbox, delivery.outbox_id)
    endpoint = db.get(NotificationEndpoint, delivery.endpoint_id)
    subscription = db.get(NotificationSubscription, delivery.subscription_id)
    if outbox is None or endpoint is None or subscription is None:
        return None
    project = db.get(Project, outbox.project_id) if outbox.project_id else None
    recipients = _role_recipients(db, project, subscription) if project is not None else ()
    try:
        event = _event_from_outbox(outbox)
    except (TypeError, ValueError):
        return None
    return delivery, outbox, endpoint, subscription, event, recipients


def _send_delivery(
    delivery_id: UUID,
    *,
    clock: Callable[[], datetime],
    jitter: float,
    session_factory: Callable[[], Session],
    adapter_factory: Callable[[Session], Any],
) -> str | None:
    with session_factory() as claim_db:
        claim_token = _claim_delivery(claim_db, delivery_id, now=clock())
        if claim_token is None:
            return None

    with session_factory() as db:
        context = _delivery_context(db, delivery_id, claim_token=claim_token)
        if context is None:
            delivery = db.get(NotificationDelivery, delivery_id)
            if (
                delivery is None
                or delivery.status != "processing"
                or delivery.claim_token != claim_token
            ):
                db.rollback()
                return None
            outbox = db.get(NotificationOutbox, delivery.outbox_id) if delivery else None
            if delivery is None or outbox is None:
                db.rollback()
                return None
            result = DeliveryResult("failed", "NOTIFICATION_DELIVERY_CONTEXT_INVALID")
            return _record_result(
                db,
                delivery,
                outbox,
                result,
                claim_token=claim_token,
                now=clock(),
                jitter=jitter,
            )
        delivery, outbox, endpoint, _subscription, event, recipients = context
        if not endpoint.enabled:
            result = DeliveryResult("failed", "NOTIFICATION_ENDPOINT_DISABLED")
        else:
            try:
                result = adapter_factory(db).send(
                    endpoint=endpoint,
                    event=event,
                    delivery_key=delivery.idempotency_key,
                    recipient_user_ids=recipients,
                )
            except (OSError, TimeoutError):
                result = DeliveryResult("retry", "NOTIFICATION_PROVIDER_UNAVAILABLE")
        return _record_result(
            db,
            delivery,
            outbox,
            result,
            claim_token=claim_token,
            now=clock(),
            jitter=jitter,
        )


def _persisted_outbox_status(
    outbox_id: UUID,
    *,
    session_factory: Callable[[], Session],
) -> str:
    with session_factory() as db:
        outbox = db.get(NotificationOutbox, outbox_id)
        if outbox is None:
            return "failed"
        if outbox.status in {"sent", "failed", "dead_letter"}:
            return outbox.status
        if outbox.status == "pending":
            return "retry"
        return outbox.status


def execute_notification_delivery(
    outbox_id: object,
    *,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    jitter: float = 0.0,
    session_factory: Callable[[], Session] | None = None,
    adapter_factory: Callable[[Session], Any] | None = None,
) -> str:
    """Claim, fan out, and deliver one persisted outbox event.

    The adapter is intentionally built only after the durable claim session has
    committed and closed.  The optional factories keep the task deterministic
    for isolated persistence tests without weakening production wiring.
    """
    parsed_id = _as_uuid(outbox_id)
    if parsed_id is None:
        return "failed"
    if now is not None and clock is not None:
        raise ValueError("now and clock cannot be used together")
    if clock is not None:
        current_time = lambda: _now(clock())
    elif now is not None:
        fixed_time = _now(now)
        current_time = lambda: fixed_time
    else:
        current_time = _now
    resolved_session_factory = session_factory or SessionLocal
    resolved_adapter_factory = adapter_factory or (
        lambda db: NotificationChannelRouter(db, settings)
    )

    with resolved_session_factory() as claim_db:
        claimed = claim_outbox(claim_db, parsed_id, now=current_time())
    if not claimed:
        return _persisted_outbox_status(
            parsed_id,
            session_factory=resolved_session_factory,
        )

    with resolved_session_factory() as db:
        delivery_ids = _prepare_deliveries(db, parsed_id, now=current_time())
    if not delivery_ids:
        return _persisted_outbox_status(
            parsed_id,
            session_factory=resolved_session_factory,
        )

    outcomes: list[str] = []
    for delivery_id in delivery_ids:
        outcome = _send_delivery(
            delivery_id,
            clock=current_time,
            jitter=jitter,
            session_factory=resolved_session_factory,
            adapter_factory=resolved_adapter_factory,
        )
        if outcome is not None:
            outcomes.append(outcome)
    if not outcomes:
        return _persisted_outbox_status(
            parsed_id,
            session_factory=resolved_session_factory,
        )
    return _persisted_outbox_status(
        parsed_id,
        session_factory=resolved_session_factory,
    )


def enqueue_due_notification_tasks(
    *,
    now: datetime | None = None,
    limit: int = 100,
    session_factory: Callable[[], Session] | None = None,
) -> int:
    """Queue due outbox IDs without changing their worker-owned state."""
    if not 1 <= limit <= 500:
        raise ValueError("notification dispatch limit must be between 1 and 500")
    current_time = _now(now)
    resolved_session_factory = session_factory or SessionLocal
    with resolved_session_factory() as db:
        outbox_ids = [
            row[0]
            for row in db.query(NotificationOutbox.id).filter(
                _outbox_claimable(current_time),
            ).order_by(
                NotificationOutbox.created_at,
                NotificationOutbox.id,
            ).limit(limit).all()
        ]
    for outbox_id in outbox_ids:
        celery_app.send_task(
            "ml_platform.deliver_notifications",
            args=[str(outbox_id)],
        )
    return len(outbox_ids)


@celery_app.task(name="ml_platform.deliver_notifications")
def deliver_notifications_task(outbox_id: str):
    return execute_notification_delivery(outbox_id)


@celery_app.task(name="ml_platform.enqueue_due_notifications")
def enqueue_due_notifications_task():
    return enqueue_due_notification_tasks()
