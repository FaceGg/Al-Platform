"""Project-scoped notification configuration and recipient-safe delivery APIs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import TypeVar
from urllib.parse import urlsplit
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import get_current_user
from app.api.users import get_current_admin
from app.config import settings
from app.database import get_db
from app.events.domain import DomainEvent
from app.models.access import ProjectMember
from app.models.notifications import (
    InAppNotification,
    NotificationDelivery,
    NotificationEndpoint,
    NotificationOutbox,
    NotificationSubscription,
)
from app.models.user import User
from app.schemas.notifications import (
    InAppNotificationList,
    NotificationDeliveryList,
    NotificationDeliveryResponse,
    NotificationEndpointCreate,
    NotificationEndpointList,
    NotificationEndpointResponse,
    NotificationEndpointTestResponse,
    NotificationEndpointUpdate,
    NotificationRecipientDirectory,
    NotificationSubscriptionCreate,
    NotificationSubscriptionList,
    NotificationSubscriptionResponse,
    NotificationSubscriptionUpdate,
    NotificationUnreadCount,
    normalize_endpoint_config,
)
from app.services.audit import AuditIntent, AuditService
from app.services.notification_channels import (
    EmailNotificationAdapter,
    MAX_EMAIL_RECIPIENTS,
    NotificationChannelRouter,
    WebhookNotificationAdapter,
)
from app.services.notification_crypto import encrypt_config
from app.services.platform_audit import PlatformAuditIntent, record_platform_event
from app.services.project_access import ProjectAccessService, ProjectRole
from app.services.webhook_security import (
    WebhookSecurityError,
    validate_wecom_url,
    validate_webhook_url,
)


router = APIRouter(tags=["notifications"])
_ERROR_CODE = re.compile(r"^[A-Z0-9_]{1,64}$")

PROJECT_WRITE_ACTIONS = {
    "POST /api/projects/{project_id}/notification-endpoints": "notification.endpoint.create",
    "PATCH /api/projects/{project_id}/notification-endpoints/{endpoint_id}": "notification.endpoint.update",
    "DELETE /api/projects/{project_id}/notification-endpoints/{endpoint_id}": "notification.endpoint.delete",
    "POST /api/projects/{project_id}/notification-endpoints/{endpoint_id}/test": "notification.endpoint.test",
    "POST /api/projects/{project_id}/notification-subscriptions": "notification.subscription.create",
    "PATCH /api/projects/{project_id}/notification-subscriptions/{subscription_id}": "notification.subscription.update",
    "DELETE /api/projects/{project_id}/notification-subscriptions/{subscription_id}": "notification.subscription.delete",
}


BodyModel = TypeVar("BodyModel", bound=BaseModel)


async def _strict_body(request: Request, model_type: type[BodyModel]) -> BodyModel:
    """Keep Pydantic strictness without echoing a rejected credential body."""
    try:
        body = await request.body()
        if len(body) > _runtime_settings(request).notification_max_payload_bytes:
            raise HTTPException(413, {"code": "NOTIFICATION_REQUEST_TOO_LARGE"})
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError
        return model_type.model_validate(payload)
    except HTTPException:
        raise
    except (TypeError, ValueError, ValidationError):
        raise HTTPException(422, {"code": "NOTIFICATION_REQUEST_INVALID"}) from None


async def _endpoint_create_body(request: Request) -> NotificationEndpointCreate:
    return await _strict_body(request, NotificationEndpointCreate)


async def _endpoint_update_body(request: Request) -> NotificationEndpointUpdate:
    return await _strict_body(request, NotificationEndpointUpdate)


async def _subscription_create_body(request: Request) -> NotificationSubscriptionCreate:
    return await _strict_body(request, NotificationSubscriptionCreate)


async def _subscription_update_body(request: Request) -> NotificationSubscriptionUpdate:
    return await _strict_body(request, NotificationSubscriptionUpdate)


def _runtime_settings(request: Request):
    return getattr(request.app.state, "settings", None) or settings


def _audit_service(db: Session) -> AuditService:
    return AuditService(sessionmaker(bind=db.get_bind()))


def _require_project(db: Session, project_id: UUID, user_id: UUID, permission: str):
    return ProjectAccessService().require(db, project_id, user_id, permission)


def _resolve_project(db: Session, project_id: UUID, user_id: UUID):
    return ProjectAccessService().resolve(db, project_id, user_id)


def _not_found(code: str) -> HTTPException:
    return HTTPException(404, {"code": code})


def _invalid(code: str) -> HTTPException:
    return HTTPException(422, {"code": code})


def _is_endpoint_name_conflict(error: IntegrityError) -> bool:
    original = getattr(error, "orig", None)
    constraint = getattr(getattr(original, "diag", None), "constraint_name", None)
    if constraint == "uq_notification_endpoint_project_name":
        return True
    return "notification_endpoints.project_id, notification_endpoints.name" in str(
        original
    )


def _endpoint_response(endpoint: NotificationEndpoint) -> dict[str, object]:
    return {
        "id": endpoint.id,
        "project_id": endpoint.project_id,
        "kind": endpoint.kind,
        "name": endpoint.name,
        "destination_hint": endpoint.destination_hint,
        "enabled": endpoint.enabled,
        "created_by_id": endpoint.created_by_id,
        "created_at": endpoint.created_at,
        "updated_at": endpoint.updated_at,
    }


def _subscription_response(
    subscription: NotificationSubscription,
    *,
    include_recipient_user_ids: bool = True,
) -> dict[str, object]:
    return {
        "id": subscription.id,
        "project_id": subscription.project_id,
        "endpoint_id": subscription.endpoint_id,
        "event_types": subscription.event_types,
        "minimum_severity": subscription.minimum_severity,
        "recipient_roles": subscription.recipient_roles,
        "recipient_user_ids": (
            subscription.recipient_user_ids if include_recipient_user_ids else []
        ),
        "enabled": subscription.enabled,
        "created_by_id": subscription.created_by_id,
        "created_at": subscription.created_at,
        "updated_at": subscription.updated_at,
    }


def _delivery_response(
    delivery: NotificationDelivery,
    destination_hint: str | None,
) -> dict[str, object]:
    return {
        "id": delivery.id,
        "status": delivery.status,
        "attempts": delivery.attempts,
        "error_code": _safe_error_code(delivery.last_error_code),
        "destination_hint": destination_hint or "unavailable",
        "created_at": delivery.created_at,
        "updated_at": delivery.updated_at,
        "next_attempt_at": delivery.next_attempt_at,
    }


def _safe_error_code(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) and _ERROR_CODE.fullmatch(value) else "NOTIFICATION_DELIVERY_FAILED"


def _member_ids(db: Session, project_id: UUID, owner_id: UUID) -> set[UUID]:
    return {
        owner_id,
        *(
            member_id
            for (member_id,) in db.query(ProjectMember.user_id)
            .filter(ProjectMember.project_id == project_id)
            .all()
        ),
    }


def _validate_project_recipient_ids(
    db: Session,
    *,
    project_id: UUID,
    owner_id: UUID,
    recipient_ids: list[UUID] | list[str],
) -> list[UUID]:
    try:
        normalized = [UUID(str(value)) for value in recipient_ids]
    except (TypeError, ValueError, AttributeError):
        raise _invalid("NOTIFICATION_RECIPIENT_INVALID") from None
    if len(set(normalized)) != len(normalized):
        raise _invalid("NOTIFICATION_RECIPIENT_INVALID")
    if not set(normalized).issubset(_member_ids(db, project_id, owner_id)):
        raise _invalid("NOTIFICATION_RECIPIENT_NOT_MEMBER")
    return normalized


def _validate_in_app_recipient_selector(
    endpoint: NotificationEndpoint,
    recipient_roles: list[str],
    recipient_user_ids: list[UUID] | list[str],
) -> None:
    if endpoint.kind == "in_app" and not recipient_roles and not recipient_user_ids:
        raise _invalid("NOTIFICATION_RECIPIENT_INVALID")


def _validated_endpoint_config(
    *,
    kind: str,
    raw_config: dict[str, object],
    app_settings,
) -> dict[str, object]:
    try:
        config = normalize_endpoint_config(kind, raw_config)
        if kind == "webhook":
            validate_webhook_url(
                str(config["url"]),
                allowlist=app_settings.notification_webhook_allowlist,
            )
            WebhookNotificationAdapter(
                config,
                http_client=httpx,
                timeout_seconds=app_settings.notification_webhook_timeout_seconds,
                max_payload_bytes=app_settings.notification_max_payload_bytes,
                resolve=None,
                allowlist=app_settings.notification_webhook_allowlist,
            )._headers(b"{}", "notification-config-validation")
        elif kind == "wecom":
            validate_wecom_url(str(config["url"]))
        elif kind == "email":
            recipients = EmailNotificationAdapter._addresses(config["to"])
            recipients.extend(
                address
                for address in EmailNotificationAdapter._addresses(config["cc"])
                if address not in recipients
            )
            if not recipients or len(recipients) > MAX_EMAIL_RECIPIENTS:
                raise ValueError
        return config
    except WebhookSecurityError as error:
        raise _invalid(error.code) from None
    except (KeyError, TypeError, ValueError):
        raise _invalid("NOTIFICATION_ENDPOINT_INVALID") from None


def _destination_hint(kind: str, config: dict[str, object]) -> str:
    if kind == "in_app":
        return "in-app recipients"
    if kind == "email":
        return "email recipients"
    try:
        hostname = urlsplit(str(config["url"])).hostname
    except (KeyError, TypeError, ValueError):
        hostname = None
    return hostname or "configured destination"


def _encrypted_config(config: dict[str, object], app_settings) -> str:
    master_key = getattr(app_settings, "resolved_notification_master_key", None)
    if master_key is None:
        raise HTTPException(503, {"code": "NOTIFICATION_CREDENTIAL_UNAVAILABLE"})
    try:
        return encrypt_config(config, master_key)
    except Exception:
        raise HTTPException(503, {"code": "NOTIFICATION_CREDENTIAL_UNAVAILABLE"}) from None


def _endpoint_for_project(db: Session, project_id: UUID, endpoint_id: UUID) -> NotificationEndpoint:
    endpoint = (
        db.query(NotificationEndpoint)
        .filter(
            NotificationEndpoint.id == endpoint_id,
            NotificationEndpoint.project_id == project_id,
        )
        .first()
    )
    if endpoint is None:
        raise _not_found("NOTIFICATION_ENDPOINT_NOT_FOUND")
    return endpoint


def _subscription_for_project(
    db: Session,
    project_id: UUID,
    subscription_id: UUID,
) -> NotificationSubscription:
    subscription = (
        db.query(NotificationSubscription)
        .filter(
            NotificationSubscription.id == subscription_id,
            NotificationSubscription.project_id == project_id,
        )
        .first()
    )
    if subscription is None:
        raise _not_found("NOTIFICATION_SUBSCRIPTION_NOT_FOUND")
    return subscription


@router.get(
    "/api/projects/{project_id}/notification-recipients",
    response_model=NotificationRecipientDirectory,
)
def list_notification_recipients(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = _require_project(db, project_id, current_user.id, "notification.manage")
    owner = db.get(User, access.project.owner_id)
    items: dict[UUID, dict[str, object]] = {}
    if owner is not None:
        items[owner.id] = {
            "user_id": owner.id,
            "username": owner.username,
            "role": "owner",
        }
    for member_id, username, role in (
        db.query(ProjectMember.user_id, User.username, ProjectMember.role)
        .join(User, User.id == ProjectMember.user_id)
        .filter(ProjectMember.project_id == project_id)
        .order_by(User.username, ProjectMember.user_id)
        .all()
    ):
        items.setdefault(
            member_id,
            {"user_id": member_id, "username": username, "role": role},
        )
    return {
        "items": sorted(
            items.values(),
            key=lambda item: (
                item["role"] != "owner",
                str(item["username"]).lower(),
                str(item["user_id"]),
            ),
        )
    }


@router.get(
    "/api/projects/{project_id}/notification-endpoints",
    response_model=NotificationEndpointList,
)
def list_notification_endpoints(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_project(db, project_id, current_user.id, "notification.read")
    query = db.query(NotificationEndpoint).filter(NotificationEndpoint.project_id == project_id)
    items = query.order_by(NotificationEndpoint.created_at, NotificationEndpoint.id).all()
    return {"items": [_endpoint_response(item) for item in items], "total": len(items)}


@router.post(
    "/api/projects/{project_id}/notification-endpoints",
    response_model=NotificationEndpointResponse,
    status_code=201,
)
def create_notification_endpoint(
    project_id: UUID,
    request: Request,
    data: NotificationEndpointCreate = Depends(_endpoint_create_body),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = _resolve_project(db, project_id, current_user.id)
    endpoint_id = uuid4()
    try:
        with _audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="notification.manage",
            intent=AuditIntent(
                project_id=project_id,
                action="notification.endpoint.create",
                resource_type="notification_endpoint",
                resource_id=str(endpoint_id),
                changes={"kind": data.kind, "name": data.name},
            ),
            allowed_changes={"kind", "name", "destination_hint", "enabled"},
        ):
            app_settings = _runtime_settings(request)
            config = _validated_endpoint_config(
                kind=data.kind,
                raw_config=data.config,
                app_settings=app_settings,
            )
            if data.kind == "in_app":
                recipient_ids = _validate_project_recipient_ids(
                    db,
                    project_id=project_id,
                    owner_id=access.project.owner_id,
                    recipient_ids=config["recipient_user_ids"],
                )
                config["recipient_user_ids"] = [str(value) for value in recipient_ids]
            endpoint = NotificationEndpoint(
                id=endpoint_id,
                project_id=project_id,
                kind=data.kind,
                name=data.name,
                destination_hint=_destination_hint(data.kind, config),
                encrypted_config=_encrypted_config(config, app_settings),
                created_by_id=current_user.id,
            )
            db.add(endpoint)
            db.flush()
    except IntegrityError as error:
        if _is_endpoint_name_conflict(error):
            raise HTTPException(
                409,
                {"code": "NOTIFICATION_ENDPOINT_NAME_CONFLICT"},
            ) from None
        raise
    db.refresh(endpoint)
    return _endpoint_response(endpoint)


@router.patch(
    "/api/projects/{project_id}/notification-endpoints/{endpoint_id}",
    response_model=NotificationEndpointResponse,
)
def update_notification_endpoint(
    project_id: UUID,
    endpoint_id: UUID,
    request: Request,
    data: NotificationEndpointUpdate = Depends(_endpoint_update_body),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = _resolve_project(db, project_id, current_user.id)
    try:
        with _audit_service(db).project_action(
            db,
            request=request,
            actor=current_user,
            access=access,
            permission="notification.manage",
            intent=AuditIntent(
                project_id=project_id,
                action="notification.endpoint.update",
                resource_type="notification_endpoint",
                resource_id=str(endpoint_id),
                changes={"name": data.name, "enabled": data.enabled},
            ),
            allowed_changes={"name", "enabled", "destination_hint"},
        ):
            endpoint = _endpoint_for_project(db, project_id, endpoint_id)
            fields = data.model_fields_set
            if "name" in fields:
                endpoint.name = data.name
            if "enabled" in fields:
                endpoint.enabled = data.enabled
            if "config" in fields:
                app_settings = _runtime_settings(request)
                config = _validated_endpoint_config(
                    kind=endpoint.kind,
                    raw_config=data.config,
                    app_settings=app_settings,
                )
                if endpoint.kind == "in_app":
                    recipient_ids = _validate_project_recipient_ids(
                        db,
                        project_id=project_id,
                        owner_id=access.project.owner_id,
                        recipient_ids=config["recipient_user_ids"],
                    )
                    config["recipient_user_ids"] = [str(value) for value in recipient_ids]
                endpoint.destination_hint = _destination_hint(endpoint.kind, config)
                endpoint.encrypted_config = _encrypted_config(config, app_settings)
            db.flush()
    except IntegrityError as error:
        if _is_endpoint_name_conflict(error):
            raise HTTPException(
                409,
                {"code": "NOTIFICATION_ENDPOINT_NAME_CONFLICT"},
            ) from None
        raise
    db.refresh(endpoint)
    return _endpoint_response(endpoint)


@router.delete(
    "/api/projects/{project_id}/notification-endpoints/{endpoint_id}",
    status_code=204,
)
def delete_notification_endpoint(
    project_id: UUID,
    endpoint_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = _resolve_project(db, project_id, current_user.id)
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="notification.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="notification.endpoint.delete",
            resource_type="notification_endpoint",
            resource_id=str(endpoint_id),
        ),
        allowed_changes=set(),
    ):
        db.delete(_endpoint_for_project(db, project_id, endpoint_id))
    return Response(status_code=204)


@router.post(
    "/api/projects/{project_id}/notification-endpoints/{endpoint_id}/test",
    response_model=NotificationEndpointTestResponse,
)
def test_notification_endpoint(
    project_id: UUID,
    endpoint_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = _resolve_project(db, project_id, current_user.id)
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="notification.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="notification.endpoint.test",
            resource_type="notification_endpoint",
            resource_id=str(endpoint_id),
        ),
        allowed_changes=set(),
    ):
        endpoint = _endpoint_for_project(db, project_id, endpoint_id)
        key_material = f"notification-test:{endpoint.id}:{current_user.id}"
        event = DomainEvent(
            event_id=uuid5(NAMESPACE_URL, key_material),
            idempotency_key=key_material,
            event_type="rollout.completed",
            severity="info",
            occurred_at=datetime.now(timezone.utc),
            project_id=project_id,
            actor_id=current_user.id,
            resource_type="notification_endpoint",
            resource_id=str(endpoint.id),
            payload={"deployment_id": str(project_id)},
        )
        channel_router = NotificationChannelRouter(
            db,
            _runtime_settings(request),
        )
        if endpoint.kind == "in_app":
            config, _configuration_error = channel_router._config(endpoint)
            if config is not None:
                recipient_ids = config.get("recipient_user_ids")
                if not isinstance(recipient_ids, list):
                    raise _invalid("NOTIFICATION_RECIPIENT_INVALID")
                _validate_project_recipient_ids(
                    db,
                    project_id=project_id,
                    owner_id=access.project.owner_id,
                    recipient_ids=recipient_ids,
                )
        result = channel_router.send(
            endpoint=endpoint,
            event=event,
            delivery_key=key_material,
        )
    return {"status": result.status, "error_code": result.error_code}


@router.get(
    "/api/projects/{project_id}/notification-subscriptions",
    response_model=NotificationSubscriptionList,
)
def list_notification_subscriptions(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = _require_project(db, project_id, current_user.id, "notification.read")
    query = db.query(NotificationSubscription).filter(
        NotificationSubscription.project_id == project_id
    )
    items = query.order_by(NotificationSubscription.created_at, NotificationSubscription.id).all()
    include_recipient_user_ids = access.role in {ProjectRole.OWNER, ProjectRole.EDITOR}
    return {
        "items": [
            _subscription_response(
                item,
                include_recipient_user_ids=include_recipient_user_ids,
            )
            for item in items
        ],
        "total": len(items),
    }


@router.post(
    "/api/projects/{project_id}/notification-subscriptions",
    response_model=NotificationSubscriptionResponse,
    status_code=201,
)
def create_notification_subscription(
    project_id: UUID,
    request: Request,
    data: NotificationSubscriptionCreate = Depends(_subscription_create_body),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = _resolve_project(db, project_id, current_user.id)
    subscription_id = uuid4()
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="notification.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="notification.subscription.create",
            resource_type="notification_subscription",
            resource_id=str(subscription_id),
            changes={
                "endpoint_id": str(data.endpoint_id),
                "enabled": data.enabled,
                "minimum_severity": data.minimum_severity,
            },
        ),
        allowed_changes={"endpoint_id", "enabled", "minimum_severity"},
    ):
        endpoint = _endpoint_for_project(db, project_id, data.endpoint_id)
        recipient_ids = _validate_project_recipient_ids(
            db,
            project_id=project_id,
            owner_id=access.project.owner_id,
            recipient_ids=data.recipient_user_ids,
        )
        _validate_in_app_recipient_selector(
            endpoint,
            data.recipient_roles,
            recipient_ids,
        )
        subscription = NotificationSubscription(
            id=subscription_id,
            project_id=project_id,
            endpoint_id=data.endpoint_id,
            event_types=data.event_types,
            minimum_severity=data.minimum_severity,
            recipient_roles=data.recipient_roles,
            recipient_user_ids=[str(value) for value in recipient_ids],
            enabled=data.enabled,
            created_by_id=current_user.id,
        )
        db.add(subscription)
        db.flush()
    db.refresh(subscription)
    return _subscription_response(subscription)


@router.patch(
    "/api/projects/{project_id}/notification-subscriptions/{subscription_id}",
    response_model=NotificationSubscriptionResponse,
)
def update_notification_subscription(
    project_id: UUID,
    subscription_id: UUID,
    request: Request,
    data: NotificationSubscriptionUpdate = Depends(_subscription_update_body),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = _resolve_project(db, project_id, current_user.id)
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="notification.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="notification.subscription.update",
            resource_type="notification_subscription",
            resource_id=str(subscription_id),
            changes={
                "endpoint_id": str(data.endpoint_id) if data.endpoint_id else None,
                "enabled": data.enabled,
                "minimum_severity": data.minimum_severity,
            },
        ),
        allowed_changes={"endpoint_id", "enabled", "minimum_severity"},
    ):
        subscription = _subscription_for_project(db, project_id, subscription_id)
        endpoint = _endpoint_for_project(db, project_id, subscription.endpoint_id)
        fields = data.model_fields_set
        if "endpoint_id" in fields:
            endpoint = _endpoint_for_project(db, project_id, data.endpoint_id)
            subscription.endpoint_id = data.endpoint_id
        if "event_types" in fields:
            subscription.event_types = data.event_types
        if "minimum_severity" in fields:
            subscription.minimum_severity = data.minimum_severity
        if "recipient_roles" in fields:
            subscription.recipient_roles = data.recipient_roles
        if "recipient_user_ids" in fields:
            recipient_ids = _validate_project_recipient_ids(
                db,
                project_id=project_id,
                owner_id=access.project.owner_id,
                recipient_ids=data.recipient_user_ids,
            )
            subscription.recipient_user_ids = [str(value) for value in recipient_ids]
        if "enabled" in fields:
            subscription.enabled = data.enabled
        _validate_in_app_recipient_selector(
            endpoint,
            subscription.recipient_roles,
            subscription.recipient_user_ids,
        )
        db.flush()
    db.refresh(subscription)
    return _subscription_response(subscription)


@router.delete(
    "/api/projects/{project_id}/notification-subscriptions/{subscription_id}",
    status_code=204,
)
def delete_notification_subscription(
    project_id: UUID,
    subscription_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = _resolve_project(db, project_id, current_user.id)
    with _audit_service(db).project_action(
        db,
        request=request,
        actor=current_user,
        access=access,
        permission="notification.manage",
        intent=AuditIntent(
            project_id=project_id,
            action="notification.subscription.delete",
            resource_type="notification_subscription",
            resource_id=str(subscription_id),
        ),
        allowed_changes=set(),
    ):
        db.delete(_subscription_for_project(db, project_id, subscription_id))
    return Response(status_code=204)


@router.get("/api/notifications", response_model=InAppNotificationList)
def list_in_app_notifications(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(InAppNotification).filter(
        InAppNotification.recipient_user_id == current_user.id
    )
    if not include_archived:
        query = query.filter(InAppNotification.archived_at.is_(None))
    items = query.order_by(InAppNotification.created_at.desc(), InAppNotification.id.desc()).all()
    return {"items": items, "total": len(items)}


@router.get("/api/notifications/unread-count", response_model=NotificationUnreadCount)
def unread_notification_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    count = (
        db.query(InAppNotification)
        .filter(
            InAppNotification.recipient_user_id == current_user.id,
            InAppNotification.read_at.is_(None),
            InAppNotification.archived_at.is_(None),
        )
        .count()
    )
    return {"count": count}


def _recipient_notification(
    db: Session,
    notification_id: UUID,
    user_id: UUID,
) -> InAppNotification:
    notification = (
        db.query(InAppNotification)
        .filter(
            InAppNotification.id == notification_id,
            InAppNotification.recipient_user_id == user_id,
        )
        .first()
    )
    if notification is None:
        raise _not_found("NOTIFICATION_NOT_FOUND")
    return notification


@router.patch("/api/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = _recipient_notification(db, notification_id, current_user.id)
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        db.refresh(notification)
    return {"id": notification.id, "read_at": notification.read_at}


@router.patch("/api/notifications/{notification_id}/archive")
def archive_notification(
    notification_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = _recipient_notification(db, notification_id, current_user.id)
    if notification.archived_at is None:
        notification.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        db.refresh(notification)
    return {"id": notification.id, "archived_at": notification.archived_at}


@router.get("/api/admin/notification-deliveries", response_model=NotificationDeliveryList)
def list_notification_deliveries(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    del admin
    query = db.query(NotificationDelivery, NotificationEndpoint.destination_hint).outerjoin(
        NotificationEndpoint,
        NotificationEndpoint.id == NotificationDelivery.endpoint_id,
    )
    total = query.count()
    rows = (
        query.order_by(NotificationDelivery.created_at.desc(), NotificationDelivery.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [_delivery_response(delivery, hint) for delivery, hint in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post(
    "/api/admin/notification-deliveries/{delivery_id}/retry",
    response_model=NotificationDeliveryResponse,
)
def retry_notification_delivery(
    delivery_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    retryable_statuses = ("failed", "dead_letter")
    delivery_query = db.query(NotificationDelivery).filter(
        NotificationDelivery.id == delivery_id
    )
    if db.get_bind().dialect.name == "postgresql":
        delivery_query = delivery_query.with_for_update()
    delivery = delivery_query.first()
    if delivery is None:
        raise _not_found("NOTIFICATION_DELIVERY_NOT_FOUND")
    outbox_query = db.query(NotificationOutbox).filter(
        NotificationOutbox.id == delivery.outbox_id
    )
    if db.get_bind().dialect.name == "postgresql":
        outbox_query = outbox_query.with_for_update()
    outbox = outbox_query.first()
    if outbox is None:
        raise _not_found("NOTIFICATION_DELIVERY_NOT_FOUND")
    if delivery.status not in retryable_statuses:
        raise HTTPException(409, {"code": "NOTIFICATION_DELIVERY_RETRY_INVALID"})
    if (
        db.query(NotificationDelivery)
        .filter(
            NotificationDelivery.outbox_id == outbox.id,
            NotificationDelivery.status == "processing",
        )
        .first()
        is not None
    ):
        raise HTTPException(409, {"code": "NOTIFICATION_DELIVERY_RETRY_BUSY"})
    endpoint = db.get(NotificationEndpoint, delivery.endpoint_id)
    destination_hint = endpoint.destination_hint if endpoint is not None else None
    retry_at = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        delivery_updated = (
            db.query(NotificationDelivery)
            .filter(
                NotificationDelivery.id == delivery.id,
                NotificationDelivery.status.in_(retryable_statuses),
            )
            .update(
                {
                    NotificationDelivery.status: "pending",
                    NotificationDelivery.next_attempt_at: retry_at,
                    NotificationDelivery.claim_token: None,
                    NotificationDelivery.claimed_at: None,
                    NotificationDelivery.last_error_code: None,
                },
                synchronize_session="fetch",
            )
        )
        outbox_updated = (
            db.query(NotificationOutbox)
            .filter(
                NotificationOutbox.id == outbox.id,
                NotificationOutbox.status.in_(retryable_statuses),
            )
            .update(
                {
                    NotificationOutbox.status: "pending",
                    NotificationOutbox.next_attempt_at: retry_at,
                    NotificationOutbox.claimed_at: None,
                    NotificationOutbox.last_error_code: None,
                },
                synchronize_session="fetch",
            )
        )
        if delivery_updated != 1 or outbox_updated != 1:
            db.rollback()
            raise HTTPException(409, {"code": "NOTIFICATION_DELIVERY_RETRY_INVALID"})
        record_platform_event(
            db,
            actor=admin,
            request=request,
            intent=PlatformAuditIntent(
                action="platform.notification.delivery_retry",
                resource_type="notification_delivery",
                resource_id=str(delivery.id),
                changes={"status": "pending"},
            ),
            result="success",
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, {"code": "NOTIFICATION_DELIVERY_RETRY_FAILED"}) from None
    db.refresh(delivery)
    return _delivery_response(delivery, destination_hint)
