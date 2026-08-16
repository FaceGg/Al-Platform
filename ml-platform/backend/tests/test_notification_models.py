"""Notification persistence and configuration contracts."""

import base64
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import Settings, settings
from app.database import Base
from app.models.project import Project
from app.models.user import User

try:
    from app.models.notifications import (
        InAppNotification,
        NotificationDelivery,
        NotificationEndpoint,
        NotificationOutbox,
        NotificationSubscription,
    )
except ModuleNotFoundError:
    InAppNotification = None
    NotificationDelivery = None
    NotificationEndpoint = None
    NotificationOutbox = None
    NotificationSubscription = None


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
WEEK10_REVISION = "20260720_10_security_notifications"
WEEK9_REVISION = "20260720_09_production_inference"
WEEK10_TABLES = {
    "platform_audit_events",
    "notification_endpoints",
    "notification_subscriptions",
    "notification_outbox",
    "notification_deliveries",
    "in_app_notifications",
}
NOTIFICATION_MASTER_KEY = base64.urlsafe_b64encode(b"n" * 32).decode("ascii")


def production_values(**overrides):
    values = {
        "app_mode": "production",
        "database_url": "postgresql+psycopg://app:db-password@db/ml_platform",
        "secret_key": "j" * 32,
        "task_backend": "celery",
        "celery_broker_url": "redis://:broker-password@redis:6379/0",
        "redis_events_url": "redis://:events-password@redis:6379/1",
        "artifact_storage_backend": "minio",
        "minio_endpoint": "minio:9000",
        "minio_access_key": "minio-access-value",
        "minio_secret_key": "minio-secret-value",
        "mlflow_tracking_uri": "http://mlflow:5000",
        "mlflow_backend_store_uri": "postgresql+psycopg://mlflow:pass@db/mlflow",
        "mlflow_artifact_root": "s3://ml-platform/mlflow",
        "tensorboard_gateway_url": "http://tensorboard-gateway:6006",
        "tensorboard_session_secret": "tensorboard-session-secret-value-1234",
        "inference_runtime_url": "http://inference-runtime:7000",
        "inference_internal_secret": "inference-internal-secret-value-1234",
    }
    values.update(overrides)
    return values


class TestNotificationSettings(unittest.TestCase):
    def test_production_requires_valid_notification_master_key(self):
        with self.assertRaises(ValidationError):
            Settings(**production_values())

        configured = Settings(
            **production_values(notification_master_key=NOTIFICATION_MASTER_KEY)
        )
        self.assertEqual(
            configured.resolved_notification_master_key.get_secret_value(),
            NOTIFICATION_MASTER_KEY,
        )
        self.assertNotIn(NOTIFICATION_MASTER_KEY, repr(configured))
        self.assertNotIn(NOTIFICATION_MASTER_KEY, repr(configured.safe_summary()))


