"""Security and delivery contracts for notification channels."""

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import tempfile
import unittest
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import Base
from app.events.domain import DomainEvent
from app.models.access import ProjectMember
from app.models.notifications import InAppNotification, NotificationEndpoint
from app.models.project import Project
from app.models.user import User

try:
    from app.services.notification_channels import NotificationChannelRouter
    from app.services.notification_crypto import (
        NotificationCredentialError,
        decrypt_config,
        encrypt_config,
    )
    from app.services.webhook_security import (
        WebhookSecurityError,
        canonical_json_bytes,
        validate_wecom_url,
        validate_webhook_url,
    )
except ModuleNotFoundError:
    NotificationChannelRouter = None
    NotificationCredentialError = None
    WebhookSecurityError = None
    canonical_json_bytes = None
    decrypt_config = None
    encrypt_config = None
    validate_wecom_url = None
    validate_webhook_url = None


MASTER_KEY = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")


def public_resolution(_host, _port):
    return ["8.8.8.8"]


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class RecordingHttpClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


class RecordingSMTP:
    def __init__(self):
        self.started_tls = False
        self.login_args = None
        self.sent = None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def starttls(self, **_kwargs):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def sendmail(self, sender, recipients, message):
        self.sent = (sender, recipients, message)


class TestNotificationChannelImports(unittest.TestCase):
    def test_notification_security_modules_are_available(self):
        self.assertIsNotNone(encrypt_config)
        self.assertIsNotNone(decrypt_config)
        self.assertIsNotNone(validate_webhook_url)
        self.assertIsNotNone(validate_wecom_url)
        self.assertIsNotNone(NotificationChannelRouter)


@unittest.skipIf(encrypt_config is None, "notification channel modules are unavailable")
class TestNotificationCrypto(unittest.TestCase):
    def setUp(self):
        self.master_key = SecretStr(MASTER_KEY)

    def test_endpoint_config_round_trip_never_exposes_plaintext(self):
        config = {
            "url": "https://hooks.example.invalid/x",
            "signing_secret": "test-signing-secret",
        }

        ciphertext = encrypt_config(config, self.master_key)

        self.assertNotIn("test-signing-secret", ciphertext)
        self.assertEqual(decrypt_config(ciphertext, self.master_key), config)

    def test_invalid_ciphertext_has_stable_error_code(self):
        with self.assertRaises(NotificationCredentialError) as raised:
            decrypt_config("not-a-fernet-token", self.master_key)

        self.assertEqual(raised.exception.code, "NOTIFICATION_CREDENTIAL_INVALID")


@unittest.skipIf(validate_webhook_url is None, "notification channel modules are unavailable")
class TestWebhookSecurity(unittest.TestCase):
    def test_webhook_rejects_loopback_private_metadata_and_invalid_url_parts(self):
        blocked = (
            "http://127.0.0.1/x",
            "https://10.0.0.2/x",
            "https://169.254.169.254/latest",
            "file:///tmp/notification",
            "https://user:pass@hooks.example.invalid/x",
            "https://hooks.example.invalid/x#fragment",
            "https://hooks.example.invalid:8443/x",
        )
        for url in blocked:
            with self.subTest(url=url):
                with self.assertRaises(WebhookSecurityError):
                    validate_webhook_url(url, resolve=lambda _host, _port: ["127.0.0.1"])

    def test_explicit_allowlist_is_required_for_private_relay(self):
        url = "https://relay.example.invalid/hooks"

        with self.assertRaises(WebhookSecurityError):
            validate_webhook_url(url, resolve=lambda _host, _port: ["10.0.0.2"])

        self.assertEqual(
            validate_webhook_url(
                url,
                resolve=lambda _host, _port: ["10.0.0.2"],
                allowlist=("relay.example.invalid",),
            ),
            url,
        )

    def test_canonical_payload_is_deterministic_and_bounded(self):
        encoded = canonical_json_bytes({"z": 1, "a": {"b": True}}, max_payload_bytes=128)
        self.assertEqual(encoded, b'{"a":{"b":true},"z":1}')

        with self.assertRaises(WebhookSecurityError) as raised:
            canonical_json_bytes({"payload": "x" * 256}, max_payload_bytes=64)

        self.assertEqual(raised.exception.code, "NOTIFICATION_PAYLOAD_TOO_LARGE")

    def test_wecom_requires_official_host_and_supported_path(self):
        with self.assertRaises(WebhookSecurityError):
            validate_wecom_url(
                "https://hooks.example.invalid/cgi-bin/webhook/send?key=x",
                resolve=public_resolution,
            )
        with self.assertRaises(WebhookSecurityError):
            validate_wecom_url(
                "https://qyapi.weixin.qq.com/unknown/path",
                resolve=public_resolution,
            )

        self.assertEqual(
            validate_wecom_url(
                "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=robot-key",
                resolve=public_resolution,
            ),
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=robot-key",
        )


