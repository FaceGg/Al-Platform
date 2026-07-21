import unittest
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.artifact import Artifact
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project
from app.models.user import User
from app.services.inference_rollout import InferenceRolloutError, InferenceRolloutService
from app.events.domain import (
    SAFE_PAYLOAD_KEYS,
    DomainEvent,
    NullDomainEventRecorder,
    create_domain_event,
)


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def preload(self, deployment_id, revision_id):
        self.calls.append(("preload", str(deployment_id), str(revision_id)))


class RecordingEventRecorder:
    def __init__(self):
        self.events = []

    def record(self, db, event):
        self.events.append(event)


class TestInferenceRollout(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.actor = User(username="rollout-owner", password_hash="hash")
        self.db.add(self.actor)
        self.db.flush()
        self.project = Project(name="Rollout", owner_id=self.actor.id)
        self.db.add(self.project)
        self.db.flush()
        artifact = Artifact(
            project_id=self.project.id,
            name="model.onnx",
            type="model",
            storage_path="",
            storage_uri="s3://models/rollout.onnx",
            file_size=1,
            format="onnx",
        )
        self.db.add(artifact)
        self.db.flush()
        registered = RegisteredModel(
            project_id=self.project.id,
            name="Rollout model",
            created_by_id=self.actor.id,
        )
        self.db.add(registered)
        self.db.flush()
        self.version = ModelVersion(
            registered_model_id=registered.id,
            version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=artifact.id,
            onnx_artifact_id=artifact.id,
            approval_status="approved",
            created_by_id=self.actor.id,
        )
        self.db.add(self.version)
        self.db.flush()
        self.deployment = InferenceDeployment(
            project_id=self.project.id,
            name="primary",
            model_version_id=self.version.id,
            created_by_id=self.actor.id,
        )
        self.db.add(self.deployment)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def make_revision(self):
        revision = DeploymentRevision(
            deployment_id=self.deployment.id,
            revision_number=1,
            strategy="canary",
            status="candidate",
            created_by_id=self.actor.id,
        )
        self.db.add(revision)
        self.db.flush()
        return revision

    def make_target(self, revision, weight_bps):
        return DeploymentTarget(
            revision_id=revision.id,
            model_version_id=self.version.id,
            weight_bps=weight_bps,
            role="candidate",
        )

    def test_target_weights_must_total_10000(self):
        revision = self.make_revision()
        self.db.add(self.make_target(revision, weight_bps=9999))
        self.db.commit()
        with self.assertRaisesRegex(InferenceRolloutError, "TARGET_WEIGHTS_INVALID"):
            InferenceRolloutService(FakeRuntime()).validate_targets(self.db, revision.id)

    def test_rollout_event_contains_only_safe_payload(self):
        revision = self.make_revision()
        self.db.add(self.make_target(revision, 10000))
        self.db.commit()
        recorder = RecordingEventRecorder()
        service = InferenceRolloutService(FakeRuntime(), event_recorder=recorder)
        service.record_rollout_completed(
            self.db,
            self.deployment.id,
            revision.id,
            self.actor.id,
        )
        event = recorder.events[-1]
        self.assertEqual(event.event_type, "rollout.completed")
        self.assertEqual(
            set(event.payload),
            {"revision_id", "deployment_id", "model_version_ids"},
        )

    def test_null_domain_event_recorder_does_not_commit(self):
        db = Mock()
        NullDomainEventRecorder().record(db, safe_event())
        db.commit.assert_not_called()

    def test_domain_event_filters_payload_to_safe_keys(self):
        event = create_domain_event(
            idempotency_key="rollout:1:completed:1",
            event_type="rollout.completed",
            severity="info",
            occurred_at=datetime.now(timezone.utc),
            project_id=uuid4(),
            actor_id=uuid4(),
            resource_type="deployment",
            resource_id="deployment-1",
            payload={"revision_id": "revision-1", "secret": "redacted"},
        )
        self.assertEqual(set(event.payload), {"revision_id"})
        self.assertTrue(set(event.payload) <= SAFE_PAYLOAD_KEYS)


def safe_event() -> DomainEvent:
    return DomainEvent(
        event_id=uuid4(),
        idempotency_key="rollout:1:completed:1",
        event_type="rollout.completed",
        severity="info",
        occurred_at=datetime.now(timezone.utc),
        project_id=None,
        actor_id=None,
        resource_type="deployment",
        resource_id=None,
        payload={},
    )


if __name__ == "__main__":
    unittest.main()
