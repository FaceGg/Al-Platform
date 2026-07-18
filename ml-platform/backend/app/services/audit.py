"""Audit-safe request context and change redaction primitives."""

import uuid


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