@unittest.skipIf(NotificationChannelRouter is None, "notification channel modules are unavailable")
class TestNotificationAdapters(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.user = User(username="notification-recipient", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Channel security", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.commit()
        self.master_key = SecretStr(MASTER_KEY)
        self.settings = Settings(
            _env_file=None,
            notification_master_key=MASTER_KEY,
            smtp_host="smtp.example.invalid",
            smtp_from="ml-platform@example.invalid",
            smtp_username="smtp-user-secret",
            smtp_password="smtp-password-secret",
        )
        self.event = DomainEvent(
            event_id=uuid4(),
            idempotency_key="notification-event-1",
            event_type="rollout.completed",
            severity="warning",
            occurred_at=datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
            project_id=self.project.id,
            actor_id=self.user.id,
            resource_type="deployment",
            resource_id="deployment-1",
            payload={"revision_id": "revision-1", "secret": "must-not-send"},
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _endpoint(self, kind, config):
        endpoint = NotificationEndpoint(
            project_id=self.project.id,
            kind=kind,
            name=f"{kind}-{uuid4()}",
            destination_hint="safe hint",
            encrypted_config=encrypt_config(config, self.master_key),
            created_by_id=self.user.id,
        )
        self.db.add(endpoint)
        self.db.commit()
        return endpoint

    def test_in_app_adapter_writes_only_safe_event_fields(self):
        endpoint = self._endpoint("in_app", {})
        router = NotificationChannelRouter(self.db, self.settings)

        result = router.send(
            endpoint=endpoint,
            event=self.event,
            delivery_key="delivery-in-app",
            recipient_user_ids=(self.user.id,),
        )

        row = self.db.query(InAppNotification).one()
        self.assertEqual(result.status, "sent")
        self.assertEqual(row.recipient_user_id, self.user.id)
        self.assertEqual(row.payload, {"revision_id": "revision-1"})
        self.assertNotIn("must-not-send", json.dumps(row.payload))

    def test_in_app_adapter_rechecks_current_membership_at_insert(self):
        recipient = User(
            username=f"revoked-notification-recipient-{uuid4().hex}",
            password_hash="hash",
        )
        self.db.add(recipient)
        self.db.flush()
        membership = ProjectMember(
            project_id=self.project.id,
            user_id=recipient.id,
            role="operator",
            created_by=self.user.id,
        )
        self.db.add(membership)
        self.db.commit()

        endpoint = self._endpoint("in_app", {})
        stale_recipients = (recipient.id,)
        membership_revoked = False

        @event.listens_for(self.engine, "before_cursor_execute")
        def revoke_member_before_notification_insert(
            connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ):
            nonlocal membership_revoked
            normalized_statement = " ".join(statement.lower().split())
            if (
                membership_revoked
                or not normalized_statement.startswith("insert into in_app_notifications")
            ):
                return
            membership_revoked = True
            connection.execute(
                ProjectMember.__table__.delete().where(
                    ProjectMember.project_id == self.project.id,
                    ProjectMember.user_id == recipient.id,
                )
            )

        try:
            result = NotificationChannelRouter(self.db, self.settings).send(
                endpoint=endpoint,
                event=self.event,
                delivery_key="delivery-revoked-recipient",
                recipient_user_ids=stale_recipients,
            )
        finally:
            event.remove(
                self.engine,
                "before_cursor_execute",
                revoke_member_before_notification_insert,
            )

        self.assertTrue(membership_revoked)
        self.assertEqual(
            (result.status, result.error_code),
            ("failed", "NOTIFICATION_RECIPIENT_INVALID"),
        )
        self.assertEqual(
            self.db.query(InAppNotification)
            .filter(InAppNotification.recipient_user_id == recipient.id)
            .count(),
            0,
        )

    def test_missing_master_key_has_unavailable_error_code(self):
        endpoint = self._endpoint("in_app", {})
        unconfigured = Settings(_env_file=None)

        result = NotificationChannelRouter(self.db, unconfigured).send(
            endpoint=endpoint,
            event=self.event,
            delivery_key="delivery-missing-master-key",
            recipient_user_ids=(self.user.id,),
        )

        self.assertEqual(
            (result.status, result.error_code),
            ("failed", "NOTIFICATION_CREDENTIAL_UNAVAILABLE"),
        )

    def test_webhook_uses_canonical_hmac_and_disables_redirects(self):
        signing_secret = "webhook-signing-secret"
        endpoint = self._endpoint(
            "webhook",
            {
                "url": "https://hooks.example.invalid/notify",
                "signature_mode": "hmac-sha256",
                "signing_secret": signing_secret,
                "headers": {"X-Notification-Source": "ml-platform"},
            },
        )
        client = RecordingHttpClient(FakeResponse(201))
        router = NotificationChannelRouter(
            self.db,
            self.settings,
            http_client=client,
            resolve=public_resolution,
        )

        result = router.send(endpoint=endpoint, event=self.event, delivery_key="delivery-webhook")

        self.assertEqual(result.status, "sent")
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertFalse(call["follow_redirects"])
        self.assertLessEqual(len(call["content"]), 65536)
        self.assertNotIn(b"must-not-send", call["content"])
        expected = hmac.new(
            signing_secret.encode("utf-8"), call["content"], hashlib.sha256
        ).hexdigest()
        self.assertEqual(call["headers"]["X-ML-Platform-Signature"], f"sha256={expected}")

    def test_webhook_retries_transient_status_and_fails_permanent_status(self):
        endpoint = self._endpoint("webhook", {"url": "https://hooks.example.invalid/notify"})

        retry = NotificationChannelRouter(
            self.db,
            self.settings,
            http_client=RecordingHttpClient(FakeResponse(503)),
            resolve=public_resolution,
        ).send(endpoint=endpoint, event=self.event, delivery_key="delivery-retry")
        failed = NotificationChannelRouter(
            self.db,
            self.settings,
            http_client=RecordingHttpClient(FakeResponse(400)),
            resolve=public_resolution,
        ).send(endpoint=endpoint, event=self.event, delivery_key="delivery-failed")

        self.assertEqual((retry.status, retry.provider_status), ("retry", 503))
        self.assertEqual((failed.status, failed.provider_status), ("failed", 400))

    def test_webhook_cannot_override_protocol_headers(self):
        endpoint = self._endpoint(
            "webhook",
            {
                "url": "https://hooks.example.invalid/notify",
                "headers": {"Idempotency-Key": "attacker-controlled"},
            },
        )
        client = RecordingHttpClient(FakeResponse(201))
        result = NotificationChannelRouter(
            self.db,
            self.settings,
            http_client=client,
            resolve=public_resolution,
        ).send(endpoint=endpoint, event=self.event, delivery_key="delivery-header")

        self.assertEqual(
            (result.status, result.error_code),
            ("failed", "NOTIFICATION_ENDPOINT_FORBIDDEN"),
        )
        self.assertEqual(client.calls, [])

    def test_wecom_rejects_unofficial_host_before_sending(self):
        endpoint = self._endpoint(
            "wecom", {"url": "https://hooks.example.invalid/cgi-bin/webhook/send?key=robot-key"}
        )
        client = RecordingHttpClient(FakeResponse(200, {"errcode": 0}))
        result = NotificationChannelRouter(
            self.db,
            self.settings,
            http_client=client,
            resolve=public_resolution,
        ).send(endpoint=endpoint, event=self.event, delivery_key="delivery-wecom")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "NOTIFICATION_ENDPOINT_FORBIDDEN")
        self.assertEqual(client.calls, [])

    def test_email_uses_tls_and_enforces_recipient_cap(self):
        smtp = RecordingSMTP()
        router = NotificationChannelRouter(
            self.db,
            self.settings,
            smtp_factory=lambda _host, _port, timeout: smtp,
        )
        endpoint = self._endpoint(
            "email",
            {"to": ["ops@example.invalid"], "cc": ["copy@example.invalid"]},
        )

        result = router.send(endpoint=endpoint, event=self.event, delivery_key="delivery-email")

        self.assertEqual(result.status, "sent")
        self.assertTrue(smtp.started_tls)
        self.assertEqual(smtp.login_args, ("smtp-user-secret", "smtp-password-secret"))
        self.assertEqual(smtp.sent[1], ["ops@example.invalid", "copy@example.invalid"])
        self.assertIn("To: ops@example.invalid", smtp.sent[2])
        self.assertIn("Cc: copy@example.invalid", smtp.sent[2])

        too_many = self._endpoint(
            "email",
            {"to": [f"recipient-{index}@example.invalid" for index in range(51)]},
        )
        limited = router.send(endpoint=too_many, event=self.event, delivery_key="delivery-email-limit")
        self.assertEqual(
            (limited.status, limited.error_code),
            ("failed", "NOTIFICATION_EMAIL_RECIPIENT_LIMIT"),
        )

    def test_email_treats_empty_compose_credentials_as_unconfigured(self):
        smtp = RecordingSMTP()
        settings = Settings(
            _env_file=None,
            notification_master_key=MASTER_KEY,
            smtp_host="mailpit",
            smtp_port=1025,
            smtp_from="ml-platform-acceptance@localhost",
            smtp_username="",
            smtp_password="",
            smtp_use_tls=False,
        )
        router = NotificationChannelRouter(
            self.db,
            settings,
            smtp_factory=lambda _host, _port, timeout: smtp,
        )
        endpoint = self._endpoint("email", {"to": ["ops@example.invalid"], "cc": []})

        result = router.send(endpoint=endpoint, event=self.event, delivery_key="delivery-email-no-auth")

        self.assertEqual(result.status, "sent")
        self.assertIsNone(smtp.login_args)
        self.assertIsNotNone(smtp.sent)


if __name__ == "__main__":
    unittest.main()
