"""Platform security audit contracts."""

import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import pwd_context
from app.database import Base, get_db
from app.main import app
from app.models.user import User

try:
    from app.models.platform_audit import PlatformAuditEvent
except ModuleNotFoundError:
    PlatformAuditEvent = None


class TestPlatformAuditModelContract(unittest.TestCase):
    def test_platform_audit_model_is_available(self):
        self.assertIsNotNone(PlatformAuditEvent)


@unittest.skipIf(PlatformAuditEvent is None, "platform audit model is not implemented")
class TestPlatformAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with cls.engine.connect() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)

        with cls.Session() as db:
            admin = User(
                username="audit-admin",
                password_hash=pwd_context.hash("safe-password"),
                role="admin",
            )
            target = User(
                username="audit-target",
                password_hash=pwd_context.hash("safe-password"),
                role="engineer",
            )
            user = User(
                username="audit-user",
                password_hash=pwd_context.hash("safe-password"),
                role="engineer",
            )
            db.add_all([admin, target, user])
            db.commit()
            cls.admin_id = str(admin.id)
            cls.target_id = str(target.id)

        def override_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        cls.client = TestClient(app)
        cls.admin_headers = cls._login("audit-admin")
        cls.user_headers = cls._login("audit-user")

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_db, None)
        cls.client.close()
        cls.engine.dispose()

    @classmethod
    def _login(cls, username):
        response = cls.client.post(
            "/api/auth/login",
            data={"username": username, "password": "safe-password"},
        )
        if response.status_code != 200:
            raise AssertionError(response.text)
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    def test_registration_writes_a_redacted_platform_event(self):
        response = self.client.post(
            "/api/auth/register",
            json={"username": "audited-registration", "password": "safe-password"},
        )
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as db:
            event = db.query(PlatformAuditEvent).filter(
                PlatformAuditEvent.action == "auth.register"
            ).one()
            self.assertEqual(event.result, "success")
            self.assertEqual(event.actor_username, "audited-registration")
            self.assertEqual(event.changes, {"username": "audited-registration"})

    def test_failed_login_writes_a_redacted_platform_event(self):
        response = self.client.post(
            "/api/auth/login",
            data={"username": "audit-user", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 401, response.text)

        with self.Session() as db:
            event = db.query(PlatformAuditEvent).filter(
                PlatformAuditEvent.action == "auth.login.failed"
            ).order_by(PlatformAuditEvent.created_at.desc()).first()
            self.assertIsNotNone(event)
            self.assertEqual(event.result, "failed")
            self.assertEqual(event.actor_username, "anonymous")
            self.assertEqual(event.changes, {"username": "audit-user"})
            self.assertNotIn("wrong-password", str(event.changes))

    def test_duplicate_registration_writes_a_redacted_failed_event(self):
        response = self.client.post(
            "/api/auth/register",
            json={"username": "audit-user", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 400, response.text)

        with self.Session() as db:
            event = db.query(PlatformAuditEvent).filter(
                PlatformAuditEvent.action == "auth.register.failed",
                PlatformAuditEvent.error_code == "USERNAME_EXISTS",
            ).one_or_none()
            self.assertIsNotNone(event)
            if event is not None:
                self.assertEqual(event.result, "failed")
                self.assertEqual(event.changes, {"username": "audit-user"})
                self.assertNotIn("wrong-password", str(event.changes))

    def test_admin_role_change_writes_a_platform_event(self):
        response = self.client.put(
            f"/api/admin/users/{self.target_id}/role",
            params={"role": "operator"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as db:
            event = db.query(PlatformAuditEvent).filter(
                PlatformAuditEvent.action == "platform.user.role_change",
                PlatformAuditEvent.resource_id == self.target_id,
                PlatformAuditEvent.result == "success",
            ).one()
            self.assertEqual(event.result, "success")
            self.assertEqual(event.changes, {
                "previous_role": "engineer",
                "role": "operator",
            })

    def test_role_changes_reject_invalid_values_and_self_demotion(self):
        invalid = self.client.put(
            f"/api/admin/users/{self.target_id}/role",
            params={"role": "superuser"},
            headers=self.admin_headers,
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)

        self_demotion = self.client.put(
            f"/api/admin/users/{self.admin_id}/role",
            params={"role": "engineer"},
            headers=self.admin_headers,
        )
        self.assertEqual(self_demotion.status_code, 400, self_demotion.text)

        with self.Session() as db:
            invalid_event = db.query(PlatformAuditEvent).filter(
                PlatformAuditEvent.action == "platform.user.role_change",
                PlatformAuditEvent.error_code == "INVALID_PLATFORM_ROLE",
            ).one_or_none()
            self.assertIsNotNone(invalid_event)
            if invalid_event is not None:
                self.assertEqual(invalid_event.result, "failed")

            self_event = db.query(PlatformAuditEvent).filter(
                PlatformAuditEvent.action == "platform.user.role_change",
                PlatformAuditEvent.error_code == "SELF_ROLE_CHANGE_FORBIDDEN",
            ).one_or_none()
            self.assertIsNotNone(self_event)
            if self_event is not None:
                self.assertEqual(self_event.result, "failed")

    def test_self_delete_writes_a_failed_event(self):
        response = self.client.delete(
            f"/api/admin/users/{self.admin_id}",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 400, response.text)

        with self.Session() as db:
            event = db.query(PlatformAuditEvent).filter(
                PlatformAuditEvent.action == "platform.user.delete",
                PlatformAuditEvent.error_code == "SELF_DELETE_FORBIDDEN",
            ).one_or_none()
            self.assertIsNotNone(event)
            if event is not None:
                self.assertEqual(event.result, "failed")

    def test_non_admin_cannot_change_platform_roles(self):
        response = self.client.put(
            f"/api/admin/users/{self.target_id}/role",
            params={"role": "viewer"},
            headers=self.user_headers,
        )
        self.assertEqual(response.status_code, 403, response.text)

    def test_actor_snapshot_survives_actor_delete(self):
        with self.Session() as db:
            actor = User(
                username="audit-deleted-actor",
                password_hash=pwd_context.hash("safe-password"),
                role="engineer",
            )
            db.add(actor)
            db.flush()
            event = PlatformAuditEvent(
                actor_id=actor.id,
                actor_username=actor.username,
                action="platform.user.role_change",
                resource_type="user",
                resource_id=str(actor.id),
                result="success",
                request_id=uuid.uuid4(),
                changes={"role": "operator"},
            )
            db.add(event)
            db.commit()
            event_id = event.id

            db.delete(actor)
            db.commit()

            db.expire_all()
            stored = db.get(PlatformAuditEvent, event_id)
            self.assertIsNotNone(stored)
            self.assertIsNone(stored.actor_id)
            self.assertEqual(stored.actor_username, "audit-deleted-actor")

    def test_security_audit_is_admin_only_and_filters_rows(self):
        with self.Session() as db:
            event = PlatformAuditEvent(
                actor_id=None,
                actor_username="anonymous",
                action="auth.login.failed",
                resource_type="user",
                result="failed",
                request_id=uuid.uuid4(),
                changes={"username": "filtered-user"},
                error_code="INVALID_CREDENTIALS",
            )
            db.add(event)
            db.commit()
            event_id = str(event.id)

        denied = self.client.get(
            "/api/admin/security-audit",
            headers=self.user_headers,
        )
        self.assertEqual(denied.status_code, 403, denied.text)

        allowed = self.client.get(
            "/api/admin/security-audit",
            params={
                "action": "auth.login.failed",
                "resource_type": "user",
                "result": "failed",
                "limit": 10,
            },
            headers=self.admin_headers,
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)
        payload = allowed.json()
        self.assertGreaterEqual(payload["total"], 1)
        self.assertEqual(payload["offset"], 0)
        self.assertEqual(payload["limit"], 10)
        self.assertIn(event_id, {item["id"] for item in payload["items"]})


if __name__ == "__main__":
    unittest.main()
