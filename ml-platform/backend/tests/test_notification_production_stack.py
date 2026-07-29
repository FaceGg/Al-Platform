"""Opt-in PostgreSQL, Redis, Celery, and controlled notification acceptance."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time
import unittest
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import httpx
from redis import Redis

import app.main  # noqa: F401 (load the production model graph)
from app.api.auth import create_access_token
from app.config import settings
from app.database import SessionLocal, engine
from app.events.domain import DomainEvent
from app.main import app
from app.models.access import ProjectMember
from app.models.notifications import (
    InAppNotification,
    NotificationDelivery,
    NotificationEndpoint,
    NotificationOutbox,
    NotificationSubscription,
)
from app.models.project import Project
from app.models.user import User
from app.services.notification_channels import NotificationChannelRouter
from app.services.notification_crypto import encrypt_config
from app.services.notification_outbox import OutboxDomainEventRecorder
from app.services.webhook_security import WebhookSecurityError, validate_webhook_url
from app.tasks.celery_app import celery_app
from app.tasks.notification_tasks import deliver_notifications_task, execute_notification_delivery


def public_resolution(_host: str, _port: int) -> list[str]:
    return ["8.8.8.8"]


class ControlledResponse:
    def __init__(self, status_code: int, payload: object | None = None) -> None:
        self.status_code = status_code
        self._payload = {} if payload is None else payload

    def json(self) -> object:
        return self._payload


class RecordingHttpClient:
    def __init__(self, response: ControlledResponse | None = None, *, raises_timeout: bool = False) -> None:
        self.response = response or ControlledResponse(201)
        self.raises_timeout = raises_timeout
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> ControlledResponse:
        self.calls.append({"url": url, **kwargs})
        if self.raises_timeout:
            raise TimeoutError("controlled receiver timeout")
        return self.response


@unittest.skipUnless(
    os.getenv("RUN_NOTIFICATION_INTEGRATION") == "1",
    "RUN_NOTIFICATION_INTEGRATION is not enabled",
)
class TestNotificationProductionStack(unittest.TestCase):
    """Run only in the isolated Week 10 Compose project prepared by CI/WSL."""

    @classmethod
    def setUpClass(cls) -> None:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("Notification integration requires PostgreSQL")
        if settings.resolved_notification_master_key is None:
            raise RuntimeError("NOTIFICATION_MASTER_KEY is not configured")
        if settings.redis_events_url is None:
            raise RuntimeError("Redis events URL is not configured")
        if not settings.smtp_host or not settings.smtp_from:
            raise RuntimeError("Controlled SMTP settings are not configured")
        if "ml_platform.deliver_notifications" not in celery_app.tasks:
            raise RuntimeError("Notification delivery task is not registered")

        cls.redis = Redis.from_url(
            settings.redis_events_url.get_secret_value(),
            decode_responses=True,
        )
        cls.redis.ping()
        with celery_app.connection_for_read() as connection:
            connection.ensure_connection(max_retries=1)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if celery_app.control.ping(timeout=5.0):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("No isolated Week 10 Celery worker responded")

        cls.prefix = f"week10-notification-{uuid4().hex}"
        with SessionLocal() as db:
            cls.users = {
                role: User(
                    username=f"{cls.prefix}-{role}",
                    password_hash="integration-only-hash",
                    role="admin" if role == "admin" else "engineer",
                )
                for role in ("owner", "editor", "operator", "viewer", "outsider", "admin")
            }
            db.add_all(cls.users.values())
            db.flush()
            project = Project(
                name=f"{cls.prefix}-project",
                owner_id=cls.users["owner"].id,
            )
            db.add(project)
            db.flush()
            db.add_all(
                ProjectMember(
                    project_id=project.id,
                    user_id=cls.users[role].id,
                    role=role,
                    created_by=cls.users["owner"].id,
                )
                for role in ("editor", "operator", "viewer")
            )
            db.commit()
            cls.project_id = project.id
            cls.user_ids = tuple(user.id for user in cls.users.values())

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            with SessionLocal() as db:
                project = db.get(Project, cls.project_id)
                if project is not None:
                    db.delete(project)
                    db.flush()
                db.query(User).filter(User.id.in_(cls.user_ids)).delete(
                    synchronize_session=False,
                )
                db.commit()
        finally:
            cls.redis.close()

    def setUp(self) -> None:
        self._clear_notification_state()

    def tearDown(self) -> None:
        self._clear_notification_state()

    @classmethod
    def _clear_notification_state(cls) -> None:
        """Keep each production scenario from subscribing later scenarios."""
        with SessionLocal() as db:
            db.query(InAppNotification).filter(
                InAppNotification.project_id == cls.project_id,
            ).delete(synchronize_session=False)
            db.query(NotificationOutbox).filter(
                NotificationOutbox.project_id == cls.project_id,
            ).delete(synchronize_session=False)
            db.query(NotificationEndpoint).filter(
                NotificationEndpoint.project_id == cls.project_id,
            ).delete(synchronize_session=False)
            db.commit()

    @classmethod
    def _endpoint(
        cls,
        db,
        *,
        kind: str,
        name: str,
        config: dict[str, object],
    ) -> NotificationEndpoint:
        master_key = settings.resolved_notification_master_key
        assert master_key is not None
        endpoint = NotificationEndpoint(
            project_id=cls.project_id,
            kind=kind,
            name=f"{cls.prefix}-{name}-{uuid4().hex}",
            destination_hint="controlled receiver",
            encrypted_config=encrypt_config(config, master_key),
            created_by_id=cls.users["owner"].id,
        )
        db.add(endpoint)
        db.flush()
        return endpoint

    @classmethod
    def _subscription(
        cls,
        db,
        endpoint: NotificationEndpoint,
        *,
        roles: list[str] | None = None,
    ) -> NotificationSubscription:
        subscription = NotificationSubscription(
            project_id=cls.project_id,
            endpoint_id=endpoint.id,
            event_types=["rollout.completed"],
            minimum_severity="info",
            recipient_roles=roles or ["owner"],
            recipient_user_ids=[],
            created_by_id=cls.users["owner"].id,
        )
        db.add(subscription)
        db.flush()
        return subscription

    @classmethod
    def _event(cls, name: str, *, deployment_id: str = "deployment-controlled") -> DomainEvent:
        return DomainEvent(
            event_id=uuid4(),
            idempotency_key=f"{cls.prefix}:{name}:{uuid4().hex}",
            event_type="rollout.completed",
            severity="warning",
            occurred_at=datetime.now(timezone.utc),
            project_id=cls.project_id,
            actor_id=cls.users["owner"].id,
            resource_type="inference_deployment",
            resource_id=deployment_id,
            payload={
                "deployment_id": deployment_id,
                "secret": "must-not-reach-controlled-receivers",
            },
        )

    @staticmethod
    def _headers(user_id: UUID) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}

    def test_01_real_postgres_redis_celery_delivers_in_app_once(self) -> None:
        with SessionLocal() as db:
            endpoint = self._endpoint(
                db,
                kind="in_app",
                name="celery-in-app",
                config={"recipient_user_ids": [str(self.users["owner"].id)]},
            )
            self._subscription(db, endpoint)
            event = self._event("celery-in-app")
            recorder = OutboxDomainEventRecorder()
            recorder.record(db, event)
            recorder.record(db, event)
            db.commit()
            outbox = db.query(NotificationOutbox).filter(
                NotificationOutbox.event_id == event.event_id,
            ).one()
            outbox_id = outbox.id
            self.assertEqual(
                db.query(NotificationOutbox).filter(
                    NotificationOutbox.event_id == event.event_id,
                ).count(),
                1,
            )

        outcome = deliver_notifications_task.delay(str(outbox_id)).get(timeout=30)
        self.assertEqual(outcome, "sent")

        with SessionLocal() as db:
            outbox = db.get(NotificationOutbox, outbox_id)
            self.assertIsNotNone(outbox)
            self.assertEqual(outbox.status, "sent")
            delivery = db.query(NotificationDelivery).filter(
                NotificationDelivery.outbox_id == outbox_id,
            ).one()
            self.assertEqual((delivery.status, delivery.attempts), ("sent", 1))
            notice = db.query(InAppNotification).filter(
                InAppNotification.event_id == event.event_id,
                InAppNotification.recipient_user_id == self.users["owner"].id,
            ).one()
            self.assertEqual(notice.payload, {"deployment_id": "deployment-controlled"})
            self.assertNotIn("must-not-reach", json.dumps(notice.payload))

    def test_02_controlled_external_channels_enforce_redaction_and_limits(self) -> None:
        with SessionLocal() as db:
            event = self._event("controlled-channels")
            in_app = self._endpoint(
                db,
                kind="in_app",
                name="in-app",
                config={"recipient_user_ids": [str(self.users["owner"].id)]},
            )
            webhook = self._endpoint(
                db,
                kind="webhook",
                name="webhook",
                config={
                    "url": "https://receiver.week10.invalid/notification",
                    "headers": {},
                    "signature_mode": "none",
                },
            )
            wecom = self._endpoint(
                db,
                kind="wecom",
                name="wecom",
                config={
                    "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=controlled-week10",
                },
            )
            email = self._endpoint(
                db,
                kind="email",
                name="email",
                config={"to": ["receiver@week10.invalid"], "cc": []},
            )
            db.commit()

            self.assertNotIn("receiver@week10.invalid", email.encrypted_config)
            in_app_result = NotificationChannelRouter(db, settings).send(
                endpoint=in_app,
                event=event,
                delivery_key=f"{self.prefix}:in-app",
                recipient_user_ids=(self.users["owner"].id,),
            )
            self.assertEqual(in_app_result.status, "sent")

            webhook_receiver = RecordingHttpClient(ControlledResponse(201))
            webhook_result = NotificationChannelRouter(
                db,
                settings,
                http_client=webhook_receiver,
                resolve=public_resolution,
            ).send(endpoint=webhook, event=event, delivery_key=f"{self.prefix}:webhook")
            self.assertEqual(webhook_result.status, "sent")
            self.assertEqual(webhook_receiver.calls[0]["follow_redirects"], False)
            self.assertNotIn(
                b"must-not-reach-controlled-receivers",
                webhook_receiver.calls[0]["content"],
            )

            wecom_receiver = RecordingHttpClient(ControlledResponse(200, {"errcode": 0}))
            wecom_result = NotificationChannelRouter(
                db,
                settings,
                http_client=wecom_receiver,
                resolve=public_resolution,
            ).send(endpoint=wecom, event=event, delivery_key=f"{self.prefix}:wecom")
            self.assertEqual(wecom_result.status, "sent")
            self.assertTrue(
                str(wecom_receiver.calls[0]["url"]).startswith(
                    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
                )
            )

            redirect_receiver = RecordingHttpClient(ControlledResponse(302))
            redirect_result = NotificationChannelRouter(
                db,
                settings,
                http_client=redirect_receiver,
                resolve=public_resolution,
            ).send(endpoint=webhook, event=event, delivery_key=f"{self.prefix}:redirect")
            self.assertEqual(redirect_result.status, "failed")
            self.assertEqual(redirect_receiver.calls[0]["follow_redirects"], False)

            with self.assertRaises(WebhookSecurityError):
                validate_webhook_url(
                    "https://metadata.google.internal/latest",
                    resolve=public_resolution,
                )
            with self.assertRaises(WebhookSecurityError):
                validate_webhook_url(
                    "https://receiver.week10.invalid/notification",
                    resolve=lambda _host, _port: ["10.0.0.8"],
                )

            timed_out = NotificationChannelRouter(
                db,
                settings,
                http_client=RecordingHttpClient(raises_timeout=True),
                resolve=public_resolution,
            ).send(endpoint=webhook, event=event, delivery_key=f"{self.prefix}:timeout")
            self.assertEqual(timed_out.status, "retry")

            too_many = self._endpoint(
                db,
                kind="email",
                name="recipient-cap",
                config={"to": [f"recipient-{index}@week10.invalid" for index in range(51)], "cc": []},
            )
            capped = NotificationChannelRouter(db, settings).send(
                endpoint=too_many,
                event=event,
                delivery_key=f"{self.prefix}:recipient-cap",
            )
            self.assertEqual(capped.error_code, "NOTIFICATION_EMAIL_RECIPIENT_LIMIT")

    def test_03_real_mailpit_receives_only_the_safe_email_envelope(self) -> None:
        receiver_url = os.getenv("NOTIFICATION_TEST_SMTP_API_URL")
        self.assertIsNotNone(receiver_url)
        recipient = f"{self.prefix}-mailpit@week10.invalid"
        with SessionLocal() as db:
            event = self._event("mailpit")
            email = self._endpoint(
                db,
                kind="email",
                name="mailpit",
                config={"to": [recipient], "cc": []},
            )
            self._subscription(db, email)
            OutboxDomainEventRecorder().record(db, event)
            db.commit()
            outbox_id = db.query(NotificationOutbox.id).filter(
                NotificationOutbox.event_id == event.event_id,
            ).scalar()

        self.assertIsNotNone(outbox_id)
        outcome = deliver_notifications_task.delay(str(outbox_id)).get(timeout=30)
        self.assertEqual(outcome, "sent")

        deadline = time.monotonic() + 10.0
        response = None
        matching_message = None
        while time.monotonic() < deadline:
            response = httpx.get(receiver_url, timeout=5.0)
            self.assertEqual(response.status_code, 200, response.text)
            messages = response.json().get("messages", [])
            matching_message = next(
                (message for message in messages if recipient in json.dumps(message)),
                None,
            )
            if matching_message is not None:
                break
            time.sleep(0.2)

        self.assertIsNotNone(response)
        self.assertIsNotNone(matching_message, response.text)
        rendered_message = json.dumps(matching_message)
        self.assertIn("WARNING: rollout.completed", rendered_message)
        self.assertIn("rollout.completed for inference_deployment", rendered_message)
        self.assertNotIn("must-not-reach-controlled-receivers", rendered_message)

    @unittest.skipUnless(
        os.getenv("RUN_NOTIFICATION_EXTERNAL_RECEIVER_INTEGRATION") == "1",
        "RUN_NOTIFICATION_EXTERNAL_RECEIVER_INTEGRATION is not enabled",
    )
    def test_05_real_worker_delivers_webhook_and_wecom_to_controlled_receiver(self) -> None:
        webhook_url = os.getenv("NOTIFICATION_TEST_WEBHOOK_URL")
        wecom_url = os.getenv("NOTIFICATION_TEST_WECOM_URL")
        events_url = os.getenv("NOTIFICATION_TEST_RECEIVER_EVENTS_URL")
        self.assertTrue(webhook_url)
        self.assertTrue(wecom_url)
        self.assertTrue(events_url)
        deployment_id = f"controlled-external-{uuid4().hex}"

        with SessionLocal() as db:
            event = self._event("controlled-external", deployment_id=deployment_id)
            webhook = self._endpoint(
                db,
                kind="webhook",
                name="controlled-webhook",
                config={
                    "url": webhook_url,
                    "headers": {},
                    "signature_mode": "none",
                },
            )
            wecom = self._endpoint(
                db,
                kind="wecom",
                name="controlled-wecom",
                config={"url": wecom_url},
            )
            self._subscription(db, webhook)
            self._subscription(db, wecom)
            OutboxDomainEventRecorder().record(db, event)
            db.commit()
            outbox_id = db.query(NotificationOutbox.id).filter(
                NotificationOutbox.event_id == event.event_id,
            ).scalar()

        self.assertIsNotNone(outbox_id)
        self.assertEqual(deliver_notifications_task.delay(str(outbox_id)).get(timeout=30), "sent")

        deadline = time.monotonic() + 15.0
        matched_events = []
        while time.monotonic() < deadline:
            response = httpx.get(events_url, timeout=5.0)
            self.assertEqual(response.status_code, 200, response.text)
            matched_events = [
                item
                for item in response.json().get("events", [])
                if deployment_id in json.dumps(item, sort_keys=True)
            ]
            if len(matched_events) >= 2:
                break
            time.sleep(0.2)

        self.assertGreaterEqual(len(matched_events), 2)
        serialized = json.dumps(matched_events, sort_keys=True)
        self.assertIn('"msgtype": "text"', serialized)
        self.assertIn('"resource_id": "' + deployment_id + '"', serialized)
        self.assertNotIn("must-not-reach-controlled-receivers", serialized)

    def test_04_retry_exhaustion_creates_one_dead_letter_alert(self) -> None:
        with SessionLocal() as db:
            endpoint = self._endpoint(
                db,
                kind="webhook",
                name="retry",
                config={
                    "url": "https://receiver.week10.invalid/retry",
                    "headers": {},
                    "signature_mode": "none",
                },
            )
            self._subscription(db, endpoint, roles=["operator"])
            retry_endpoint_id = endpoint.id
            event = self._event("retry-exhaustion")
            OutboxDomainEventRecorder().record(db, event)
            db.commit()
            outbox_id = db.query(NotificationOutbox.id).filter(
                NotificationOutbox.event_id == event.event_id,
            ).scalar()

        retry_receiver = RecordingHttpClient(ControlledResponse(503))
        now = datetime(2030, 1, 1, 0, 0, 0)
        for _attempt in range(settings.notification_delivery_max_attempts + 1):
            execute_notification_delivery(
                outbox_id,
                now=now,
                adapter_factory=lambda db: NotificationChannelRouter(
                    db,
                    settings,
                    http_client=retry_receiver,
                    resolve=public_resolution,
                ),
            )
            with SessionLocal() as db:
                delivery = db.query(NotificationDelivery).filter(
                    NotificationDelivery.outbox_id == outbox_id,
                    NotificationDelivery.endpoint_id == retry_endpoint_id,
                ).one()
                if delivery.status == "dead_letter":
                    break
                self.assertEqual(delivery.status, "retry")
                self.assertIsNotNone(delivery.next_attempt_at)
                now = delivery.next_attempt_at
        else:
            self.fail("controlled retry never reached dead letter")

        with SessionLocal() as db:
            outbox = db.get(NotificationOutbox, outbox_id)
            delivery = db.query(NotificationDelivery).filter(
                NotificationDelivery.outbox_id == outbox_id,
                NotificationDelivery.endpoint_id == retry_endpoint_id,
            ).one()
            alerts = db.query(InAppNotification).filter(
                InAppNotification.event_id == event.event_id,
                InAppNotification.event_type == "notification.dead_letter",
            ).all()
            self.assertEqual((outbox.status, delivery.status), ("dead_letter", "dead_letter"))
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0].recipient_user_id, self.users["operator"].id)

    def test_05_security_and_authorization_contracts_remain_live(self) -> None:
        client = TestClient(app)
        try:
            role_injection = client.post(
                "/api/auth/register",
                json={
                    "username": f"{self.prefix}-role-probe",
                    "password": "safe-integration-password",
                    "role": "admin",
                },
            )
            self.assertEqual(role_injection.status_code, 422, role_injection.text)

            owner_headers = self._headers(self.users["owner"].id)
            endpoint_response = client.post(
                f"/api/projects/{self.project_id}/notification-endpoints",
                headers=owner_headers,
                json={
                    "kind": "in_app",
                    "name": f"{self.prefix}-api-encrypted",
                    "config": {"recipient_user_ids": [str(self.users["owner"].id)]},
                },
            )
            self.assertEqual(endpoint_response.status_code, 201, endpoint_response.text)
            self.assertNotIn("config", endpoint_response.json())
            endpoint_id = UUID(endpoint_response.json()["id"])
            with SessionLocal() as db:
                endpoint = db.get(NotificationEndpoint, endpoint_id)
                self.assertIsNotNone(endpoint)
                self.assertNotIn(str(self.users["owner"].id), endpoint.encrypted_config)

            outsider_headers = self._headers(self.users["outsider"].id)
            project_admin_headers = self._headers(self.users["admin"].id)
            for path in (
                f"/api/projects/{self.project_id}/notification-endpoints",
                f"/api/compute/nodes/{uuid4()}",
                f"/api/compute/devices/{uuid4()}",
                f"/api/annotations/tasks/{uuid4()}/samples",
            ):
                response = client.get(path, headers=outsider_headers)
                self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(
                client.get(
                    f"/api/projects/{self.project_id}/notification-endpoints",
                    headers=project_admin_headers,
                ).status_code,
                404,
            )
            self.assertEqual(
                client.get("/api/admin/security-audit", headers=owner_headers).status_code,
                403,
            )
            self.assertEqual(
                client.get("/api/admin/security-audit", headers=project_admin_headers).status_code,
                200,
            )
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
