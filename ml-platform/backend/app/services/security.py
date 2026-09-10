"""Small, dependency-free security gates shared by HTTP and upload paths.

The application has several HTTP surfaces (the platform API and the
annotator portal).  Keeping origin/CSRF, rate-limit and upload checks in one
module makes the failure codes stable and lets the test suite exercise the
policy without starting a broker or a second process.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import secrets
import threading
import time
from pathlib import PurePath
from typing import Iterable
from urllib.parse import urlsplit

from fastapi import HTTPException


_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def expand_local_dev_origins(origins: Iterable[str]) -> frozenset[str]:
    """Add bounded loopback aliases used by local browser/Vite development.

    Production callers must pass their exact origins. This helper is only used
    by the local application mode and never creates a wildcard policy.
    """
    normalized = {origin for origin in (_origin(item) for item in origins) if origin}
    for origin in tuple(normalized):
        parsed = urlsplit(origin)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "http" or hostname not in {"localhost", "127.0.0.1", "::1"}:
            continue
        port = parsed.port
        if port is None:
            continue
        ports = {port}
        # Vite moves from its default port to the next port when occupied.
        if port == 5173:
            ports.add(5174)
        for alias_host in ("localhost", "127.0.0.1", "[::1]"):
            for alias_port in ports:
                normalized.add(f"http://{alias_host}:{alias_port}")
    return frozenset(normalized)


@dataclass(frozen=True)
class SecurityPolicy:
    """HTTP security policy for a single application surface."""

    allowed_origins: frozenset[str]
    csrf_cookie_name: str = "csrf_token"
    csrf_header_name: str = "X-CSRF-Token"
    state_changing_methods: frozenset[str] = _STATE_CHANGING_METHODS

    def __post_init__(self) -> None:
        normalized = frozenset(filter(None, (_origin(item) for item in self.allowed_origins)))
        if not normalized or "*" in self.allowed_origins:
            raise ValueError("SECURITY_ORIGIN_POLICY_INVALID")
        object.__setattr__(self, "allowed_origins", normalized)


def enforce_request_security(request, policy: SecurityPolicy) -> None:
    """Reject untrusted origins and cookie state changes.

    Bearer-token requests do not need a CSRF token.  A request carrying a
    cookie does: it must provide a matching double-submit token and a trusted
    Origin or Referer.  This deliberately runs before the CORS middleware so
    an unknown preflight is a stable 403 instead of a framework-specific 400.
    """

    origin_header = request.headers.get("origin")
    request_origin = _origin(origin_header)
    if origin_header and request_origin not in policy.allowed_origins:
        raise _http_error(403, "CORS_ORIGIN_FORBIDDEN", "request origin is not allowed")

    # Preflight has no application cookie and must be accepted only for a
    # registered origin.  Unknown origins returned above as 403.
    if request.method.upper() == "OPTIONS":
        return

    method = request.method.upper()
    if method not in policy.state_changing_methods:
        return
    cookies = request.cookies
    if not cookies:
        return

    referer_header = request.headers.get("referer")
    referer_origin = _origin(referer_header)
    if referer_header and referer_origin not in policy.allowed_origins:
        raise _http_error(403, "CSRF_ORIGIN_FORBIDDEN", "request referer is not allowed")
    if request_origin is None and referer_origin is None:
        raise _http_error(403, "CSRF_ORIGIN_REQUIRED", "cookie state changes require Origin or Referer")

    expected = cookies.get(policy.csrf_cookie_name)
    supplied = request.headers.get(policy.csrf_header_name)
    if not expected or not supplied:
        raise _http_error(403, "CSRF_TOKEN_REQUIRED", "csrf token is required")
    if not secrets.compare_digest(str(expected), str(supplied)):
        raise _http_error(403, "CSRF_TOKEN_INVALID", "csrf token is invalid")


@dataclass(frozen=True)
class RateLimitPolicy:
    capacity: int
    window_seconds: int

    def __post_init__(self) -> None:
        if isinstance(self.capacity, bool) or self.capacity < 1 or self.window_seconds < 1:
            raise ValueError("RATE_LIMIT_POLICY_INVALID")


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class SlidingWindowRateLimiter:
    """Thread-safe bounded sliding-window limiter for a process-local edge.

    Production deployments can replace the store with the existing Redis
    token-bucket implementation.  The process-local implementation is still
    useful as a fail-closed first hop and for isolated portal processes.
    """

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, policy: RateLimitPolicy) -> RateLimitDecision:
        if not isinstance(key, str) or not key:
            raise ValueError("RATE_LIMIT_KEY_INVALID")
        now = float(self._clock())
        cutoff = now - policy.window_seconds
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= policy.capacity:
                retry = max(1, int(events[0] + policy.window_seconds - now + 0.999))
                return RateLimitDecision(False, 0, retry)
            events.append(now)
            return RateLimitDecision(True, policy.capacity - len(events), 0)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


LOGIN_IP_LIMIT = RateLimitPolicy(5, 15 * 60)
LOGIN_ACCOUNT_LIMIT = RateLimitPolicy(10, 15 * 60)
REGISTRATION_LIMIT = RateLimitPolicy(10, 60 * 60)
PASSWORD_RESET_LIMIT = RateLimitPolicy(5, 60 * 60)
BULK_LABEL_LIMIT = RateLimitPolicy(120, 60)


_rate_limiter = SlidingWindowRateLimiter()


def rate_limiter() -> SlidingWindowRateLimiter:
    return _rate_limiter


def enforce_rate_limit(key: str, policy: RateLimitPolicy, *, limiter: SlidingWindowRateLimiter | None = None) -> None:
    decision = (limiter or _rate_limiter).check(key, policy)
    if not decision.allowed:
        error = _http_error(429, "RATE_LIMITED", "request rate limit exceeded")
        # Retry-After is attached without exposing account existence or the
        # configured capacity in the response body.
        error.headers = {"Retry-After": str(decision.retry_after_seconds)}
        raise error


def validate_upload_filename(filename: str, *, max_length: int = 255) -> str:
    if not isinstance(filename, str) or not filename or len(filename) > max_length:
        raise ValueError("UPLOAD_PATH_INVALID")
    if "\x00" in filename or filename.startswith(("/", "\\")):
        raise ValueError("UPLOAD_PATH_INVALID")
    normalized = filename.replace("\\", "/")
    if normalized != filename or ".." in PurePath(normalized).parts:
        raise ValueError("UPLOAD_PATH_INVALID")
    if PurePath(filename).name != filename:
        raise ValueError("UPLOAD_PATH_INVALID")
    return filename


def validate_upload_magic(source_format: str, prefix: bytes) -> str:
    """Validate a bounded prefix against a declared upload format."""

    fmt = str(source_format or "").lower().lstrip(".")
    prefix = bytes(prefix or b"")
    stripped = prefix.lstrip()
    if fmt in {"xlsx", "excel", "zip"}:
        valid = prefix.startswith(b"PK\x03\x04")
    elif fmt == "xls":
        valid = prefix.startswith((b"PK\x03\x04", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"))
    elif fmt == "parquet":
        valid = prefix.startswith(b"PAR1")
    elif fmt == "json":
        valid = stripped.startswith((b"{", b"["))
    elif fmt == "xml":
        valid = stripped.startswith(b"<")
    elif fmt in {"csv", "tsv"}:
        valid = bool(prefix) and not prefix.startswith((b"PK\x03\x04", b"PAR1")) and b"\x00" not in prefix
    else:
        # Unknown formats are checked by their parser/consumer.  Do not
        # invent a magic number for opaque model or archive formats.
        return fmt
    if not valid:
        raise ValueError("UPLOAD_MAGIC_INVALID")
    return fmt


def csrf_token() -> str:
    return secrets.token_urlsafe(32)


__all__ = [
    "BULK_LABEL_LIMIT",
    "LOGIN_ACCOUNT_LIMIT",
    "LOGIN_IP_LIMIT",
    "PASSWORD_RESET_LIMIT",
    "REGISTRATION_LIMIT",
    "RateLimitDecision",
    "RateLimitPolicy",
    "SecurityPolicy",
    "expand_local_dev_origins",
    "SlidingWindowRateLimiter",
    "csrf_token",
    "enforce_rate_limit",
    "enforce_request_security",
    "rate_limiter",
    "validate_upload_filename",
    "validate_upload_magic",
]
