"""Transactional notification outbox contracts for frozen domain events."""

import hashlib
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.model_registry import build_model_registry_router
from app.database import Base
from app.events.domain import DomainEvent
from app.models.artifact import Artifact
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
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
from app.services.notification_channels import DeliveryResult
from app.services.inference_rollout import InferenceRolloutService
from app.tasks.inference_tasks import build_inference_rollout_service

try:
    from app.services.notification_outbox import OutboxDomainEventRecorder
except ModuleNotFoundError:
    OutboxDomainEventRecorder = None

try:
    from app.tasks.notification_tasks import (
        _claim_delivery,
        _create_dead_letter_alert,
        _fan_out_deliveries,
        _lock_outbox_for_reconciliation,
        _record_result,
        claim_outbox,
        deliver_notifications_task,
        execute_notification_delivery,
        next_retry_at,
    )
except (ModuleNotFoundError, ImportError):
    _claim_delivery = None
    _create_dead_letter_alert = None
    _fan_out_deliveries = None
    _lock_outbox_for_reconciliation = None
    _record_result = None
    claim_outbox = None
    deliver_notifications_task = None
    execute_notification_delivery = None
    next_retry_at = None

try:
    from app.tasks.notification_tasks import (
        enqueue_due_notification_tasks,
        enqueue_due_notifications_task,
    )
except ImportError:
    enqueue_due_notification_tasks = None
    enqueue_due_notifications_task = None


class FakeRuntime:
    def preload(self, deployment_id, revision_id):
        return None


class RecordingNotificationAdapter:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def send(self, *, endpoint, event, delivery_key, recipient_user_ids=()):
        self.calls.append({
            "endpoint_id": endpoint.id,
            "event_id": event.event_id,
            "delivery_key": delivery_key,
            "recipient_user_ids": tuple(recipient_user_ids),
        })
        return self.results.pop(0) if self.results else DeliveryResult("sent")


