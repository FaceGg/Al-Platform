"""Platform-wide audit helpers with explicit transaction ownership."""

from dataclasses import dataclass, field

from sqlalchemy.orm import sessionmaker

from app.models.platform_audit import PlatformAuditEvent
from app.services.audit import audit_request_context, redact_changes


@dataclass(frozen=True)
class PlatformAuditIntent:
    action: str
    resource_type: str
    resource_id: str | None = None
    changes: dict[str, object] = field(default_factory=dict)


def record_platform_event(
    db,
    *,
    actor,
    request,
    intent: PlatformAuditIntent,
    result: str,
    error_code: str | None = None,
) -> PlatformAuditEvent:
    """Add a redacted event without committing the caller's transaction."""
    request_id, source_ip = audit_request_context(request)
    event = PlatformAuditEvent(
        actor_id=getattr(actor, "id", None),
        actor_username=getattr(actor, "username", "anonymous"),
        action=intent.action,
        resource_type=intent.resource_type,
        resource_id=intent.resource_id,
        result=result,
        request_id=request_id,
        source_ip=source_ip,
        changes=redact_changes(intent.changes, allowed=set(intent.changes)),
        error_code=error_code,
    )
    db.add(event)
    return event


@dataclass(frozen=True)
class _PlatformAuditActor:
    id: object | None
    username: str


def record_failed_platform_event(
    db,
    *,
    actor,
    request,
    intent: PlatformAuditIntent,
    error_code: str,
) -> None:
    """Rollback business state, then persist a stable failed-event record."""
    actor_snapshot = _PlatformAuditActor(
        id=getattr(actor, "id", None),
        username=getattr(actor, "username", "anonymous"),
    )
    bind = db.get_bind()
    db.rollback()
    with sessionmaker(bind=bind)() as audit_db:
        record_platform_event(
            audit_db,
            actor=actor_snapshot,
            request=request,
            intent=intent,
            result="failed",
            error_code=error_code,
        )
        audit_db.commit()
