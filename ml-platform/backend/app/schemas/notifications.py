"""Strict public contracts for notification configuration and delivery state."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


NotificationEndpointKind = Literal["in_app", "wecom", "email", "webhook"]
NotificationSeverity = Literal["info", "warning", "critical"]
NotificationRecipientRole = Literal["owner", "editor", "operator", "viewer"]


def normalize_endpoint_config(
    kind: NotificationEndpointKind,
    config: dict[str, object],
) -> dict[str, object]:
    """Reject unknown channel fields before an API route encrypts configuration."""
    if not isinstance(config, dict):
        raise ValueError("notification endpoint config must be an object")

    if kind == "in_app":
        allowed = {"recipient_user_ids"}
        values = config.get("recipient_user_ids")
        if set(config) - allowed or not isinstance(values, list) or not values:
            raise ValueError("in-app endpoint requires recipient_user_ids")
        if len(values) > 50:
            raise ValueError("in-app endpoint recipient limit exceeded")
        try:
            recipient_ids = [str(UUID(str(value))) for value in values]
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("in-app endpoint recipients must be UUIDs") from error
        if len(set(recipient_ids)) != len(recipient_ids):
            raise ValueError("in-app endpoint recipients must be unique")
        return {"recipient_user_ids": recipient_ids}

    if kind == "wecom":
        allowed = {"url"}
        url = config.get("url")
        if set(config) - allowed or not isinstance(url, str) or not url:
            raise ValueError("WeCom endpoint requires a URL")
        return {"url": url}

    if kind == "email":
        allowed = {"to", "cc"}
        to = config.get("to")
        cc = config.get("cc", [])
        if set(config) - allowed or not isinstance(to, list) or not isinstance(cc, list):
            raise ValueError("email endpoint requires recipient lists")
        if not to or len(to) + len(cc) > 50 or not all(
            isinstance(value, str) for value in [*to, *cc]
        ):
            raise ValueError("email endpoint recipients are invalid")
        return {"to": list(to), "cc": list(cc)}

    allowed = {"url", "headers", "signature_mode", "signing_secret"}
    url = config.get("url")
    headers = config.get("headers", {})
    signature_mode = config.get("signature_mode", "none")
    signing_secret = config.get("signing_secret")
    if set(config) - allowed or not isinstance(url, str) or not url:
        raise ValueError("webhook endpoint requires a URL")
    if not isinstance(headers, dict) or not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in headers.items()
    ):
        raise ValueError("webhook headers are invalid")
    if signature_mode not in {"none", "hmac-sha256"}:
        raise ValueError("webhook signature mode is invalid")
    if signature_mode == "hmac-sha256":
        if not isinstance(signing_secret, str) or not signing_secret:
            raise ValueError("webhook signing secret is required")
    elif signing_secret is not None:
        raise ValueError("webhook signing secret requires hmac-sha256")

    normalized: dict[str, object] = {
        "url": url,
        "headers": dict(headers),
        "signature_mode": signature_mode,
    }
    if signature_mode == "hmac-sha256":
        normalized["signing_secret"] = signing_secret
    return normalized


class NotificationEndpointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: NotificationEndpointKind
    name: str = Field(min_length=1, max_length=128)
    config: dict[str, object]

    @model_validator(mode="after")
    def validate_channel_config(self):
        self.config = normalize_endpoint_config(self.kind, self.config)
        return self


class NotificationEndpointUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    config: dict[str, object] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self):
        if any(
            getattr(self, field) is None
            for field in self.model_fields_set
        ):
            raise ValueError("notification endpoint update values cannot be null")
        return self


class NotificationSubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint_id: UUID
    event_types: list[str] = Field(min_length=1, max_length=32)
    minimum_severity: NotificationSeverity = "info"
    recipient_roles: list[NotificationRecipientRole] = Field(default_factory=list, max_length=4)
    recipient_user_ids: list[UUID] = Field(default_factory=list, max_length=50)
    enabled: bool = True

    @field_validator("event_types")
    @classmethod
    def normalize_event_types(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if isinstance(value, str) and value.strip()]
        if len(normalized) != len(values) or len(set(normalized)) != len(normalized):
            raise ValueError("event types must be non-empty and unique")
        return normalized

class NotificationSubscriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint_id: UUID | None = None
    event_types: list[str] | None = Field(default=None, min_length=1, max_length=32)
    minimum_severity: NotificationSeverity | None = None
    recipient_roles: list[NotificationRecipientRole] | None = Field(default=None, max_length=4)
    recipient_user_ids: list[UUID] | None = Field(default=None, max_length=50)
    enabled: bool | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self):
        if any(
            getattr(self, field) is None
            for field in self.model_fields_set
        ):
            raise ValueError("notification subscription update values cannot be null")
        return self

    @field_validator("event_types")
    @classmethod
    def normalize_optional_event_types(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return values
        return NotificationSubscriptionCreate.normalize_event_types(values)


class NotificationEndpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    kind: NotificationEndpointKind
    name: str
    destination_hint: str
    enabled: bool
    created_by_id: UUID | None
    created_at: datetime
    updated_at: datetime


class NotificationEndpointList(BaseModel):
    items: list[NotificationEndpointResponse]
    total: int


class NotificationRecipientResponse(BaseModel):
    user_id: UUID
    username: str
    role: NotificationRecipientRole


class NotificationRecipientDirectory(BaseModel):
    items: list[NotificationRecipientResponse]


class NotificationSubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    endpoint_id: UUID
    event_types: list[str]
    minimum_severity: NotificationSeverity
    recipient_roles: list[NotificationRecipientRole]
    recipient_user_ids: list[UUID]
    enabled: bool
    created_by_id: UUID | None
    created_at: datetime
    updated_at: datetime


class NotificationSubscriptionList(BaseModel):
    items: list[NotificationSubscriptionResponse]
    total: int


class InAppNotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None
    event_id: UUID
    event_type: str
    severity: NotificationSeverity
    title: str
    body: str
    payload: dict[str, object]
    read_at: datetime | None
    archived_at: datetime | None
    created_at: datetime


class InAppNotificationList(BaseModel):
    items: list[InAppNotificationResponse]
    total: int


class NotificationUnreadCount(BaseModel):
    count: int


class NotificationEndpointTestResponse(BaseModel):
    status: Literal["sent", "retry", "failed"]
    error_code: str | None


class NotificationDeliveryResponse(BaseModel):
    id: UUID
    status: str
    attempts: int
    error_code: str | None
    destination_hint: str
    created_at: datetime
    updated_at: datetime
    next_attempt_at: datetime | None


class NotificationDeliveryList(BaseModel):
    items: list[NotificationDeliveryResponse]
    total: int
    offset: int
    limit: int