class TestNotificationModels(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.user = User(username="notification-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Notifications", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_notification_models_are_available(self):
        self.assertIsNotNone(NotificationEndpoint)
        self.assertIsNotNone(NotificationSubscription)
        self.assertIsNotNone(NotificationOutbox)
        self.assertIsNotNone(NotificationDelivery)
        self.assertIsNotNone(InAppNotification)

    @unittest.skipIf(NotificationEndpoint is None, "notification models are unavailable")
    def test_endpoint_kind_and_project_name_are_constrained(self):
        endpoint = NotificationEndpoint(
            project_id=self.project.id,
            kind="in_app",
            name="console",
            destination_hint="project users",
            encrypted_config="ciphertext",
            created_by_id=self.user.id,
        )
        self.db.add(endpoint)
        self.db.commit()

        self.db.add(NotificationEndpoint(
            project_id=self.project.id,
            kind="sms",
            name="invalid",
            destination_hint="none",
            encrypted_config="ciphertext",
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        self.db.add(NotificationEndpoint(
            project_id=self.project.id,
            kind="email",
            name="console",
            destination_hint="operator@example.invalid",
            encrypted_config="ciphertext",
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()

    @unittest.skipIf(NotificationOutbox is None, "notification models are unavailable")
    def test_outbox_event_and_idempotency_keys_are_unique(self):
        event_id = __import__("uuid").uuid4()
        self.db.add(NotificationOutbox(
            event_id=event_id,
            idempotency_key="rollout-1-completed",
            event_type="rollout.completed",
            severity="info",
            occurred_at=__import__("datetime").datetime.now(),
            project_id=self.project.id,
            resource_type="deployment",
            resource_id="deployment-1",
            payload={"state": "completed"},
            status="pending",
        ))
        self.db.commit()

        self.db.add(NotificationOutbox(
            event_id=event_id,
            idempotency_key="rollout-2-completed",
            event_type="rollout.completed",
            severity="info",
            occurred_at=__import__("datetime").datetime.now(),
            project_id=self.project.id,
            resource_type="deployment",
            resource_id="deployment-2",
            payload={},
            status="pending",
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    @unittest.skipIf(InAppNotification is None, "notification models are unavailable")
    def test_in_app_notification_has_only_safe_delivery_columns(self):
        columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("in_app_notifications")
        }
        self.assertEqual(columns, {
            "id",
            "recipient_user_id",
            "project_id",
            "event_id",
            "event_type",
            "deduplication_key",
            "severity",
            "title",
            "body",
            "payload",
            "read_at",
            "archived_at",
            "created_at",
        })

    @unittest.skipIf(InAppNotification is None, "notification models are unavailable")
    def test_in_app_notification_deduplication_key_is_optional_and_unique(self):
        deduplication_key = "notification.dead_letter:event-1"
        self.db.add(InAppNotification(
            recipient_user_id=self.user.id,
            project_id=self.project.id,
            event_id=uuid4(),
            event_type="notification.dead_letter",
            deduplication_key=deduplication_key,
            severity="critical",
            title="Delivery failed",
            body="A delivery reached its retry limit.",
            payload={},
        ))
        self.db.commit()

        self.db.add(InAppNotification(
            recipient_user_id=self.user.id,
            project_id=self.project.id,
            event_id=uuid4(),
            event_type="notification.dead_letter",
            deduplication_key=deduplication_key,
            severity="critical",
            title="Duplicate delivery failed",
            body="This duplicate must not persist.",
            payload={},
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        self.db.add(InAppNotification(
            recipient_user_id=self.user.id,
            project_id=self.project.id,
            event_id=uuid4(),
            event_type="rollout.completed",
            deduplication_key=None,
            severity="info",
            title="Normal notification",
            body="Normal notifications remain repeatable.",
            payload={},
        ))
        self.db.commit()

    @unittest.skipIf(NotificationDelivery is None, "notification models are unavailable")
    def test_delivery_claim_lease_columns_are_present(self):
        columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("notification_deliveries")
        }
        self.assertTrue({"claim_token", "claimed_at"}.issubset(columns))


class TestNotificationMigration(unittest.TestCase):
    def test_revision_is_linear_and_reverses_only_week10_objects(self):
        revision_path = (
            BACKEND_ROOT
            / "alembic"
            / "versions"
            / "20260720_10_security_notifications.py"
        )
        self.assertTrue(revision_path.is_file())
        source = revision_path.read_text(encoding="utf-8")
        self.assertIn(f'revision = "{WEEK10_REVISION}"', source)
        self.assertIn(f'down_revision = "{WEEK9_REVISION}"', source)
        self.assertNotIn("create_all", source)
        self.assertNotIn("drop_all", source)

        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory, 'notifications.db').as_posix()}"
            config = Config(str(ALEMBIC_INI))
            original_database_url = settings.database_url
            settings.database_url = database_url
            try:
                command.upgrade(config, WEEK9_REVISION)
                command.upgrade(config, "head")
                command.check(config)
                db_engine = create_engine(database_url)
                try:
                    inspector = inspect(db_engine)
                    self.assertTrue(WEEK10_TABLES.issubset(inspector.get_table_names()))
                    delivery_columns = {
                        column["name"]
                        for column in inspector.get_columns("notification_deliveries")
                    }
                    self.assertTrue(
                        {"claim_token", "claimed_at"}.issubset(delivery_columns)
                    )
                    in_app_constraints = {
                        tuple(constraint["column_names"])
                        for constraint in inspector.get_unique_constraints(
                            "in_app_notifications"
                        )
                    }
                    self.assertIn(("deduplication_key",), in_app_constraints)
                finally:
                    db_engine.dispose()
                command.downgrade(config, WEEK9_REVISION)
            finally:
                settings.database_url = original_database_url

            db_engine = create_engine(database_url)
            try:
                tables = set(inspect(db_engine).get_table_names())
                self.assertTrue(WEEK10_TABLES.isdisjoint(tables))
            finally:
                db_engine.dispose()


if __name__ == "__main__":
    unittest.main()
