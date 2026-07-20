"""Audit-safe request context and change redaction primitives."""

from contextlib import contextmanager
from dataclasses import dataclass, field
import uuid

from app.models.access import AuditEvent
from app.services.project_access import (
    ROLE_PERMISSIONS,
    ProjectAccessError,
)


SENSITIVE_KEY_PARTS = frozenset({
    "password",
    "token",
    "secret",
    "credential",
    "authorization",
    "cookie",
    "content",
    "data",
    "path",
})


def _is_sensitive(key: object) -> bool:
    normalized = str(key).lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _redact_value(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _is_sensitive(key) else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    return value


def redact_changes(value: dict, *, allowed: set[str]) -> dict:
    return {
        key: "[REDACTED]" if _is_sensitive(key) else _redact_value(item)
        for key, item in value.items()
        if key in allowed
    }


def audit_request_context(request) -> tuple[uuid.UUID, str | None]:
    request_id = getattr(request.state, "request_id", None)
    if not isinstance(request_id, uuid.UUID):
        request_id = uuid.uuid4()
    source_ip = request.client.host if request.client is not None else None
    return request_id, source_ip


@dataclass(frozen=True)
class AuditIntent:
    project_id: uuid.UUID
    action: str
    resource_type: str
    resource_id: str | None = None
    changes: dict = field(default_factory=dict)


class AuditService:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    @staticmethod
    def _event(
        *,
        intent: AuditIntent,
        actor_id,
        actor_username: str,
        request_id: uuid.UUID,
        source_ip: str | None,
        result: str,
        changes: dict,
        error_code: str | None = None,
    ) -> AuditEvent:
        return AuditEvent(
            project_id=intent.project_id,
            actor_id=actor_id,
            actor_username=actor_username,
            action=intent.action,
            resource_type=intent.resource_type,
            resource_id=intent.resource_id,
            result=result,
            request_id=request_id,
            source_ip=source_ip,
            changes=changes,
            error_code=error_code,
        )

    def _record_failed(
        self,
        *,
        intent,
        actor_id,
        actor_username,
        request_id,
        source_ip,
        changes,
        error_code,
    ) -> None:
        with self.session_factory() as audit_db:
            audit_db.add(self._event(
                intent=intent,
                actor_id=actor_id,
                actor_username=actor_username,
                request_id=request_id,
                source_ip=source_ip,
                result="failed",
                changes=changes,
                error_code=error_code,
            ))
            audit_db.commit()

    @contextmanager
    def project_action(
        self,
        db,
        *,
        request,
        actor,
        access,
        permission: str,
        intent: AuditIntent,
        allowed_changes: set[str],
    ):
        actor_id = actor.id
        actor_username = actor.username
        request_id, source_ip = audit_request_context(request)
        changes = redact_changes(intent.changes, allowed=allowed_changes)

        if access is None:
            raise ProjectAccessError("PROJECT_NOT_FOUND", hidden=True)
        if permission not in ROLE_PERMISSIONS[access.role]:
            db.add(self._event(
                intent=intent,
                actor_id=actor_id,
                actor_username=actor_username,
                request_id=request_id,
                source_ip=source_ip,
                result="denied",
                changes=changes,
                error_code="PROJECT_PERMISSION_DENIED",
            ))
            db.commit()
            raise ProjectAccessError("PROJECT_PERMISSION_DENIED", hidden=False)

        try:
            yield
            db.add(self._event(
                intent=intent,
                actor_id=actor_id,
                actor_username=actor_username,
                request_id=request_id,
                source_ip=source_ip,
                result="success",
                changes=changes,
            ))
            db.commit()
        except Exception as error:
            db.rollback()
            error_code = getattr(error, "code", "PROJECT_ACTION_FAILED")
            self._record_failed(
                intent=intent,
                actor_id=actor_id,
                actor_username=actor_username,
                request_id=request_id,
                source_ip=source_ip,
                changes=changes,
                error_code=error_code,
            )
            raise