class TestNotificationOutbox(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.user = User(username="outbox-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Outbox", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.commit()
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def recorder(self):
        self.assertIsNotNone(
            OutboxDomainEventRecorder,
            "OutboxDomainEventRecorder must be available",
        )
        return OutboxDomainEventRecorder()

    def domain_event(self, *, event_id=None, idempotency_key="rollout:1:completed:1"):
        return DomainEvent(
            event_id=event_id or uuid4(),
            idempotency_key=idempotency_key,
            event_type="rollout.completed",
            severity="info",
            occurred_at=datetime.now(timezone.utc),
            project_id=self.project.id,
            actor_id=self.user.id,
            resource_type="inference_deployment",
            resource_id="deployment-1",
            payload={
                "revision_id": "revision-1",
                "model_version_ids": ["version-1"],
                "storage_uri": "s3://must-not-reach-outbox",
            },
        )

    def create_outbox(self, *, event=None):
        event = event or self.domain_event()
        self.recorder().record(self.db, event)
        self.db.commit()
        return self.db.query(NotificationOutbox).filter(
            NotificationOutbox.event_id == event.event_id,
        ).one()

    def create_subscription(
        self,
        *,
        event_types=None,
        minimum_severity="info",
        recipient_roles=None,
        recipient_user_ids=None,
        enabled=True,
    ):
        endpoint = NotificationEndpoint(
            project_id=self.project.id,
            kind="in_app",
            name=f"outbox-endpoint-{uuid4()}",
            destination_hint="in-app",
            encrypted_config="not-used-by-recording-adapter",
            enabled=enabled,
            created_by_id=self.user.id,
        )
        self.db.add(endpoint)
        self.db.flush()
        subscription = NotificationSubscription(
            project_id=self.project.id,
            endpoint_id=endpoint.id,
            event_types=event_types or ["rollout.completed"],
            minimum_severity=minimum_severity,
            recipient_roles=recipient_roles or ["owner"],
            recipient_user_ids=recipient_user_ids or [],
            enabled=enabled,
            created_by_id=self.user.id,
        )
        self.db.add(subscription)
        self.db.commit()
        return endpoint, subscription

    def notification_task(self):
        self.assertIsNotNone(claim_outbox, "notification task module must be available")
        self.assertIsNotNone(
            execute_notification_delivery,
            "notification delivery executor must be available",
        )

    def execute(self, outbox_id, adapter, *, now, jitter=0.0):
        self.notification_task()
        return execute_notification_delivery(
            outbox_id,
            now=now,
            jitter=jitter,
            session_factory=self.session_factory,
            adapter_factory=lambda _db: adapter,
        )

    def test_recorder_writes_safe_outbox_row_that_outer_rollback_removes(self):
        event_record = self.domain_event()

        self.recorder().record(self.db, event_record)

        rows = self.db.query(NotificationOutbox).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].event_id, event_record.event_id)
        self.assertEqual(rows[0].idempotency_key, event_record.idempotency_key)
        self.assertEqual(
            rows[0].payload,
            {
                "revision_id": "revision-1",
                "model_version_ids": ["version-1"],
            },
        )
        self.db.rollback()
        self.assertEqual(self.db.query(NotificationOutbox).count(), 0)

    def test_recorder_only_adds_and_flushes_without_commit_or_dispatch(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.tasks.celery_app.celery_app.send_task") as send_task:
            self.recorder().record(db, self.domain_event())

        db.add.assert_called_once()
        db.flush.assert_called_once_with()
        db.commit.assert_not_called()
        db.begin_nested.assert_not_called()
        send_task.assert_not_called()

    def test_recorder_normalizes_legacy_error_severity_to_critical(self):
        event_record = DomainEvent(
            event_id=uuid4(),
            idempotency_key="rollout:1:failed:1",
            event_type="rollout.failed",
            severity="error",
            occurred_at=datetime.now(timezone.utc),
            project_id=self.project.id,
            actor_id=self.user.id,
            resource_type="inference_deployment",
            resource_id="deployment-1",
            payload={"error_code": "MODEL_LOAD_FAILED"},
        )

        self.recorder().record(self.db, event_record)

        self.assertEqual(
            self.db.query(NotificationOutbox).one().severity,
            "critical",
        )

    def test_duplicate_with_matching_event_and_idempotency_key_is_suppressed(self):
        event_record = self.domain_event()
        recorder = self.recorder()
        recorder.record(self.db, event_record)
        recorder.record(self.db, event_record)

        self.assertEqual(self.db.query(NotificationOutbox).count(), 1)

    def test_mismatched_unique_collisions_are_reraised(self):
        event_record = self.domain_event()
        recorder = self.recorder()
        recorder.record(self.db, event_record)
        self.db.commit()

        with self.assertRaises(IntegrityError):
            recorder.record(
                self.db,
                self.domain_event(
                    event_id=event_record.event_id,
                    idempotency_key="rollout:other:completed:1",
                ),
            )
        self.db.rollback()

        with self.assertRaises(IntegrityError):
            recorder.record(
                self.db,
                self.domain_event(
                    idempotency_key=event_record.idempotency_key,
                ),
            )
        self.db.rollback()

    def test_api_rollout_factory_uses_app_state_recorder(self):
        recorder = self.recorder()
        runtime = FakeRuntime()
        router = build_model_registry_router(
            deployment_service=SimpleNamespace(runtime=runtime),
        )
        release_route = next(
            route
            for route in router.routes
            if route.path == "/api/inference-deployments/{deployment_id}/rollouts"
            and "POST" in route.methods
        )
        rollout_service_for = inspect.getclosurevars(
            release_route.endpoint
        ).nonlocals["rollout_service_for"]
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(domain_event_recorder=recorder),
            ),
        )

        service = rollout_service_for(self.db, request)

        self.assertIs(service.runtime, runtime)
        self.assertIs(service.event_recorder, recorder)

    def test_task_rollout_factory_uses_concrete_outbox_recorder(self):
        recorder_type = type(self.recorder())
        runtime = FakeRuntime()
        with patch(
            "app.tasks.inference_tasks.build_inference_deployment_service",
            return_value=SimpleNamespace(runtime=runtime),
        ):
            service = build_inference_rollout_service()

        self.assertIs(service.runtime, runtime)
        self.assertIsInstance(service.event_recorder, recorder_type)

    def test_real_rollout_producer_writes_outbox_in_business_transaction(self):
        artifact = Artifact(
            project_id=self.project.id,
            name="stable.onnx",
            type="model",
            storage_path="",
            storage_uri="s3://models/stable.onnx",
            file_size=1,
            format="onnx",
        )
        self.db.add(artifact)
        self.db.flush()
        registered = RegisteredModel(
            project_id=self.project.id,
            name="Outbox model",
            created_by_id=self.user.id,
        )
        self.db.add(registered)
        self.db.flush()
        stable_version = ModelVersion(
            registered_model_id=registered.id,
            version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=artifact.id,
            onnx_artifact_id=artifact.id,
            approval_status="approved",
            created_by_id=self.user.id,
        )
        self.db.add(stable_version)
        self.db.flush()
        candidate_artifact = Artifact(
            project_id=self.project.id,
            name="candidate.onnx",
            type="model",
            storage_path="",
            storage_uri="s3://models/candidate.onnx",
            file_size=1,
            format="onnx",
        )
        self.db.add(candidate_artifact)
        self.db.flush()
        candidate_version = ModelVersion(
            registered_model_id=registered.id,
            version_number=2,
            source_kind="onnx_artifact",
            source_artifact_id=candidate_artifact.id,
            onnx_artifact_id=candidate_artifact.id,
            approval_status="approved",
            created_by_id=self.user.id,
        )
        self.db.add(candidate_version)
        self.db.flush()
        deployment = InferenceDeployment(
            project_id=self.project.id,
            name="outbox-deployment",
            model_version_id=stable_version.id,
            created_by_id=self.user.id,
        )
        self.db.add(deployment)
        self.db.flush()
        stable_revision = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=1,
            strategy="immediate",
            status="stable",
            created_by_id=self.user.id,
        )
        self.db.add(stable_revision)
        self.db.flush()
        self.db.add(DeploymentTarget(
            revision_id=stable_revision.id,
            model_version_id=stable_version.id,
            weight_bps=10000,
            role="stable",
        ))
        self.db.commit()

        service = InferenceRolloutService(
            FakeRuntime(),
            event_recorder=self.recorder(),
        )
        service.create_candidate(
            self.db,
            deployment.id,
            self.user.id,
            [{"model_version_id": str(candidate_version.id), "weight_bps": 10000}],
            commit=False,
        )

        row = self.db.query(NotificationOutbox).one()
        self.assertEqual(row.event_type, "rollout.started")
        self.assertEqual(row.project_id, self.project.id)
        self.assertEqual(row.status, "pending")
        self.db.rollback()
        self.assertEqual(self.db.query(NotificationOutbox).count(), 0)

    def test_claim_is_atomic_single_winner(self):
        self.assertIsNotNone(claim_outbox, "claim_outbox must be available")
        outbox = self.create_outbox()
        now = datetime(2026, 7, 27, 10, 0, 0)

        self.assertTrue(claim_outbox(self.db, outbox.id, now=now))
        self.assertFalse(claim_outbox(self.db, outbox.id, now=now))

        persisted = self.db.get(NotificationOutbox, outbox.id)
        self.assertEqual(persisted.status, "processing")
        self.assertEqual(persisted.claimed_at, now)

    def test_stale_processing_claim_can_be_recovered_after_hard_timeout(self):
        self.assertIsNotNone(claim_outbox, "claim_outbox must be available")
        outbox = self.create_outbox()
        claimed_at = datetime(2026, 7, 27, 10, 0, 0)

        with patch(
            "app.tasks.notification_tasks.settings.task_hard_timeout_seconds",
            2,
        ):
            self.assertTrue(claim_outbox(self.db, outbox.id, now=claimed_at))
            self.assertFalse(
                claim_outbox(
                    self.db,
                    outbox.id,
                    now=claimed_at + timedelta(seconds=2),
                )
            )
            self.assertTrue(
                claim_outbox(
                    self.db,
                    outbox.id,
                    now=claimed_at + timedelta(seconds=3),
                )
            )

    def test_stale_processing_delivery_is_reclaimed_after_outbox_recovery(self):
        endpoint, subscription = self.create_subscription()
        outbox = self.create_outbox()
        claimed_at = datetime(2026, 7, 27, 10, 0, 0)
        outbox.status = "processing"
        outbox.claimed_at = claimed_at
        delivery_key = hashlib.sha256(
            f"{outbox.event_id}:{subscription.id}:{endpoint.id}".encode("utf-8")
        ).hexdigest()
        self.db.add(NotificationDelivery(
            outbox_id=outbox.id,
            subscription_id=subscription.id,
            endpoint_id=endpoint.id,
            idempotency_key=delivery_key,
            status="processing",
            attempts=1,
            claimed_at=claimed_at,
            updated_at=claimed_at,
        ))
        self.db.commit()
        adapter = RecordingNotificationAdapter(DeliveryResult("sent"))

        with patch(
            "app.tasks.notification_tasks.settings.task_hard_timeout_seconds",
            2,
        ):
            result = self.execute(
                outbox.id,
                adapter,
                now=claimed_at + timedelta(seconds=3),
            )

        self.assertEqual(result, "sent")
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(self.db.query(NotificationDelivery).one().status, "sent")

    def test_stale_worker_cannot_finalize_delivery_reclaimed_by_newer_worker(self):
        self.assertIsNotNone(_claim_delivery, "_claim_delivery must be available")
        self.assertIsNotNone(_record_result, "_record_result must be available")
        endpoint, subscription = self.create_subscription()
        outbox = self.create_outbox()
        delivery = NotificationDelivery(
            outbox_id=outbox.id,
            subscription_id=subscription.id,
            endpoint_id=endpoint.id,
            idempotency_key="stale-worker-delivery",
            status="pending",
        )
        self.db.add(delivery)
        self.db.commit()
        first_claimed_at = datetime(2026, 7, 27, 10, 0, 0)
        reclaimed_at = first_claimed_at + timedelta(seconds=3)

        with patch(
            "app.tasks.notification_tasks.settings.task_hard_timeout_seconds",
            2,
        ):
            with self.session_factory() as first_worker:
                first_claim_token = _claim_delivery(
                    first_worker,
                    delivery.id,
                    now=first_claimed_at,
                )
            with self.session_factory() as second_worker:
                second_claim_token = _claim_delivery(
                    second_worker,
                    delivery.id,
                    now=reclaimed_at,
                )
            self.assertIsNotNone(first_claim_token)
            self.assertIsNotNone(second_claim_token)
            self.assertNotEqual(first_claim_token, second_claim_token)

            with self.session_factory() as second_worker:
                second_delivery = second_worker.get(NotificationDelivery, delivery.id)
                second_outbox = second_worker.get(NotificationOutbox, outbox.id)
                self.assertEqual(
                    _record_result(
                        second_worker,
                        second_delivery,
                        second_outbox,
                        DeliveryResult("sent"),
                        claim_token=second_claim_token,
                        now=reclaimed_at,
                        jitter=0.0,
                    ),
                    "sent",
                )

            with self.session_factory() as first_worker:
                late_delivery = first_worker.get(NotificationDelivery, delivery.id)
                late_outbox = first_worker.get(NotificationOutbox, outbox.id)
                self.assertEqual(
                    _record_result(
                        first_worker,
                        late_delivery,
                        late_outbox,
                        DeliveryResult("retry", "WEBHOOK_TIMEOUT"),
                        claim_token=first_claim_token,
                        now=reclaimed_at + timedelta(seconds=1),
                        jitter=0.0,
                    ),
                    "sent",
                )

        self.db.expire_all()
        persisted_delivery = self.db.get(NotificationDelivery, delivery.id)
        persisted_outbox = self.db.get(NotificationOutbox, outbox.id)
        self.assertEqual(persisted_delivery.status, "sent")
        self.assertIsNone(persisted_delivery.last_error_code)
        self.assertEqual(persisted_outbox.status, "sent")

    def test_reconciliation_locks_the_outbox_row_on_postgresql(self):
        self.assertIsNotNone(
            _lock_outbox_for_reconciliation,
            "outbox reconciliation lock must be available",
        )
        outbox = self.create_outbox()
        query = MagicMock()
        filtered = query.filter.return_value
        locked = filtered.with_for_update.return_value
        locked.one_or_none.return_value = outbox
        db = MagicMock()
        db.query.return_value = query

        with patch(
            "app.tasks.notification_tasks._dialect_name",
            return_value="postgresql",
        ):
            result = _lock_outbox_for_reconciliation(db, outbox.id)

        self.assertIs(result, outbox)
        filtered.with_for_update.assert_called_once_with()
        locked.one_or_none.assert_called_once_with()

    def test_mixed_sent_and_retry_results_keep_the_outbox_due(self):
        self.assertIsNotNone(_record_result, "notification result recorder must be available")
        endpoint, subscription = self.create_subscription()
        second_endpoint, second_subscription = self.create_subscription()
        outbox = self.create_outbox()
        sent_delivery = NotificationDelivery(
            outbox_id=outbox.id,
            subscription_id=subscription.id,
            endpoint_id=endpoint.id,
            idempotency_key="mixed-sent-delivery",
            status="processing",
            attempts=1,
            claim_token="sent-worker",
            claimed_at=datetime(2026, 7, 28, 10, 0, 0),
        )
        retry_delivery = NotificationDelivery(
            outbox_id=outbox.id,
            subscription_id=second_subscription.id,
            endpoint_id=second_endpoint.id,
            idempotency_key="mixed-retry-delivery",
            status="processing",
            attempts=1,
            claim_token="retry-worker",
            claimed_at=datetime(2026, 7, 28, 10, 0, 0),
        )
        self.db.add_all([sent_delivery, retry_delivery])
        self.db.commit()

        with self.session_factory() as retry_worker:
            self.assertEqual(
                _record_result(
                    retry_worker,
                    retry_worker.get(NotificationDelivery, retry_delivery.id),
                    retry_worker.get(NotificationOutbox, outbox.id),
                    DeliveryResult("retry", "WEBHOOK_TIMEOUT"),
                    claim_token="retry-worker",
                    now=datetime(2026, 7, 28, 10, 0, 1),
                    jitter=0.0,
                ),
                "pending",
            )
        with self.session_factory() as sent_worker:
            self.assertEqual(
                _record_result(
                    sent_worker,
                    sent_worker.get(NotificationDelivery, sent_delivery.id),
                    sent_worker.get(NotificationOutbox, outbox.id),
                    DeliveryResult("sent"),
                    claim_token="sent-worker",
                    now=datetime(2026, 7, 28, 10, 0, 2),
                    jitter=0.0,
                ),
                "pending",
            )

        self.db.expire_all()
        persisted = self.db.get(NotificationOutbox, outbox.id)
        self.assertEqual(persisted.status, "pending")
        self.assertEqual(persisted.next_attempt_at, datetime(2026, 7, 28, 10, 0, 2))
        self.assertEqual(persisted.last_error_code, "WEBHOOK_TIMEOUT")

    def test_dead_letter_alert_ignores_existing_deduplication_key_conflict(self):
        self.assertIsNotNone(
            _create_dead_letter_alert,
            "_create_dead_letter_alert must be available",
        )
        endpoint, subscription = self.create_subscription()
        outbox = self.create_outbox()
        delivery = NotificationDelivery(
            outbox_id=outbox.id,
            subscription_id=subscription.id,
            endpoint_id=endpoint.id,
            idempotency_key="dead-letter-deduplication-conflict",
            status="dead_letter",
            attempts=1,
            last_error_code="WEBHOOK_TIMEOUT",
        )
        self.db.add(delivery)
        self.db.flush()
        deduplication_key = f"notification.dead_letter:{outbox.event_id}"
        self.db.add(InAppNotification(
            recipient_user_id=self.user.id,
            project_id=self.project.id,
            event_id=uuid4(),
            event_type="unrelated.notification",
            severity="info",
            title="Existing notification",
            body="Existing notification body.",
            payload={},
            deduplication_key=deduplication_key,
        ))
        self.db.commit()

        _create_dead_letter_alert(self.db, outbox, delivery)
        self.db.commit()

        alerts = self.db.query(InAppNotification).filter(
            InAppNotification.deduplication_key == deduplication_key,
        ).all()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(self.db.query(InAppNotification).count(), 1)

    def test_repeated_delivery_creates_and_sends_one_logical_delivery(self):
        self.create_subscription()
        outbox = self.create_outbox()
        adapter = RecordingNotificationAdapter(DeliveryResult("sent"))
        now = datetime(2026, 7, 27, 10, 0, 0)

        self.assertEqual(self.execute(outbox.id, adapter, now=now), "sent")
        self.assertEqual(self.execute(outbox.id, adapter, now=now), "sent")

        self.assertEqual(self.db.query(NotificationDelivery).count(), 1)
        self.assertEqual(len(adapter.calls), 1)
        self.db.refresh(outbox)
        self.assertEqual(
            outbox.status,
            "sent",
        )

    def test_fanout_resolves_owner_first_and_only_project_member_recipients(self):
        operator = User(username="outbox-operator", password_hash="hash")
        outsider = User(username="outbox-outsider", password_hash="hash")
        self.db.add_all([operator, outsider])
        self.db.flush()
        self.db.add(ProjectMember(
            project_id=self.project.id,
            user_id=operator.id,
            role="operator",
            created_by=self.user.id,
        ))
        self.db.commit()
        self.create_subscription(
            recipient_roles=["operator", "owner"],
            recipient_user_ids=[str(operator.id), str(outsider.id)],
        )
        self.create_subscription(event_types=["rollout.failed"])
        self.create_subscription(minimum_severity="warning")
        outbox = self.create_outbox()
        adapter = RecordingNotificationAdapter(DeliveryResult("sent"))

        self.assertEqual(
            self.execute(
                outbox.id,
                adapter,
                now=datetime(2026, 7, 27, 10, 0, 0),
            ),
            "sent",
        )

        self.assertEqual(self.db.query(NotificationDelivery).count(), 1)
        self.assertEqual(
            adapter.calls[0]["recipient_user_ids"],
            (self.user.id, operator.id),
        )

    def test_each_delivery_uses_fresh_clock_times_for_claim_and_retry(self):
        self.notification_task()
        self.create_subscription()
        self.create_subscription()
        outbox = self.create_outbox()
        base_time = datetime(2026, 7, 28, 9, 0, 0)
        clock_calls = []

        def clock():
            value = base_time + timedelta(seconds=len(clock_calls) * 10)
            clock_calls.append(value)
            return value

        adapter = RecordingNotificationAdapter(
            DeliveryResult("retry", "WEBHOOK_TIMEOUT"),
            DeliveryResult("retry", "WEBHOOK_TIMEOUT"),
        )

        result = execute_notification_delivery(
            outbox.id,
            clock=clock,
            session_factory=self.session_factory,
            adapter_factory=lambda _db: adapter,
        )

        self.assertEqual(result, "retry")
        retry_times = sorted(
            row.next_attempt_at
            for row in self.db.query(NotificationDelivery).all()
        )
        self.assertEqual(len(retry_times), 2)
        self.assertLess(retry_times[0], retry_times[1])
        self.assertGreaterEqual(len(clock_calls), 6)

    def test_concurrent_fanout_uses_atomic_delivery_insert(self):
        self.assertIsNotNone(_fan_out_deliveries, "fan-out helper must be available")
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "fanout-race.db"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                connect_args={"check_same_thread": False, "timeout": 5},
            )

            @event.listens_for(engine, "connect")
            def enable_foreign_keys(connection, _record):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

            Base.metadata.create_all(engine)
            session_factory = sessionmaker(bind=engine, expire_on_commit=False)
            try:
                with session_factory() as setup_db:
                    owner = User(username="fanout-race-owner", password_hash="hash")
                    setup_db.add(owner)
                    setup_db.flush()
                    project = Project(name="Fanout race", owner_id=owner.id)
                    setup_db.add(project)
                    setup_db.flush()
                    endpoint = NotificationEndpoint(
                        project_id=project.id,
                        kind="in_app",
                        name="fanout-race-endpoint",
                        destination_hint="in-app",
                        encrypted_config="unused",
                        created_by_id=owner.id,
                    )
                    setup_db.add(endpoint)
                    setup_db.flush()
                    subscription = NotificationSubscription(
                        project_id=project.id,
                        endpoint_id=endpoint.id,
                        event_types=["rollout.completed"],
                        minimum_severity="info",
                        recipient_roles=["owner"],
                        recipient_user_ids=[],
                        created_by_id=owner.id,
                    )
                    outbox = NotificationOutbox(
                        event_id=uuid4(),
                        idempotency_key="fanout-race-event",
                        event_type="rollout.completed",
                        severity="info",
                        occurred_at=datetime(2026, 7, 28, 9, 0, 0),
                        project_id=project.id,
                        actor_id=owner.id,
                        resource_type="deployment",
                        resource_id="fanout-race",
                        payload={},
                        status="processing",
                    )
                    setup_db.add_all([subscription, outbox])
                    setup_db.commit()
                    outbox_id = outbox.id

                insert_barrier = threading.Barrier(2, timeout=10)
                seen_fanout_inserts = 0
                listener_lock = threading.Lock()

                @event.listens_for(engine, "before_cursor_execute")
                def synchronize_delivery_insert(
                    _connection,
                    _cursor,
                    statement,
                    _parameters,
                    _context,
                    _executemany,
                ):
                    nonlocal seen_fanout_inserts
                    normalized = " ".join(statement.lower().split())
                    if not normalized.startswith("insert into notification_deliveries"):
                        return
                    with listener_lock:
                        seen_fanout_inserts += 1
                        should_wait = seen_fanout_inserts <= 2
                    if should_wait:
                        insert_barrier.wait()

                worker_errors = []
                worker_ids = []
                worker_lock = threading.Lock()

                def fan_out():
                    try:
                        with session_factory() as worker_db:
                            worker_outbox = worker_db.get(NotificationOutbox, outbox_id)
                            ids = _fan_out_deliveries(worker_db, worker_outbox)
                            worker_db.commit()
                        with worker_lock:
                            worker_ids.append(ids)
                    except BaseException as error:  # Assert worker failures below.
                        with worker_lock:
                            worker_errors.append(error)

                workers = [threading.Thread(target=fan_out) for _ in range(2)]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=15)

                self.assertFalse(any(worker.is_alive() for worker in workers))
                self.assertEqual(worker_errors, [])
                self.assertEqual(len(worker_ids), 2)
                self.assertEqual(seen_fanout_inserts, 2)
                with session_factory() as verify_db:
                    self.assertEqual(
                        verify_db.query(NotificationDelivery).filter(
                            NotificationDelivery.outbox_id == outbox_id,
                        ).count(),
                        1,
                    )
            finally:
                engine.dispose()

    def test_retry_schedule_is_monotonic_and_has_bounded_jitter(self):
        self.assertIsNotNone(next_retry_at, "next_retry_at must be available")
        self.create_subscription()
        outbox = self.create_outbox()
        adapter = RecordingNotificationAdapter(
            DeliveryResult("retry", "WEBHOOK_TIMEOUT"),
            DeliveryResult("retry", "WEBHOOK_TIMEOUT"),
        )
        first_now = datetime(2026, 7, 27, 10, 0, 0)

        self.assertEqual(
            self.execute(outbox.id, adapter, now=first_now, jitter=999),
            "retry",
        )
        delivery = self.db.query(NotificationDelivery).one()
        first_retry_at = delivery.next_attempt_at
        self.assertEqual(first_retry_at - first_now, timedelta(seconds=1.25))

        self.assertEqual(
            self.execute(outbox.id, adapter, now=first_retry_at, jitter=999),
            "retry",
        )
        self.db.refresh(delivery)
        self.assertEqual(delivery.next_attempt_at - first_retry_at, timedelta(seconds=2.5))
        self.assertGreater(delivery.next_attempt_at, first_retry_at)
        self.assertEqual(
            next_retry_at(100, first_now, 999) - first_now,
            timedelta(seconds=375),
        )

    def test_permanent_credential_failure_is_not_retried(self):
        self.create_subscription()
        outbox = self.create_outbox()
        adapter = RecordingNotificationAdapter(
            DeliveryResult("retry", "NOTIFICATION_CREDENTIAL_INVALID"),
        )

        self.assertEqual(
            self.execute(
                outbox.id,
                adapter,
                now=datetime(2026, 7, 27, 10, 0, 0),
            ),
            "failed",
        )

        delivery = self.db.query(NotificationDelivery).one()
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNone(delivery.next_attempt_at)
        self.assertEqual(delivery.last_error_code, "NOTIFICATION_CREDENTIAL_INVALID")

    def test_retry_exhaustion_creates_exactly_one_operator_dead_letter_alert(self):
        self.notification_task()
        operator = User(username="dead-letter-operator", password_hash="hash")
        self.db.add(operator)
        self.db.flush()
        self.db.add(ProjectMember(
            project_id=self.project.id,
            user_id=operator.id,
            role="operator",
            created_by=self.user.id,
        ))
        self.db.commit()
        self.create_subscription()
        outbox = self.create_outbox()
        adapter = RecordingNotificationAdapter(
            DeliveryResult("retry", "WEBHOOK_TIMEOUT"),
            DeliveryResult("retry", "WEBHOOK_TIMEOUT"),
        )
        first_now = datetime(2026, 7, 27, 10, 0, 0)

        with patch(
            "app.tasks.notification_tasks.settings.notification_delivery_max_attempts",
            2,
        ):
            self.assertEqual(self.execute(outbox.id, adapter, now=first_now), "retry")
            delivery = self.db.query(NotificationDelivery).one()
            self.assertEqual(
                self.execute(
                    outbox.id,
                    adapter,
                    now=delivery.next_attempt_at,
                ),
                "dead_letter",
            )
            self.assertEqual(
                self.execute(
                    outbox.id,
                    adapter,
                    now=delivery.next_attempt_at,
                ),
                "dead_letter",
            )

        self.db.refresh(delivery)
        self.assertEqual(delivery.status, "dead_letter")
        alerts = self.db.query(InAppNotification).filter(
            InAppNotification.event_id == outbox.event_id,
            InAppNotification.event_type == "notification.dead_letter",
        ).all()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].recipient_user_id, operator.id)

    def test_stale_delivery_result_cannot_overwrite_newer_lease(self):
        self.create_subscription()
        outbox = self.create_outbox()
        claimed_at = datetime(2026, 7, 27, 10, 0, 0)
        recovered_adapter = RecordingNotificationAdapter(DeliveryResult("sent"))
        test_case = self

        class StaleAdapter:
            def __init__(self):
                self.reclaimed = False

            def send(self, *, endpoint, event, delivery_key, recipient_user_ids=()):
                del endpoint, event, delivery_key, recipient_user_ids
                if not self.reclaimed:
                    self.reclaimed = True
                    result = test_case.execute(
                        outbox.id,
                        recovered_adapter,
                        now=claimed_at + timedelta(seconds=3),
                    )
                    test_case.assertEqual(result, "sent")
                return DeliveryResult("retry", "WEBHOOK_TIMEOUT")

        with patch(
            "app.tasks.notification_tasks.settings.task_hard_timeout_seconds",
            2,
        ):
            result = self.execute(outbox.id, StaleAdapter(), now=claimed_at)

        self.assertEqual(result, "sent")
        delivery = self.db.query(NotificationDelivery).one()
        self.assertEqual(delivery.status, "sent")
        self.assertEqual(delivery.attempts, 2)
        self.assertEqual(len(recovered_adapter.calls), 1)

    def test_dead_letter_alert_has_a_database_deduplication_key(self):
        if not hasattr(InAppNotification, "deduplication_key"):
            self.fail("dead-letter alerts need a durable idempotency identity")
        unique_constraints = [
            constraint
            for constraint in InAppNotification.__table__.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        ]
        self.assertIn(
            ("deduplication_key",),
            [tuple(constraint.columns.keys()) for constraint in unique_constraints],
        )
        first = InAppNotification(
            recipient_user_id=self.user.id,
            project_id=self.project.id,
            event_id=uuid4(),
            event_type="notification.dead_letter",
            severity="critical",
            title="first",
            body="first",
            deduplication_key="dead-letter-alert",
        )
        second = InAppNotification(
            recipient_user_id=self.user.id,
            project_id=self.project.id,
            event_id=uuid4(),
            event_type="notification.dead_letter",
            severity="critical",
            title="second",
            body="second",
            deduplication_key="dead-letter-alert",
        )
        self.db.add_all([first, second])
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_notification_delivery_task_has_stable_celery_registration(self):
        self.assertIsNotNone(
            deliver_notifications_task,
            "deliver_notifications_task must be available",
        )
        from app.tasks.celery_app import celery_app

        self.assertIn("ml_platform.deliver_notifications", celery_app.tasks)
        with patch(
            "app.tasks.notification_tasks.execute_notification_delivery",
            return_value="sent",
        ) as execute:
            result = deliver_notifications_task.run("outbox-1")

        self.assertEqual(result, "sent")
        execute.assert_called_once_with("outbox-1")

    def test_due_outbox_dispatcher_enqueues_without_claiming(self):
        self.assertIsNotNone(
            enqueue_due_notification_tasks,
            "enqueue_due_notification_tasks must be available",
        )
        self.assertIsNotNone(
            enqueue_due_notifications_task,
            "enqueue_due_notifications_task must be available",
        )
        outbox = self.create_outbox()
        now = datetime(2026, 7, 27, 10, 0, 0)

        with patch(
            "app.tasks.notification_tasks.celery_app.send_task",
        ) as send_task:
            queued = enqueue_due_notification_tasks(
                now=now,
                session_factory=self.session_factory,
            )

        self.assertEqual(queued, 1)
        send_task.assert_called_once_with(
            "ml_platform.deliver_notifications",
            args=[str(outbox.id)],
        )
        self.db.refresh(outbox)
        self.assertEqual(outbox.status, "pending")
        from app.tasks.celery_app import celery_app

        self.assertIn("ml_platform.enqueue_due_notifications", celery_app.tasks)
        self.assertIn("notification-outbox-dispatch", celery_app.conf.beat_schedule)


if __name__ == "__main__":
    unittest.main()
