"""Strict SSRF and payload boundaries for notification Webhooks."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import ipaddress
import json
import socket
from urllib.parse import urlsplit


DEFAULT_NOTIFICATION_PAYLOAD_BYTES = 65_536
DEFAULT_HTTPS_PORT = 443
MAX_WEBHOOK_URL_LENGTH = 2_048
WECOM_HOST = "qyapi.weixin.qq.com"
WECOM_PATHS = frozenset({"/cgi-bin/webhook/send", "/cgi-bin/message/send"})
METADATA_HOSTS = frozenset({"metadata", "metadata.google.internal"})


class WebhookSecurityError(RuntimeError):
    """Stable public-safe endpoint policy failure."""

    def __init__(self, code: str = "NOTIFICATION_ENDPOINT_FORBIDDEN") -> None:
        super().__init__(code)
        self.code = code


def canonical_json_bytes(
    value: object,
    *,
    max_payload_bytes: int = DEFAULT_NOTIFICATION_PAYLOAD_BYTES,
) -> bytes:
    """Serialize a deterministic JSON body and reject over-limit payloads."""
    if not isinstance(max_payload_bytes, int) or max_payload_bytes <= 0:
        raise WebhookSecurityError("NOTIFICATION_PAYLOAD_INVALID")
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise WebhookSecurityError("NOTIFICATION_PAYLOAD_INVALID") from error
    if len(encoded) > max_payload_bytes:
        raise WebhookSecurityError("NOTIFICATION_PAYLOAD_TOO_LARGE")
    return encoded


def _resolve_host(host: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise WebhookSecurityError("NOTIFICATION_ENDPOINT_UNRESOLVABLE") from error
    return [record[4][0] for record in records]


def _resolved_addresses(records: Iterable[object]) -> list[str]:
    addresses: list[str] = []
    for record in records:
        if isinstance(record, str):
            addresses.append(record)
        elif isinstance(record, tuple) and record:
            sockaddr = record[-1]
            if isinstance(sockaddr, tuple) and sockaddr:
                addresses.append(str(sockaddr[0]))
    if not addresses:
        raise WebhookSecurityError("NOTIFICATION_ENDPOINT_UNRESOLVABLE")
    return addresses


def _normalized_allowlist(allowlist: Iterable[str]) -> frozenset[str]:
    normalized: set[str] = set()
    for candidate in allowlist:
        if not isinstance(candidate, str):
            continue
        host = candidate.strip().rstrip(".").lower()
        if host and "://" not in host and "/" not in host:
            normalized.add(host)
    return frozenset(normalized)


def _is_restricted_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return True
    return not parsed.is_global


def _is_metadata_host(host: str) -> bool:
    return host in METADATA_HOSTS or host.endswith(".metadata.google.internal")


def validate_webhook_url(
    url: str,
    *,
    resolve: Callable[[str, int], Iterable[object]] | None = None,
    allowlist: Iterable[str] = (),
) -> str:
    """Validate a single HTTPS destination and resolve it before connection."""
    if not isinstance(url, str) or not url or len(url) > MAX_WEBHOOK_URL_LENGTH:
        raise WebhookSecurityError("NOTIFICATION_ENDPOINT_INVALID")
    try:
        parsed = urlsplit(url)
        port = parsed.port or DEFAULT_HTTPS_PORT
    except ValueError as error:
        raise WebhookSecurityError("NOTIFICATION_ENDPOINT_INVALID") from error

    host = (parsed.hostname or "").rstrip(".").lower()
    if (
        parsed.scheme.lower() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port != DEFAULT_HTTPS_PORT
    ):
        raise WebhookSecurityError("NOTIFICATION_ENDPOINT_FORBIDDEN")
    try:
        host.encode("ascii")
    except UnicodeEncodeError as error:
        raise WebhookSecurityError("NOTIFICATION_ENDPOINT_INVALID") from error

    is_allowlisted = host in _normalized_allowlist(allowlist)
    if (
        host == "localhost"
        or host.endswith(".localhost")
        or _is_metadata_host(host)
    ) and not is_allowlisted:
        raise WebhookSecurityError("NOTIFICATION_ENDPOINT_FORBIDDEN")

    resolver = resolve or _resolve_host
    try:
        addresses = _resolved_addresses(resolver(host, port))
    except WebhookSecurityError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise WebhookSecurityError("NOTIFICATION_ENDPOINT_UNRESOLVABLE") from error
    if not is_allowlisted and any(_is_restricted_address(address) for address in addresses):
        raise WebhookSecurityError("NOTIFICATION_ENDPOINT_FORBIDDEN")
    return url


def validate_wecom_url(
    url: str,
    *,
    resolve: Callable[[str, int], Iterable[object]] | None = None,
    allowlist: Iterable[str] = (),
) -> str:
    """Allow only documented WeCom robot or application message destinations."""
    validated = validate_webhook_url(url, resolve=resolve, allowlist=allowlist)
    parsed = urlsplit(validated)
    if parsed.hostname != WECOM_HOST or parsed.path not in WECOM_PATHS:
        raise WebhookSecurityError("NOTIFICATION_ENDPOINT_FORBIDDEN")
    query = parsed.query
    if parsed.path == "/cgi-bin/webhook/send" and "key=" not in query:
        raise WebhookSecurityError("NOTIFICATION_ENDPOINT_INVALID")
    if parsed.path == "/cgi-bin/message/send" and "access_token=" not in query:
        raise WebhookSecurityError("NOTIFICATION_ENDPOINT_INVALID")
    return validated
