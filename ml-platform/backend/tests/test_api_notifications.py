import json
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.config import Settings
from app.database import Base, get_db
from app.main import app
from app.models.access import AuditEvent, ProjectMember
from app.models.notifications import (
    InAppNotification,
    NotificationDelivery,
    NotificationEndpoint,
    NotificationOutbox,
    NotificationSubscription,
)
from app.models.platform_audit import PlatformAuditEvent
from app.models.project import Project
from app.models.user import User
from app.schemas.notifications import (
    NotificationEndpointUpdate,
    NotificationSubscriptionUpdate,
)
from app.services.notification_channels import DeliveryResult, NotificationChannelRouter
from app.services.notification_crypto import decrypt_config, encrypt_config
from app.tasks.notification_tasks import execute_notification_delivery


class TestNotificationAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)
        cls.db = cls.Session()
        cls.settings = Settings(
            notification_master_key=Fernet.generate_key().decode("ascii"),
        )
        cls.previous_settings = getattr(app.state, "settings", None)
        app.state.settings = cls.settings

        cls.users = {
            role: User(
                username=f"notification-api-{role}",
                password_hash="hash",
                role="admin" if role == "admin" else "engineer",
            )
            for role in ("owner", "editor", "operator", "viewer", "outsider", "admin")
        }
        cls.db.add_all(cls.users.values())
        cls.db.flush()
        cls.project = Project(
            name="Notification API project",
            owner_id=cls.users["owner"].id,
        )
        cls.other_project = Project(
            name="Notification API other project",
            owner_id=cls.users["owner"].id,
        )
        cls.db.add_all((cls.project, cls.other_project))
        cls.db.flush()
        cls.db.add_all(
            ProjectMember(
                project_id=cls.project.id,
                user_id=cls.users[role].id,
                role=role,
                created_by=cls.users["owner"].id,
            )
            for role in ("editor", "operator", "viewer")
        )
        cls.db.commit()

        cls.current_user = cls.users["owner"]
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.current_user
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        if cls.previous_settings is None:
            delattr(app.state, "settings")
        else:
            app.state.settings = cls.previous_settings
        cls.db.close()
        cls.engine.dispose()

    def setUp(self):
        self._as("owner")

    def _as(self, role):
        self.__class__.current_user = self.users[role]

    def _request_without_server_exceptions(self, method, url, **kwargs):
        transport = self.client._transport
        previous = transport.raise_server_exceptions
        transport.raise_server_exceptions = False
        try:
            return getattr(self.client, method)(url, **kwargs)
        finally:
            transport.raise_server_exceptions = previous

    def _create_endpoint(self, name, *, recipient_user_ids=None):
        recipient_user_ids = recipient_user_ids or [str(self.users["owner"].id)]
        response = self.client.post(
            f"/api/projects/{self.project.id}/notification-endpoints",
            json={
                "kind": "in_app",
                "name": name,
                "config": {"recipient_user_ids": recipient_user_ids},
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_strict_endpoint_schema_encrypts_config_and_hides_secrets(self):
        unknown = self.client.post(
            f"/api/projects/{self.project.id}/notification-endpoints",
            json={
                "kind": "in_app",
                "name": "strict-unknown",
                "config": {"recipient_user_ids": [str(self.users["owner"].id)]},
                "unexpected": True,
            },
        )
        self.assertEqual(unknown.status_code, 422, unknown.text)

        nested_unknown = self.client.post(
            f"/api/projects/{self.project.id}/notification-endpoints",
            json={
                "kind": "in_app",
                "name": "strict-config",
                "config": {
                    "recipient_user_ids": [str(self.users["owner"].id)],
                    "secret": "not-allowed",
                },
            },
        )
        self.assertEqual(nested_unknown.status_code, 422, nested_unknown.text)
        self.assertNotIn("not-allowed", nested_unknown.text)

        with patch(
            "app.services.webhook_security._resolve_host",
            return_value=["8.8.8.8"],
        ):
            webhook = self.client.post(
                f"/api/projects/{self.project.id}/notification-endpoints",
                json={
                    "kind": "webhook",
                    "name": "secret-webhook",
                    "config": {
                        "url": "https://hooks.example.invalid/notification",
                        "signature_mode": "hmac-sha256",
                        "signing_secret": "test-webhook-secret",
                    },
                },
            )
        self.assertEqual(webhook.status_code, 201, webhook.text)
        self.assertNotIn("test-webhook-secret", webhook.text)
        webhook_endpoint = self.db.get(NotificationEndpoint, uuid.UUID(webhook.json()["id"]))
        self.assertNotIn("test-webhook-secret", webhook_endpoint.encrypted_config)

        created = self._create_endpoint("safe-endpoint")
        self.assertNotIn("config", created)
        self.assertNotIn("encrypted_config", created)
        self.assertNotIn("recipient_user_ids", json.dumps(created))

        endpoint = self.db.get(NotificationEndpoint, uuid.UUID(created["id"]))
        self.assertIsNotNone(endpoint)
        self.assertNotIn(str(self.users["owner"].id), endpoint.encrypted_config)
        self.assertEqual(
            decrypt_config(
                endpoint.encrypted_config,
                self.settings.resolved_notification_master_key,
            ),
            {"recipient_user_ids": [str(self.users["owner"].id)]},
        )
        audit = (
            self.db.query(AuditEvent)
            .filter(
                AuditEvent.project_id == self.project.id,
                AuditEvent.action == "notification.endpoint.create",
                AuditEvent.resource_id == str(endpoint.id),
                AuditEvent.result == "success",
            )
            .one()
        )
        self.assertNotIn("config", json.dumps(audit.changes))
        self.assertNotIn(endpoint.encrypted_config, json.dumps(audit.changes))
        webhook_audit = (
            self.db.query(AuditEvent)
            .filter(
                AuditEvent.project_id == self.project.id,
                AuditEvent.action == "notification.endpoint.create",
                AuditEvent.resource_id == str(webhook_endpoint.id),
                AuditEvent.result == "success",
            )
            .one()
        )
        self.assertNotIn("test-webhook-secret", json.dumps(webhook_audit.changes))

    def test_wecom_endpoint_creation_honors_runtime_allowlist(self):
        previous_settings = app.state.settings
        app.state.settings = Settings(
            _env_file=None,
            notification_master_key=self.settings.notification_master_key,
            notification_webhook_allowlist=["qyapi.weixin.qq.com"],
        )
        try:
            with patch(
                "app.services.webhook_security._resolve_host",
                return_value=["10.0.0.2"],
            ):
                response = self.client.post(
                    f"/api/projects/{self.project.id}/notification-endpoints",
                    json={
                        "kind": "wecom",
                        "name": f"controlled-wecom-{uuid.uuid4().hex}",
                        "config": {
                            "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=controlled",
                        },
                    },
                )
        finally:
            app.state.settings = previous_settings

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["kind"], "wecom")

    def test_notification_endpoint_rejects_declared_oversized_json_request(self):
        payload = json.dumps(
            {
                "kind": "in_app",
                "name": "oversized-json-request",
                "config": {"recipient_user_ids": [str(self.users["owner"].id)]},
            },
        ) + (" " * (self.settings.notification_max_payload_bytes + 1))

        response = self.client.post(
            f"/api/projects/{self.project.id}/notification-endpoints",
            content=payload,
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(response.json()["detail"]["code"], "NOTIFICATION_REQUEST_TOO_LARGE")

    def test_owner_and_editor_manage_while_other_members_are_read_only(self):
        owner_endpoint = self._create_endpoint("owner-managed")

        self._as("editor")
        editor_endpoint = self._create_endpoint("editor-managed")
        updated = self.client.patch(
            f"/api/projects/{self.project.id}/notification-endpoints/{editor_endpoint['id']}",
            json={"enabled": False},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertFalse(updated.json()["enabled"])
        deleted = self.client.delete(
            f"/api/projects/{self.project.id}/notification-endpoints/{editor_endpoint['id']}"
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)

        endpoint_actions = {
            event.action
            for event in self.db.query(AuditEvent).filter(
                AuditEvent.project_id == self.project.id,
                AuditEvent.resource_type == "notification_endpoint",
                AuditEvent.result == "success",
            )
        }
        self.assertTrue({
            "notification.endpoint.create",
            "notification.endpoint.update",
            "notification.endpoint.delete",
        }.issubset(endpoint_actions))

        for role in ("operator", "viewer"):
            with self.subTest(role=role):
                self._as(role)
                readable = self.client.get(
                    f"/api/projects/{self.project.id}/notification-endpoints"
                )
                self.assertEqual(readable.status_code, 200, readable.text)
                denied_create = self.client.post(
                    f"/api/projects/{self.project.id}/notification-endpoints",
                    json={
                        "kind": "in_app",
                        "name": f"{role}-denied",
                        "config": {"recipient_user_ids": [str(self.users[role].id)]},
                    },
                )
                self.assertEqual(denied_create.status_code, 403, denied_create.text)
                denied_update = self.client.patch(
                    f"/api/projects/{self.project.id}/notification-endpoints/{owner_endpoint['id']}",
                    json={"enabled": False},
                )
                self.assertEqual(denied_update.status_code, 403, denied_update.text)

        self._as("outsider")
        hidden = self.client.get(
            f"/api/projects/{self.project.id}/notification-endpoints"
        )
        self.assertEqual(hidden.status_code, 404, hidden.text)

        self._as("admin")
        admin_hidden = self.client.get(
            f"/api/projects/{self.project.id}/notification-endpoints"
        )
        self.assertEqual(admin_hidden.status_code, 404, admin_hidden.text)

    def test_notification_recipient_directory_is_manage_scoped_and_hides_outsiders(self):
        self._as("editor")
        members = self.client.get(f"/api/projects/{self.project.id}/members")
        self.assertEqual(members.status_code, 403, members.text)

        directory = self.client.get(
            f"/api/projects/{self.project.id}/notification-recipients"
        )
        self.assertEqual(directory.status_code, 200, directory.text)
        items = directory.json()["items"]
        self.assertEqual(
            {
                (item["user_id"], item["username"], item["role"])
                for item in items
            },
            {
                (str(self.users["owner"].id), self.users["owner"].username, "owner"),
                (str(self.users["editor"].id), self.users["editor"].username, "editor"),
                (str(self.users["operator"].id), self.users["operator"].username, "operator"),
                (str(self.users["viewer"].id), self.users["viewer"].username, "viewer"),
            },
        )
        self.assertTrue(all(set(item) == {"user_id", "username", "role"} for item in items))
        self.assertNotIn(str(self.users["outsider"].id), {item["user_id"] for item in items})

        selected_editor_id = next(
            item["user_id"] for item in items if item["role"] == "editor"
        )
        created = self.client.post(
            f"/api/projects/{self.project.id}/notification-endpoints",
            json={
                "kind": "in_app",
                "name": "editor-directory-endpoint",
                "config": {"recipient_user_ids": [selected_editor_id]},
            },
        )
        self.assertEqual(created.status_code, 201, created.text)

        for role in ("operator", "viewer"):
            with self.subTest(role=role):
                self._as(role)
                denied = self.client.get(
                    f"/api/projects/{self.project.id}/notification-recipients"
                )
                self.assertEqual(denied.status_code, 403, denied.text)

        self._as("outsider")
        hidden = self.client.get(
            f"/api/projects/{self.project.id}/notification-recipients"
        )
        self.assertEqual(hidden.status_code, 404, hidden.text)

    def test_endpoint_create_name_conflict_returns_stable_409(self):
        self._create_endpoint("duplicate-endpoint-name")
        conflict = self._request_without_server_exceptions(
            "post",
            f"/api/projects/{self.project.id}/notification-endpoints",
            json={
                "kind": "in_app",
                "name": "duplicate-endpoint-name",
                "config": {"recipient_user_ids": [str(self.users["owner"].id)]},
            },
        )

        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(
            conflict.json()["detail"]["code"],
            "NOTIFICATION_ENDPOINT_NAME_CONFLICT",
        )

    def test_endpoint_rename_name_conflict_returns_stable_409(self):
        original = self._create_endpoint("original-endpoint-name")
        renamed = self._create_endpoint("renamed-endpoint-name")
        conflict = self._request_without_server_exceptions(
            "patch",
            f"/api/projects/{self.project.id}/notification-endpoints/{renamed['id']}",
            json={"name": original["name"]},
        )

        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(
            conflict.json()["detail"]["code"],
            "NOTIFICATION_ENDPOINT_NAME_CONFLICT",
        )

    def test_subscription_validates_project_endpoint_and_explicit_recipients(self):
        endpoint = self._create_endpoint("subscription-endpoint")
        cross_project = self.client.post(
            f"/api/projects/{self.other_project.id}/notification-subscriptions",
            json={
                "endpoint_id": endpoint["id"],
                "event_types": ["inference.rollout.failed"],
                "recipient_user_ids": [str(self.users["owner"].id)],
            },
        )
        self.assertEqual(cross_project.status_code, 404, cross_project.text)

        non_member = self.client.post(
            f"/api/projects/{self.project.id}/notification-subscriptions",
            json={
                "endpoint_id": endpoint["id"],
                "event_types": ["inference.rollout.failed"],
                "recipient_user_ids": [str(self.users["outsider"].id)],
            },
        )
        self.assertEqual(non_member.status_code, 422, non_member.text)

        created = self.client.post(
            f"/api/projects/{self.project.id}/notification-subscriptions",
            json={
                "endpoint_id": endpoint["id"],
                "event_types": ["inference.rollout.failed"],
                "recipient_roles": ["operator"],
                "recipient_user_ids": [str(self.users["editor"].id)],
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        subscription_id = created.json()["id"]
        strict_patch = self.client.patch(
            f"/api/projects/{self.project.id}/notification-subscriptions/{subscription_id}",
            json={"enabled": False, "unknown": True},
        )
        self.assertEqual(strict_patch.status_code, 422, strict_patch.text)
        null_patch = self.client.patch(
            f"/api/projects/{self.project.id}/notification-subscriptions/{subscription_id}",
            json={"recipient_roles": None},
        )
        self.assertEqual(null_patch.status_code, 422, null_patch.text)
        updated = self.client.patch(
            f"/api/projects/{self.project.id}/notification-subscriptions/{subscription_id}",
            json={"enabled": False},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertFalse(updated.json()["enabled"])
        deleted = self.client.delete(
            f"/api/projects/{self.project.id}/notification-subscriptions/{subscription_id}"
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)
        subscription_actions = {
            event.action
            for event in self.db.query(AuditEvent).filter(
                AuditEvent.project_id == self.project.id,
                AuditEvent.resource_type == "notification_subscription",
                AuditEvent.result == "success",
            )
        }
        self.assertTrue({
            "notification.subscription.create",
            "notification.subscription.update",
            "notification.subscription.delete",
        }.issubset(subscription_actions))

    def test_subscription_recipient_ids_are_manage_scoped(self):
        endpoint = self._create_endpoint("recipient-privacy-endpoint")
        created = self.client.post(
            f"/api/projects/{self.project.id}/notification-subscriptions",
            json={
                "endpoint_id": endpoint["id"],
                "event_types": ["inference.rollout.failed"],
                "recipient_user_ids": [str(self.users["editor"].id)],
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        created_id = created.json()["id"]

        for role in ("operator", "viewer"):
            with self.subTest(role=role):
                self._as(role)
                response = self.client.get(
                    f"/api/projects/{self.project.id}/notification-subscriptions"
                )
                self.assertEqual(response.status_code, 200, response.text)
                subscription = next(
                    item for item in response.json()["items"] if item["id"] == created_id
                )
                self.assertEqual(subscription["recipient_user_ids"], [])
                self.assertNotIn(str(self.users["editor"].id), response.text)

        self._as("editor")
        manager_response = self.client.get(
            f"/api/projects/{self.project.id}/notification-subscriptions"
        )
        self.assertEqual(manager_response.status_code, 200, manager_response.text)
        manager_subscription = next(
            item
            for item in manager_response.json()["items"]
            if item["id"] == created_id
        )
        self.assertEqual(
            manager_subscription["recipient_user_ids"],
            [str(self.users["editor"].id)],
        )

    def test_external_subscriptions_do_not_require_in_app_recipient_selectors(self):
        with patch(
            "app.services.webhook_security._resolve_host",
            return_value=["8.8.8.8"],
        ):
            endpoint = self.client.post(
                f"/api/projects/{self.project.id}/notification-endpoints",
                json={
                    "kind": "webhook",
                    "name": "external-subscription-endpoint",
                    "config": {"url": "https://hooks.example.invalid/notification"},
                },
            )
        self.assertEqual(endpoint.status_code, 201, endpoint.text)

        created = self.client.post(
            f"/api/projects/{self.project.id}/notification-subscriptions",
            json={
                "endpoint_id": endpoint.json()["id"],
                "event_types": ["inference.rollout.failed"],
            },
        )
        self.assertEqual(created.status_code, 201, created.text)

        updated = self.client.patch(
            f"/api/projects/{self.project.id}/notification-subscriptions/{created.json()['id']}",
            json={"enabled": False},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertFalse(updated.json()["enabled"])

    def test_patch_schemas_reject_explicit_nulls(self):
        endpoint_fields = ("name", "config", "enabled")
        for field in endpoint_fields:
            with self.subTest(schema="endpoint", field=field):
                with self.assertRaises(ValidationError):
                    NotificationEndpointUpdate.model_validate({field: None})

        subscription_fields = (
            "endpoint_id",
            "event_types",
            "minimum_severity",
            "recipient_roles",
            "recipient_user_ids",
            "enabled",
        )
        for field in subscription_fields:
            with self.subTest(schema="subscription", field=field):
                with self.assertRaises(ValidationError):
                    NotificationSubscriptionUpdate.model_validate({field: None})

    def test_patch_routes_reject_explicit_nulls(self):
        endpoint = self._create_endpoint("null-patch-endpoint")
        subscription = self.client.post(
            f"/api/projects/{self.project.id}/notification-subscriptions",
            json={
                "endpoint_id": endpoint["id"],
                "event_types": ["inference.rollout.failed"],
                "recipient_roles": ["owner"],
            },
        )
        self.assertEqual(subscription.status_code, 201, subscription.text)

        for field in ("name", "config", "enabled"):
            with self.subTest(resource="endpoint", field=field):
                response = self.client.patch(
                    f"/api/projects/{self.project.id}/notification-endpoints/{endpoint['id']}",
                    json={field: None},
                )
                self.assertEqual(response.status_code, 422, response.text)

        for field in (
            "endpoint_id",
            "event_types",
            "minimum_severity",
            "recipient_roles",
            "recipient_user_ids",
            "enabled",
        ):
            with self.subTest(resource="subscription", field=field):
                response = self.client.patch(
                    f"/api/projects/{self.project.id}/notification-subscriptions/{subscription.json()['id']}",
                    json={field: None},
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_in_app_notifications_are_recipient_private_and_mutable_only_by_recipient(self):
        own_notification = InAppNotification(
            recipient_user_id=self.users["owner"].id,
            project_id=self.project.id,
            event_id=uuid.uuid4(),
            event_type="notification.api.own",
            severity="warning",
            title="Own notification",
            body="Owner only",
            payload={"safe": True},
        )
        other_notification = InAppNotification(
            recipient_user_id=self.users["editor"].id,
            project_id=self.project.id,
            event_id=uuid.uuid4(),
            event_type="notification.api.other",
            severity="warning",
            title="Other notification",
            body="Editor only",
            payload={"safe": True},
        )
        self.db.add_all((own_notification, other_notification))
        self.db.commit()

        listed = self.client.get("/api/notifications")
        self.assertEqual(listed.status_code, 200, listed.text)
        listed_ids = {item["id"] for item in listed.json()["items"]}
        self.assertIn(str(own_notification.id), listed_ids)
        self.assertNotIn(str(other_notification.id), listed_ids)
        unread = self.client.get("/api/notifications/unread-count")
        self.assertEqual(unread.status_code, 200, unread.text)
        self.assertGreaterEqual(unread.json()["count"], 1)

        other_read = self.client.patch(f"/api/notifications/{other_notification.id}/read")
        self.assertEqual(other_read.status_code, 404, other_read.text)
        read = self.client.patch(f"/api/notifications/{own_notification.id}/read")
        self.assertEqual(read.status_code, 200, read.text)
        archived = self.client.patch(f"/api/notifications/{own_notification.id}/archive")
        self.assertEqual(archived.status_code, 200, archived.text)

    def test_endpoint_test_uses_safe_response_and_admin_retry_is_audited(self):
        endpoint = self._create_endpoint("testable-endpoint")
        tested = self.client.post(
            f"/api/projects/{self.project.id}/notification-endpoints/{endpoint['id']}/test"
        )
        self.assertEqual(tested.status_code, 200, tested.text)
        self.assertEqual(set(tested.json()), {"status", "error_code"})

        persisted_endpoint = self.db.get(NotificationEndpoint, uuid.UUID(endpoint["id"]))
        outbox = NotificationOutbox(
            event_id=uuid.uuid4(),
            idempotency_key=f"notification-api-outbox-{uuid.uuid4()}",
            event_type="rollout.failed",
            severity="critical",
            occurred_at=datetime.now(timezone.utc),
            project_id=self.project.id,
            actor_id=self.users["owner"].id,
            resource_type="notification_endpoint",
            resource_id=str(persisted_endpoint.id),
            payload={"safe": True},
            status="failed",
            attempts=1,
            last_error_code="NOTIFICATION_PROVIDER_REJECTED",
        )
        self.db.add(outbox)
        self.db.flush()
        subscription = NotificationSubscription(
            project_id=self.project.id,
            endpoint_id=persisted_endpoint.id,
            event_types=["rollout.failed"],
            minimum_severity="info",
            recipient_roles=["owner"],
            recipient_user_ids=[],
            enabled=True,
            created_by_id=self.users["owner"].id,
        )
        self.db.add(subscription)
        self.db.flush()
        delivery = NotificationDelivery(
            outbox_id=outbox.id,
            subscription_id=subscription.id,
            endpoint_id=persisted_endpoint.id,
            idempotency_key=f"notification-api-delivery-{uuid.uuid4()}",
            status="failed",
            attempts=1,
            provider_metadata={"body": "must-not-leak"},
            last_error_code="NOTIFICATION_PROVIDER_REJECTED",
        )
        self.db.add(delivery)
        self.db.commit()

        self._as("admin")
        listed = self.client.get("/api/admin/notification-deliveries")
        self.assertEqual(listed.status_code, 200, listed.text)
        item = next(
            candidate
            for candidate in listed.json()["items"]
            if candidate["id"] == str(delivery.id)
        )
        self.assertNotIn("config", json.dumps(item))
        self.assertNotIn("provider_metadata", item)
        self.assertNotIn("must-not-leak", json.dumps(item))

        retried = self.client.post(f"/api/admin/notification-deliveries/{delivery.id}/retry")
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["status"], "pending")
        retried_outbox = self.db.get(NotificationOutbox, outbox.id)
        self.assertEqual(retried_outbox.status, "pending")
        adapter = Mock()
        adapter.send.return_value = DeliveryResult("sent")
        scheduler_result = execute_notification_delivery(
            retried_outbox.id,
            session_factory=self.Session,
            adapter_factory=lambda _db: adapter,
        )
        self.db.expire_all()
        self.assertEqual(
            scheduler_result,
            "sent",
            {
                "outbox_status": self.db.get(NotificationOutbox, outbox.id).status,
                "delivery_states": [
                    (row.id, row.status, row.last_error_code)
                    for row in self.db.query(NotificationDelivery)
                    .filter(NotificationDelivery.outbox_id == outbox.id)
                    .all()
                ],
            },
        )
        self.db.refresh(delivery)
        self.assertEqual(delivery.status, "sent")
        event = (
            self.db.query(PlatformAuditEvent)
            .filter(
                PlatformAuditEvent.action == "platform.notification.delivery_retry",
                PlatformAuditEvent.resource_id == str(delivery.id),
                PlatformAuditEvent.result == "success",
            )
            .one()
        )
        self.assertEqual(event.actor_id, self.users["admin"].id)

    def test_in_app_endpoint_test_is_per_recipient_idempotent(self):
        endpoint = self._create_endpoint("idempotent-test-endpoint")
        for _ in range(2):
            tested = self.client.post(
                f"/api/projects/{self.project.id}/notification-endpoints/{endpoint['id']}/test"
            )
            self.assertEqual(tested.status_code, 200, tested.text)
            self.assertEqual(tested.json()["status"], "sent")

        event_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"notification-test:{endpoint['id']}:{self.users['owner'].id}",
        )
        notifications = self.db.query(InAppNotification).filter(
            InAppNotification.event_id == event_id,
            InAppNotification.recipient_user_id == self.users["owner"].id,
        ).all()
        self.assertEqual(len(notifications), 1)
        self.assertEqual(len(notifications[0].deduplication_key), 64)

    def test_webhook_endpoint_test_revalidates_ssrf_and_hides_provider_body(self):
        signing_secret = "webhook-test-provider-secret"
        with patch(
            "app.services.webhook_security._resolve_host",
            return_value=["8.8.8.8"],
        ):
            created = self.client.post(
                f"/api/projects/{self.project.id}/notification-endpoints",
                json={
                    "kind": "webhook",
                    "name": "safe-webhook-test-endpoint",
                    "config": {
                        "url": "https://hooks.example.invalid/notification",
                        "signature_mode": "hmac-sha256",
                        "signing_secret": signing_secret,
                    },
                },
            )
        self.assertEqual(created.status_code, 201, created.text)
        endpoint = self.db.get(NotificationEndpoint, uuid.UUID(created.json()["id"]))
        self.assertNotIn(signing_secret, endpoint.encrypted_config)

        with patch(
            "app.services.webhook_security._resolve_host",
            return_value=["127.0.0.1"],
        ), patch("app.services.notification_channels.httpx.post") as post:
            blocked = self.client.post(
                f"/api/projects/{self.project.id}/notification-endpoints/{endpoint.id}/test"
            )
        self.assertEqual(blocked.status_code, 200, blocked.text)
        self.assertEqual(blocked.json()["status"], "failed")
        self.assertEqual(
            blocked.json()["error_code"],
            "NOTIFICATION_ENDPOINT_FORBIDDEN",
        )
        post.assert_not_called()

        provider_response = Mock(status_code=400, text="provider-body-must-not-leak")
        with patch(
            "app.services.webhook_security._resolve_host",
            return_value=["8.8.8.8"],
        ), patch(
            "app.services.notification_channels.httpx.post",
            return_value=provider_response,
        ):
            tested = self.client.post(
                f"/api/projects/{self.project.id}/notification-endpoints/{endpoint.id}/test"
            )
        self.assertEqual(tested.status_code, 200, tested.text)
        self.assertEqual(set(tested.json()), {"status", "error_code"})
        self.assertEqual(tested.json()["status"], "failed")
        self.assertNotIn("provider-body-must-not-leak", tested.text)
        self.assertNotIn(signing_secret, tested.text)

    def _create_then_remove_in_app_member(self, name):
        removed_user = User(
            username=f"notification-removed-member-{uuid.uuid4().hex}",
            password_hash="hash",
            role="engineer",
        )
        self.db.add(removed_user)
        self.db.flush()
        membership = ProjectMember(
            project_id=self.project.id,
            user_id=removed_user.id,
            role="operator",
            created_by=self.users["owner"].id,
        )
        self.db.add(membership)
        self.db.commit()
        endpoint = self._create_endpoint(
            name,
            recipient_user_ids=[str(removed_user.id)],
        )
        self.db.delete(membership)
        self.db.commit()
        return removed_user, endpoint

    def test_in_app_endpoint_test_rejects_removed_configured_recipient(self):
        _removed_user, endpoint = self._create_then_remove_in_app_member(
            "removed-member-test-endpoint"
        )

        tested = self.client.post(
            f"/api/projects/{self.project.id}/notification-endpoints/{endpoint['id']}/test"
        )

        self.assertEqual(tested.status_code, 422, tested.text)
        self.assertEqual(
            tested.json()["detail"]["code"],
            "NOTIFICATION_RECIPIENT_NOT_MEMBER",
        )

    def test_in_app_fanout_does_not_fall_back_to_stale_endpoint_recipients(self):
        removed_user, endpoint_response = self._create_then_remove_in_app_member(
            "removed-member-fanout-endpoint"
        )
        endpoint = self.db.get(
            NotificationEndpoint,
            uuid.UUID(endpoint_response["id"]),
        )
        subscription = NotificationSubscription(
            project_id=self.project.id,
            endpoint_id=endpoint.id,
            event_types=["runtime.load_failed"],
            minimum_severity="info",
            recipient_roles=[],
            recipient_user_ids=[str(removed_user.id)],
            enabled=True,
            created_by_id=self.users["owner"].id,
        )
        outbox = NotificationOutbox(
            event_id=uuid.uuid4(),
            idempotency_key=f"stale-recipient-outbox-{uuid.uuid4()}",
            event_type="runtime.load_failed",
            severity="critical",
            occurred_at=datetime.now(timezone.utc),
            project_id=self.project.id,
            actor_id=self.users["owner"].id,
            resource_type="notification_endpoint",
            resource_id=str(endpoint.id),
            payload={"deployment_id": str(self.project.id)},
            status="pending",
        )
        self.db.add_all((subscription, outbox))
        self.db.commit()

        result = execute_notification_delivery(
            outbox.id,
            session_factory=self.Session,
            adapter_factory=lambda db: NotificationChannelRouter(db, self.settings),
        )
        self.db.expire_all()
        delivery = self.db.query(NotificationDelivery).filter(
            NotificationDelivery.outbox_id == outbox.id,
        ).one()
        stale_notifications = self.db.query(InAppNotification).filter(
            InAppNotification.recipient_user_id == removed_user.id,
            InAppNotification.event_id == outbox.event_id,
        ).all()

        self.assertEqual(result, "failed")
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.last_error_code, "NOTIFICATION_RECIPIENT_INVALID")
        self.assertEqual(stale_notifications, [])

    def test_admin_retry_rejects_active_or_sent_delivery_and_sent_parent(self):
        endpoint = self._create_endpoint("terminal-retry-endpoint")
        persisted_endpoint = self.db.get(NotificationEndpoint, uuid.UUID(endpoint["id"]))
        outbox = NotificationOutbox(
            event_id=uuid.uuid4(),
            idempotency_key=f"notification-retry-guard-outbox-{uuid.uuid4()}",
            event_type="notification.api.delivery",
            severity="critical",
            occurred_at=datetime.now(timezone.utc),
            project_id=self.project.id,
            actor_id=self.users["owner"].id,
            resource_type="notification_endpoint",
            resource_id=str(persisted_endpoint.id),
            payload={"safe": True},
            status="processing",
            attempts=1,
            claimed_at=datetime.now(timezone.utc),
        )
        self.db.add(outbox)
        self.db.flush()
        delivery = NotificationDelivery(
            outbox_id=outbox.id,
            endpoint_id=persisted_endpoint.id,
            idempotency_key=f"notification-retry-guard-delivery-{uuid.uuid4()}",
            status="processing",
            attempts=1,
            claim_token="active-delivery-claim",
            claimed_at=datetime.now(timezone.utc),
        )
        self.db.add(delivery)
        self.db.commit()

        self._as("admin")
        active_retry = self.client.post(f"/api/admin/notification-deliveries/{delivery.id}/retry")
        self.assertEqual(active_retry.status_code, 409, active_retry.text)
        self.db.refresh(delivery)
        self.assertEqual(delivery.status, "processing")
        self.assertEqual(delivery.claim_token, "active-delivery-claim")

        delivery.status = "sent"
        delivery.claim_token = None
        delivery.claimed_at = None
        outbox.status = "sent"
        outbox.claimed_at = None
        self.db.commit()
        sent_retry = self.client.post(f"/api/admin/notification-deliveries/{delivery.id}/retry")
        self.assertEqual(sent_retry.status_code, 409, sent_retry.text)
        self.db.refresh(delivery)
        self.assertEqual(delivery.status, "sent")

        # A stale administrator retry must not reopen a parent that another
        # delivery has already settled successfully.
        delivery.status = "failed"
        delivery.last_error_code = "NOTIFICATION_PROVIDER_REJECTED"
        self.db.commit()
        sent_parent_retry = self.client.post(
            f"/api/admin/notification-deliveries/{delivery.id}/retry"
        )
        self.assertEqual(sent_parent_retry.status_code, 409, sent_parent_retry.text)
        self.db.refresh(delivery)
        self.db.refresh(outbox)
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(outbox.status, "sent")


if __name__ == "__main__":
    unittest.main()
