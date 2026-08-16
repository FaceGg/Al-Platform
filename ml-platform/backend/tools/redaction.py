"""Shared redaction primitives for acceptance evidence and controlled receivers."""

from __future__ import annotations

import re


# The authority component is intentionally greedy through the final ``@`` before
# a path. This also removes malformed raw ``@`` characters in password values.
_URL_USERINFO = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^\s/]*@",
    re.IGNORECASE,
)
_JSON_SECRET_VALUE = re.compile(
    r'(?i)("[^"\n]*(?:password|secret|token|authorization|api[_-]?key|access[_-]?key|client[_-]?secret|credential)[^"\n]*"\s*:\s*)"(?:\\.|[^"\\])*"',
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([a-z0-9._-]*(?:password|secret|token|authorization|api[_-]?key|access[_-]?key|client[_-]?secret|credential)[a-z0-9._-]*)\s*[:=]\s*([^\s,;]+)",
)
_AUTH_HEADER = re.compile(
    r"(?i)\b(authorization|proxy-authorization|x-api-key)\s*[:=]\s*(?:(?:basic|bearer)\s+)?[^\s,;]+",
)
_BARE_SENSITIVE_TOKEN = re.compile(
    r"(?i)(?<![a-z0-9_])[a-z0-9._-]*(?:password|secret|token|authorization|api[_-]?key|access[_-]?key|client[_-]?secret|credential)[a-z0-9._-]*(?![a-z0-9_])",
)


def redact_text(value: str) -> str:
    """Remove credential values from untrusted diagnostic text."""
    redacted = _URL_USERINFO.sub(r"\g<scheme>[redacted]@", value)
    redacted = _JSON_SECRET_VALUE.sub(r'\1"[redacted]"', redacted)
    redacted = _AUTH_HEADER.sub(r"\1: [redacted]", redacted)
    redacted = _SECRET_ASSIGNMENT.sub(r"\1=[redacted]", redacted)
    return _BARE_SENSITIVE_TOKEN.sub("[redacted]", redacted)
