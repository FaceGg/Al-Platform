"""Bounded notification channel adapters over safe domain events."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
import hashlib
import hmac
import re
import smtplib
import ssl
from typing import Literal, Protocol
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.events.domain import DomainEvent, to_storage_payload
from app.models.notifications import InAppNotification, NotificationEndpoint
from app.services.notification_crypto import NotificationCredentialError, decrypt_config
from app.services.webhook_security import (
    WebhookSecurityError,
    canonical_json_bytes,
    validate_wecom_url,
    validate_webhook_url,
)


DeliveryStatus = Literal["sent", "retry", "failed"]
MAX_EMAIL_RECIPIENTS = 50
MAX_CUSTOM_HEADERS = 16
HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")
FORBIDDEN_HEADERS = frozenset({
    "authorization",
    "content-type",
    "content-length",
    "cookie",
    "host",
    "idempotency-key",
    "proxy-authorization",
    "x-ml-platform-signature",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-real-ip",
})


@dataclass(frozen=True)
class DeliveryResult:
    status: DeliveryStatus
    error_code: str | None = None
    provider_status: int | None = None


class NotificationAdapter(Protocol):
    def send(
        self,
        *,
        endpoint: NotificationEndpoint,
        event: DomainEvent,
        delivery_key: str,
        recipient_user_ids: Iterable[UUID] | None = None,
    ) -> DeliveryResult: ...


def _safe_event_envelope(event: DomainEvent) -> dict[str, object]:
    occurred_at = event.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    return {
        "event_id": str(event.event_id),
        "idempotency_key": event.idempotency_key,
        "event_type": event.event_type,
        "severity": event.severity,
        "occurred_at": occurred_at.astimezone(timezone.utc).isoformat(),
        "project_id": str(event.project_id) if event.project_id else None,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "payload": to_storage_payload(event.payload),
    }


def _event_title(event: DomainEvent) -> str:
    return f"{event.severity.upper()}: {event.event_type}"


def _event_body(event: DomainEvent) -> str:
    resource = event.resource_type
    if event.resource_id:
        resource = f"{resource} {event.resource_id}"
    return f"{event.event_type} for {resource}"


def _http_result(response: object) -> DeliveryResult:
    status = getattr(response, "status_code", None)
    if not isinstance(status, int):
        return DeliveryResult("retry", "NOTIFICATION_PROVIDER_UNAVAILABLE")
    if 200 <= status < 300:
        return DeliveryResult("sent", provider_status=status)
    if status in {408, 429} or status >= 500:
        return DeliveryResult("retry", "NOTIFICATION_PROVIDER_RETRYABLE", status)
    return DeliveryResult("failed", "NOTIFICATION_PROVIDER_REJECTED", status)


def _network_error_result() -> DeliveryResult:
    return DeliveryResult("retry", "NOTIFICATION_PROVIDER_UNAVAILABLE")


def _normalized_recipient_ids(values: Iterable[UUID]) -> tuple[UUID, ...]:
    normalized: list[UUID] = []
    for value in values:
        try:
            user_id = value if isinstance(value, UUID) else UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            continue
        if user_id not in normalized:
            normalized.append(user_id)
    return tuple(normalized)


def _in_app_deduplication_key(delivery_key: str, recipient_user_id: UUID) -> str:
    return hashlib.sha256(
        f"{delivery_key}:{recipient_user_id}".encode("utf-8")
    ).hexdigest()


class InAppNotificationAdapter:
    def __init__(self, db: Session, config: Mapping[str, object]) -> None:
        self.db = db
        self.config = config

    def send(
        self,
        *,
        endpoint: NotificationEndpoint,
        event: DomainEvent,
        delivery_key: str,
        recipient_user_ids: Iterable[UUID] | None = None,
    ) -> DeliveryResult:
        configured_recipients = self.config.get("recipient_user_ids", [])
        source = configured_recipients if recipient_user_ids is None else recipient_user_ids
        if not isinstance(source, Iterable) or isinstance(source, (str, bytes)):
            return DeliveryResult("failed", "NOTIFICATION_RECIPIENT_INVALID")
        recipients = _normalized_recipient_ids(source)
        if not recipients:
            return DeliveryResult("failed", "NOTIFICATION_RECIPIENT_INVALID")
        payload = to_storage_payload(event.payload)
        dialect_name = self.db.get_bind().dialect.name
        if dialect_name == "postgresql":
            statement_factory = postgresql_insert
        elif dialect_name == "sqlite":
            statement_factory = sqlite_insert
        else:
            return DeliveryResult("failed", "NOTIFICATION_DELIVERY_STORAGE_UNSUPPORTED")
        for recipient_user_id in recipients:
            values = {
                "id": uuid4(),
                "recipient_user_id": recipient_user_id,
                "project_id": event.project_id,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "deduplication_key": _in_app_deduplication_key(
                    delivery_key,
                    recipient_user_id,
                ),
                "severity": event.severity,
                "title": _event_title(event),
                "body": _event_body(event),
                "payload": payload,
            }
            statement = statement_factory(InAppNotification).values(**values)
            self.db.execute(statement.on_conflict_do_nothing(
                index_elements=[InAppNotification.deduplication_key],
            ))
        self.db.flush()
        return DeliveryResult("sent")


class WebhookNotificationAdapter:
    def __init__(
        self,
        config: Mapping[str, object],
        *,
        http_client: object,
        timeout_seconds: int,
        max_payload_bytes: int,
        resolve: Callable[[str, int], Iterable[object]] | None,
        allowlist: Iterable[str],
    ) -> None:
        self.config = config
        self.http_client = http_client
        self.timeout_seconds = timeout_seconds
        self.max_payload_bytes = max_payload_bytes
        self.resolve = resolve
        self.allowlist = allowlist

    def _headers(self, body: bytes, delivery_key: str) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": delivery_key,
        }
        custom_headers = self.config.get("headers", {})
        if not isinstance(custom_headers, Mapping) or len(custom_headers) > MAX_CUSTOM_HEADERS:
            raise WebhookSecurityError("NOTIFICATION_ENDPOINT_INVALID")
        for name, value in custom_headers.items():
            normalized_name = str(name)
            normalized_value = str(value)
            if (
                not HEADER_NAME.fullmatch(normalized_name)
                or normalized_name.lower() in FORBIDDEN_HEADERS
                or "\r" in normalized_value
                or "\n" in normalized_value
                or len(normalized_value) > 512
            ):
                raise WebhookSecurityError("NOTIFICATION_ENDPOINT_FORBIDDEN")
            headers[normalized_name] = normalized_value

        mode = self.config.get("signature_mode", "none")
        if mode == "none":
            return headers
        if mode != "hmac-sha256":
            raise WebhookSecurityError("NOTIFICATION_ENDPOINT_INVALID")
        secret = self.config.get("signing_secret")
        if not isinstance(secret, str) or not secret:
            raise WebhookSecurityError("NOTIFICATION_CREDENTIAL_INVALID")
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-ML-Platform-Signature"] = f"sha256={signature}"
        return headers

    def send(
        self,
        *,
        endpoint: NotificationEndpoint,
        event: DomainEvent,
        delivery_key: str,
        recipient_user_ids: Iterable[UUID] | None = None,
    ) -> DeliveryResult:
        del endpoint, recipient_user_ids
        url = self.config.get("url")
        if not isinstance(url, str):
            return DeliveryResult("failed", "NOTIFICATION_ENDPOINT_INVALID")
        try:
            validated_url = validate_webhook_url(
                url,
                resolve=self.resolve,
                allowlist=self.allowlist,
            )
            body = canonical_json_bytes(
                _safe_event_envelope(event),
                max_payload_bytes=self.max_payload_bytes,
            )
            headers = self._headers(body, delivery_key)
        except WebhookSecurityError as error:
            return DeliveryResult("failed", error.code)
        try:
            response = self.http_client.post(
                validated_url,
                content=body,
                headers=headers,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            )
        except (httpx.HTTPError, OSError, TimeoutError):
            return _network_error_result()
        return _http_result(response)


class WeComNotificationAdapter:
    def __init__(
        self,
        config: Mapping[str, object],
        *,
        http_client: object,
        timeout_seconds: int,
        max_payload_bytes: int,
        resolve: Callable[[str, int], Iterable[object]] | None,
    ) -> None:
        self.config = config
        self.http_client = http_client
        self.timeout_seconds = timeout_seconds
        self.max_payload_bytes = max_payload_bytes
        self.resolve = resolve

    def send(
        self,
        *,
        endpoint: NotificationEndpoint,
        event: DomainEvent,
        delivery_key: str,
        recipient_user_ids: Iterable[UUID] | None = None,
    ) -> DeliveryResult:
        del endpoint, recipient_user_ids
        url = self.config.get("url")
        if not isinstance(url, str):
            return DeliveryResult("failed", "NOTIFICATION_ENDPOINT_INVALID")
        try:
            validated_url = validate_wecom_url(url, resolve=self.resolve)
            body = canonical_json_bytes(
                {
                    "msgtype": "text",
                    "text": {"content": f"{_event_title(event)}\n{_event_body(event)}"},
                },
                max_payload_bytes=self.max_payload_bytes,
            )
        except WebhookSecurityError as error:
            return DeliveryResult("failed", error.code)
        try:
            response = self.http_client.post(
                validated_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "Idempotency-Key": delivery_key,
                },
                timeout=self.timeout_seconds,
                follow_redirects=False,
            )
        except (httpx.HTTPError, OSError, TimeoutError):
            return _network_error_result()

        result = _http_result(response)
        if result.status != "sent":
            return result
        try:
            provider_payload = response.json()
        except (TypeError, ValueError):
            return DeliveryResult("failed", "NOTIFICATION_WECOM_INVALID_RESPONSE", result.provider_status)
        if not isinstance(provider_payload, Mapping) or provider_payload.get("errcode", 0) == 0:
            return result
        if provider_payload.get("errcode") == 45009:
            return DeliveryResult("retry", "NOTIFICATION_WECOM_RATE_LIMITED", result.provider_status)
        return DeliveryResult("failed", "NOTIFICATION_WECOM_REJECTED", result.provider_status)


class EmailNotificationAdapter:
    def __init__(
        self,
        config: Mapping[str, object],
        *,
        settings: Settings,
        smtp_factory: Callable[..., object],
    ) -> None:
        self.config = config
        self.settings = settings
        self.smtp_factory = smtp_factory

    @staticmethod
    def _addresses(value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError
        addresses: list[str] = []
        for candidate in value:
            if not isinstance(candidate, str) or "\r" in candidate or "\n" in candidate:
                raise ValueError
            display_name, address = parseaddr(candidate)
            if display_name or not address or candidate != address or "@" not in address:
                raise ValueError
            if address not in addresses:
                addresses.append(address)
        return addresses

    def send(
        self,
        *,
        endpoint: NotificationEndpoint,
        event: DomainEvent,
        delivery_key: str,
        recipient_user_ids: Iterable[UUID] | None = None,
    ) -> DeliveryResult:
        del endpoint, delivery_key, recipient_user_ids
        try:
            to_recipients = self._addresses(self.config.get("to", []))
            cc_recipients = [
                address
                for address in self._addresses(self.config.get("cc", []))
                if address not in to_recipients
            ]
            recipients = to_recipients + cc_recipients
        except ValueError:
            return DeliveryResult("failed", "NOTIFICATION_EMAIL_RECIPIENT_INVALID")
        if not recipients:
            return DeliveryResult("failed", "NOTIFICATION_EMAIL_RECIPIENT_INVALID")
        if len(recipients) > MAX_EMAIL_RECIPIENTS:
            return DeliveryResult("failed", "NOTIFICATION_EMAIL_RECIPIENT_LIMIT")
        if not self.settings.smtp_host or not self.settings.smtp_from:
            return DeliveryResult("failed", "NOTIFICATION_EMAIL_UNAVAILABLE")

        username = self.settings.smtp_username
        password = self.settings.smtp_password
        if (username is None) != (password is None):
            return DeliveryResult("failed", "NOTIFICATION_EMAIL_CREDENTIAL_INVALID")

        message = EmailMessage()
        message["From"] = self.settings.smtp_from
        if to_recipients:
            message["To"] = ", ".join(to_recipients)
        if cc_recipients:
            message["Cc"] = ", ".join(cc_recipients)
        message["Subject"] = _event_title(event)
        message.set_content(_event_body(event))
        try:
            with self.smtp_factory(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.notification_webhook_timeout_seconds,
            ) as client:
                if self.settings.smtp_use_tls:
                    client.starttls(context=ssl.create_default_context())
                if username is not None and password is not None:
                    client.login(username.get_secret_value(), password.get_secret_value())
                client.sendmail(self.settings.smtp_from, recipients, message.as_string())
        except smtplib.SMTPAuthenticationError:
            return DeliveryResult("failed", "NOTIFICATION_EMAIL_AUTH_FAILED")
        except smtplib.SMTPRecipientsRefused:
            return DeliveryResult("failed", "NOTIFICATION_EMAIL_RECIPIENT_INVALID")
        except smtplib.SMTPResponseException as error:
            if 400 <= error.smtp_code < 500:
                return DeliveryResult("retry", "NOTIFICATION_EMAIL_RETRYABLE", error.smtp_code)
            return DeliveryResult("failed", "NOTIFICATION_EMAIL_REJECTED", error.smtp_code)
        except (smtplib.SMTPException, OSError, TimeoutError):
            return DeliveryResult("retry", "NOTIFICATION_EMAIL_UNAVAILABLE")
        return DeliveryResult("sent")


class NotificationChannelRouter:
    """Decrypt one endpoint config and dispatch only a safe event envelope."""

    def __init__(
        self,
        db: Session,
        settings: Settings,
        *,
        http_client: object | None = None,
        smtp_factory: Callable[..., object] = smtplib.SMTP,
        resolve: Callable[[str, int], Iterable[object]] | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.http_client = http_client or httpx
        self.smtp_factory = smtp_factory
        self.resolve = resolve

    def _config(
        self, endpoint: NotificationEndpoint
    ) -> tuple[dict[str, object] | None, str | None]:
        master_key: SecretStr | None = self.settings.resolved_notification_master_key
        if master_key is None:
            return None, "NOTIFICATION_CREDENTIAL_UNAVAILABLE"
        try:
            return decrypt_config(endpoint.encrypted_config, master_key), None
        except NotificationCredentialError:
            return None, "NOTIFICATION_CREDENTIAL_INVALID"

    def send(
        self,
        *,
        endpoint: NotificationEndpoint,
        event: DomainEvent,
        delivery_key: str,
        recipient_user_ids: Iterable[UUID] | None = None,
    ) -> DeliveryResult:
        config, configuration_error = self._config(endpoint)
        if config is None:
            return DeliveryResult("failed", configuration_error)
        if endpoint.kind == "in_app":
            adapter: NotificationAdapter = InAppNotificationAdapter(self.db, config)
        elif endpoint.kind == "wecom":
            adapter = WeComNotificationAdapter(
                config,
                http_client=self.http_client,
                timeout_seconds=self.settings.notification_webhook_timeout_seconds,
                max_payload_bytes=self.settings.notification_max_payload_bytes,
                resolve=self.resolve,
            )
        elif endpoint.kind == "email":
            adapter = EmailNotificationAdapter(
                config,
                settings=self.settings,
                smtp_factory=self.smtp_factory,
            )
        elif endpoint.kind == "webhook":
            adapter = WebhookNotificationAdapter(
                config,
                http_client=self.http_client,
                timeout_seconds=self.settings.notification_webhook_timeout_seconds,
                max_payload_bytes=self.settings.notification_max_payload_bytes,
                resolve=self.resolve,
                allowlist=self.settings.notification_webhook_allowlist,
            )
        else:
            return DeliveryResult("failed", "NOTIFICATION_ENDPOINT_INVALID")
        return adapter.send(
            endpoint=endpoint,
            event=event,
            delivery_key=delivery_key,
            recipient_user_ids=recipient_user_ids,
        )
