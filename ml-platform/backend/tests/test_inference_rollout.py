import json
import math
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
from fastapi import FastAPI

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.artifact import Artifact
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentRollout,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project
from app.models.user import User
from app.services.inference_rollout import (
    InferenceRolloutError,
    InferenceRolloutService,
    WeightedTargetRouter,
)
from app.services.inference_deployment import InferenceDeploymentService
from app.services.inference_runtime_client import InferenceRuntimeClientError
from app.events.domain import (
    SAFE_PAYLOAD_KEYS,
    DomainEvent,
    NullDomainEventRecorder,
    create_domain_event,
    to_storage_payload,
)
from app.main import configure_runtime_dependencies


class FakeRuntime:
    def __init__(self):
        self.calls = []
        self.fail_preload = False
        self.loaded = {}

    def preload(self, deployment_id, revision_id):
        if self.fail_preload:
            raise RuntimeError("INFERENCE_RUNTIME_UNAVAILABLE")
        self.calls.append(("preload", str(deployment_id), str(revision_id)))

    def load(self, runtime_key, specification):
        self.calls.append(("load", str(runtime_key)))
        self.loaded[str(runtime_key)] = specification

    def unload(self, runtime_key):
        self.calls.append(("unload", str(runtime_key)))
        return self.loaded.pop(str(runtime_key), None) is not None


class ConflictPreservingRuntime(FakeRuntime):
    """Match RuntimeRegistry behavior: a key cannot change identity in place."""

    def __init__(self):
        super().__init__()
        self.fail_legacy_model_version_id = None
        self.raise_after_legacy_model_version_id = None
        self.legacy_runtime_key = None

    def load(self, runtime_key, specification):
        runtime_key = str(runtime_key)
        existing = self.loaded.get(runtime_key)
        if existing is not None and existing != specification:
            raise InferenceRuntimeClientError("DEPLOYMENT_SPEC_CONFLICT")
        if (
            runtime_key == self.legacy_runtime_key
            and specification["model_version_id"] == self.fail_legacy_model_version_id
        ):
            raise InferenceRuntimeClientError("MODEL_LOAD_FAILED")
        loaded = super().load(runtime_key, specification)
        if (
            runtime_key == self.legacy_runtime_key
            and specification["model_version_id"]
            == self.raise_after_legacy_model_version_id
        ):
            raise InferenceRuntimeClientError("INFERENCE_RUNTIME_UNAVAILABLE")
        return loaded


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
        self.candidate_version = ModelVersion(
            registered_model_id=registered.id,
            version_number=2,
            source_kind="onnx_artifact",
            source_artifact_id=candidate_artifact.id,
            onnx_artifact_id=candidate_artifact.id,
            approval_status="approved",
            created_by_id=self.actor.id,
        )
        self.db.add(self.candidate_version)
        self.db.flush()
        self.deployment = InferenceDeployment(
            project_id=self.project.id,
            name="primary",
            model_version_id=self.version.id,
            created_by_id=self.actor.id,
        )
        self.db.add(self.deployment)
        self.db.commit()
        self.stable_revision = DeploymentRevision(
            deployment_id=self.deployment.id,
            revision_number=1,
            strategy="immediate",
            status="stable",
            created_by_id=self.actor.id,
        )
        self.db.add(self.stable_revision)
        self.db.flush()
        self.db.add(DeploymentTarget(
            revision_id=self.stable_revision.id,
            model_version_id=self.version.id,
            weight_bps=10000,
            role="stable",
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def make_revision(self):
        revision = DeploymentRevision(
            deployment_id=self.deployment.id,
            revision_number=3,
            strategy="canary",
            status="candidate",
            created_by_id=self.actor.id,
        )
        self.db.add(revision)
        self.db.flush()
        return revision

    def make_candidate_revision(self, weights=(7000, 3000)):
        revision = DeploymentRevision(
            deployment_id=self.deployment.id,
            revision_number=2,
            strategy="canary",
            status="candidate",
            created_by_id=self.actor.id,
        )
        self.db.add(revision)
        self.db.flush()
        self.db.add_all([
            DeploymentTarget(
                revision_id=revision.id,
                model_version_id=self.version.id,
                weight_bps=weights[0],
                role="stable",
            ),
            DeploymentTarget(
                revision_id=revision.id,
                model_version_id=self.candidate_version.id,
                weight_bps=weights[1],
                role="candidate",
            ),
        ])
        self.db.commit()
        self.db.refresh(revision)
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

    def test_weighted_router_is_stable_and_sorted_by_model_id(self):
        revision = self.make_candidate_revision((7000, 3000))
        router = WeightedTargetRouter()
        first = router.select(revision, "request-42")
        second = router.select(revision, "request-42")
        self.assertEqual(first, second)
        self.assertEqual(first.revision_id, revision.id)
        self.assertIn(first.model_version_id, {
            self.version.id,
            self.candidate_version.id,
        })

    def test_weighted_router_rejects_non_integer_weights(self):
        revision = SimpleNamespace(
            id=uuid4(),
            deployment_id=self.deployment.id,
            targets=[
                SimpleNamespace(model_version_id=self.version.id, weight_bps=9999.5),
                SimpleNamespace(model_version_id=self.candidate_version.id, weight_bps=0.5),
            ],
        )
        with self.assertRaisesRegex(InferenceRolloutError, "TARGET_WEIGHTS_INVALID"):
            WeightedTargetRouter().select(revision, "request-42")

    def test_active_rollout_selects_revision_then_target(self):
        candidate = self.make_candidate_revision((9000, 1000))
        rollout = DeploymentRollout(
            deployment_id=self.deployment.id,
            from_revision_id=self.stable_revision.id,
            to_revision_id=candidate.id,
            state="progressing",
            current_step=1000,
            lock_version=1,
            step_schedule=[0, 1000, 5000, 10000],
            thresholds={"max_error_rate": 0.01, "max_p95_ms": 500},
        )
        self.db.add(rollout)
        self.db.commit()
        self.db.refresh(self.deployment)
        routed = WeightedTargetRouter().select_active(self.deployment, "request-42")
        self.assertIn(routed.revision_id, {
            self.stable_revision.id,
            candidate.id,
        })

    def test_create_candidate_rejects_unapproved_cross_project_and_duplicate_targets(self):
        service = InferenceRolloutService(FakeRuntime())
        self.version.approval_status = "pending"
        self.db.commit()
        with self.assertRaisesRegex(InferenceRolloutError, "MODEL_VERSION_NOT_APPROVED"):
            service.create_candidate(
                self.db,
                self.deployment.id,
                self.actor.id,
                [{"model_version_id": self.version.id, "weight_bps": 10000}],
            )
        self.version.approval_status = "approved"
        self.db.commit()
        other_project = Project(name="Other rollout project", owner_id=self.actor.id)
        self.db.add(other_project)
        self.db.flush()
        foreign_artifact = Artifact(
            project_id=other_project.id,
            name="foreign.onnx",
            type="model",
            storage_path="",
            storage_uri="s3://models/foreign.onnx",
            file_size=1,
            format="onnx",
        )
        self.db.add(foreign_artifact)
        self.db.flush()
        foreign_model = RegisteredModel(
            project_id=other_project.id,
            name="Foreign model",
            created_by_id=self.actor.id,
        )
        self.db.add(foreign_model)
        self.db.flush()
        foreign_version = ModelVersion(
            registered_model_id=foreign_model.id,
            version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=foreign_artifact.id,
            onnx_artifact_id=foreign_artifact.id,
            approval_status="approved",
            created_by_id=self.actor.id,
        )
        self.db.add(foreign_version)
        self.db.commit()
        with self.assertRaisesRegex(InferenceRolloutError, "MODEL_VERSION_NOT_FOUND"):
            service.create_candidate(
                self.db,
                self.deployment.id,
                self.actor.id,
                [{"model_version_id": foreign_version.id, "weight_bps": 10000}],
            )
        with self.assertRaisesRegex(InferenceRolloutError, "TARGET_DUPLICATE"):
            service.create_candidate(
                self.db,
                self.deployment.id,
                self.actor.id,
                [
                    {"model_version_id": self.candidate_version.id, "weight_bps": 5000},
                    {"model_version_id": self.candidate_version.id, "weight_bps": 5000},
                ],
            )

    def test_only_one_active_rollout_is_allowed(self):
        service = InferenceRolloutService(FakeRuntime())
        service.create_candidate(
            self.db,
            self.deployment.id,
            self.actor.id,
            [{"model_version_id": self.candidate_version.id, "weight_bps": 10000}],
        )
        with self.assertRaisesRegex(InferenceRolloutError, "ROLLOUT_ALREADY_ACTIVE"):
            service.create_candidate(
                self.db,
                self.deployment.id,
                self.actor.id,
                [{"model_version_id": self.candidate_version.id, "weight_bps": 10000}],
            )

    def test_preload_and_advance_persist_default_steps_until_completion(self):
        runtime = FakeRuntime()
        service = InferenceRolloutService(runtime)
        rollout = service.create_candidate(
            self.db,
            self.deployment.id,
            self.actor.id,
            [{"model_version_id": self.candidate_version.id, "weight_bps": 10000}],
        )
        rollout = service.preload(
            self.db, rollout.id, expected_lock_version=rollout.lock_version,
        )
        self.assertEqual((rollout.state, rollout.current_step), ("progressing", 0))
        for expected_step in (1000, 5000, 10000):
            rollout = service.advance(
                self.db,
                rollout.id,
                expected_lock_version=rollout.lock_version,
                observation={"error_rate": 0.0, "p95_ms": 1},
            )
            self.assertEqual(rollout.current_step, expected_step)
        self.assertEqual(rollout.state, "completed")
        legacy_specification = runtime.loaded[str(self.deployment.id)]
        self.assertEqual(
            legacy_specification["model_version_id"],
            str(self.candidate_version.id),
        )
        self.assertEqual(
            legacy_specification["revision_id"],
            str(rollout.to_revision_id),
        )

    def _rollout_ready_for_completion(self, runtime):
        service = InferenceRolloutService(runtime)
        rollout = service.create_candidate(
            self.db,
            self.deployment.id,
            self.actor.id,
            [{"model_version_id": self.candidate_version.id, "weight_bps": 10000}],
        )
        rollout = service.preload(
            self.db,
            rollout.id,
            expected_lock_version=rollout.lock_version,
        )
        for _ in (1000, 5000):
            rollout = service.advance(
                self.db,
                rollout.id,
                expected_lock_version=rollout.lock_version,
                observation={"error_rate": 0.0, "p95_ms": 1},
            )
        stable = self.db.query(DeploymentRevision).filter_by(
            deployment_id=self.deployment.id,
            status="stable",
        ).one()
        candidate = rollout.to_revision
        candidate_target = candidate.targets[0]
        runtime.load(
            self.deployment.id,
            InferenceDeploymentService._specification(self.db, self.deployment),
        )
        candidate_key = f"{candidate.id}:{candidate_target.model_version_id}"
        runtime.load(
            candidate_key,
            InferenceDeploymentService._target_specification(
                self.db,
                self.deployment,
                candidate,
                candidate_target,
            ),
        )
        return service, rollout, stable, candidate, candidate_key

    def test_completion_replaces_conflicting_legacy_key_and_keeps_candidate_alias(self):
        runtime = ConflictPreservingRuntime()
        service, rollout, _stable, candidate, candidate_key = (
            self._rollout_ready_for_completion(runtime)
        )

        completed = service.advance(
            self.db,
            rollout.id,
            expected_lock_version=rollout.lock_version,
            observation={"error_rate": 0.0, "p95_ms": 1},
        )

        self.assertEqual(completed.state, "completed")
        self.assertEqual(
            runtime.loaded[str(self.deployment.id)]["model_version_id"],
            str(self.candidate_version.id),
        )
        self.assertEqual(
            runtime.loaded[str(self.deployment.id)]["revision_id"],
            str(candidate.id),
        )
        self.assertIn(candidate_key, runtime.loaded)
        self.assertEqual(candidate.status, "stable")

    def test_legacy_replacement_failure_restores_stable_and_pauses_rollout(self):
        runtime = ConflictPreservingRuntime()
        service, rollout, stable, candidate, candidate_key = (
            self._rollout_ready_for_completion(runtime)
        )
        runtime.legacy_runtime_key = str(self.deployment.id)
        runtime.fail_legacy_model_version_id = str(self.candidate_version.id)

        with self.assertRaisesRegex(
            InferenceRolloutError,
            "ROLLOUT_LEGACY_REFRESH_FAILED",
        ):
            service.advance(
                self.db,
                rollout.id,
                expected_lock_version=rollout.lock_version,
                observation={"error_rate": 0.0, "p95_ms": 1},
            )

        self.db.refresh(rollout)
        self.db.refresh(stable)
        self.db.refresh(candidate)
        self.assertEqual((rollout.state, rollout.current_step), ("paused", 0))
        self.assertEqual(rollout.last_error_code, "ROLLOUT_LEGACY_REFRESH_FAILED")
        self.assertEqual(stable.status, "stable")
        self.assertEqual(candidate.status, "candidate")
        self.assertEqual(
            runtime.loaded[str(self.deployment.id)]["model_version_id"],
            str(self.version.id),
        )
        self.assertIn(candidate_key, runtime.loaded)

    def test_ambiguous_legacy_load_failure_restores_stable_before_pausing(self):
        runtime = ConflictPreservingRuntime()
        service, rollout, stable, candidate, candidate_key = (
            self._rollout_ready_for_completion(runtime)
        )
        runtime.legacy_runtime_key = str(self.deployment.id)
        runtime.raise_after_legacy_model_version_id = str(self.candidate_version.id)

        with self.assertRaisesRegex(
            InferenceRolloutError,
            "ROLLOUT_LEGACY_REFRESH_FAILED",
        ):
            service.advance(
                self.db,
                rollout.id,
                expected_lock_version=rollout.lock_version,
                observation={"error_rate": 0.0, "p95_ms": 1},
            )

        self.db.refresh(rollout)
        self.db.refresh(stable)
        self.db.refresh(candidate)
        self.assertEqual((rollout.state, rollout.current_step), ("paused", 0))
        self.assertEqual(stable.status, "stable")
        self.assertEqual(candidate.status, "candidate")
        self.assertEqual(
            runtime.loaded[str(self.deployment.id)]["model_version_id"],
            str(self.version.id),
        )
        self.assertIn(candidate_key, runtime.loaded)

    def test_preload_fails_closed_without_runtime_preload_or_load(self):
        candidate = self.make_candidate_revision((9000, 1000))
        rollout = DeploymentRollout(
            deployment_id=self.deployment.id,
            from_revision_id=self.stable_revision.id,
            to_revision_id=candidate.id,
            state="pending",
            current_step=0,
            lock_version=1,
            step_schedule=[0, 1000, 5000, 10000],
            thresholds={"max_error_rate": 0.01, "max_p95_ms": 500},
        )
        self.db.add(rollout)
        self.db.commit()
        with self.assertRaisesRegex(InferenceRolloutError, "ROLLOUT_PRELOAD_FAILED"):
            InferenceRolloutService(object()).preload(
                self.db,
                rollout.id,
                expected_lock_version=1,
            )
        self.db.refresh(rollout)
        self.assertEqual(rollout.last_error_code, "ROLLOUT_PRELOAD_FAILED")

    def test_stale_rollout_command_is_rejected(self):
        candidate = self.make_candidate_revision((9000, 1000))
        rollout = DeploymentRollout(
            deployment_id=self.deployment.id,
            from_revision_id=self.stable_revision.id,
            to_revision_id=candidate.id,
            state="progressing",
            current_step=1000,
            lock_version=2,
            step_schedule=[0, 1000, 5000, 10000],
            thresholds={"max_error_rate": 0.01, "max_p95_ms": 500},
        )
        self.db.add(rollout)
        self.db.commit()
        with self.assertRaisesRegex(InferenceRolloutError, "ROLLOUT_REVISION_CONFLICT"):
            InferenceRolloutService(FakeRuntime()).advance(
                self.db, rollout.id, expected_lock_version=1,
            )

    def test_preload_failure_marks_rollout_failed_and_restores_stable_step(self):
        candidate = self.make_candidate_revision((9000, 1000))
        runtime = FakeRuntime()
        runtime.fail_preload = True
        service = InferenceRolloutService(runtime)
        rollout = DeploymentRollout(
            deployment_id=self.deployment.id,
            from_revision_id=self.stable_revision.id,
            to_revision_id=candidate.id,
            state="pending",
            current_step=0,
            lock_version=1,
            step_schedule=[0, 1000, 5000, 10000],
            thresholds={"max_error_rate": 0.01, "max_p95_ms": 500},
        )
        self.db.add(rollout)
        self.db.commit()
        with self.assertRaisesRegex(InferenceRolloutError, "ROLLOUT_PRELOAD_FAILED"):
            service.preload(self.db, rollout.id, expected_lock_version=1)
        self.db.refresh(rollout)
        self.assertEqual((rollout.state, rollout.current_step), ("failed", 0))

    def test_threshold_failure_restores_stable_weights_before_pause(self):
        candidate = self.make_candidate_revision((9000, 1000))
        runtime = FakeRuntime()
        service = InferenceRolloutService(runtime)
        rollout = DeploymentRollout(
            deployment_id=self.deployment.id,
            from_revision_id=self.stable_revision.id,
            to_revision_id=candidate.id,
            state="progressing",
            current_step=1000,
            lock_version=1,
            step_schedule=[0, 1000, 5000, 10000],
            thresholds={"max_error_rate": 0.01, "max_p95_ms": 500},
        )
        self.db.add(rollout)
        self.db.commit()
        with self.assertRaisesRegex(InferenceRolloutError, "ROLLOUT_HEALTH_THRESHOLD_EXCEEDED"):
            service.advance(
                self.db,
                rollout.id,
                expected_lock_version=1,
                observation={"error_rate": 0.02, "p95_ms": 100},
            )
        self.db.refresh(rollout)
        self.assertEqual((rollout.state, rollout.current_step), ("paused", 0))

    def test_rollback_is_idempotent_and_restores_stable_revision(self):
        candidate = self.make_candidate_revision((9000, 1000))
        rollout = DeploymentRollout(
            deployment_id=self.deployment.id,
            from_revision_id=self.stable_revision.id,
            to_revision_id=candidate.id,
            state="completed",
            current_step=10000,
            lock_version=2,
            step_schedule=[0, 1000, 5000, 10000],
            thresholds={"max_error_rate": 0.01, "max_p95_ms": 500},
        )
        self.db.add(rollout)
        self.db.commit()
        service = InferenceRolloutService(FakeRuntime())
        first = service.rollback(self.db, rollout.id, expected_lock_version=2)
        second = service.rollback(self.db, rollout.id, expected_lock_version=first.lock_version)
        self.assertEqual(first.id, second.id)
        self.assertEqual((second.state, second.current_step), ("rolled_back", 0))

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

    def test_domain_event_direct_constructor_rejects_unknown_type(self):
        with self.assertRaisesRegex(ValueError, "DOMAIN_EVENT_TYPE_INVALID"):
            DomainEvent(
                event_id=uuid4(),
                idempotency_key="unknown:1",
                event_type="unknown.event",
                severity="info",
                occurred_at=datetime.now(timezone.utc),
                project_id=None,
                actor_id=None,
                resource_type="deployment",
                resource_id=None,
                payload={},
            )

    def test_domain_event_payload_is_immutable(self):
        event = create_domain_event(
            idempotency_key="rollout:1:completed:1",
            event_type="rollout.completed",
            severity="info",
            occurred_at=datetime.now(timezone.utc),
            project_id=None,
            actor_id=None,
            resource_type="deployment",
            resource_id=None,
            payload={"step": 1},
        )
        with self.assertRaises(TypeError):
            event.payload["step"] = 2

    def test_domain_event_deep_freezes_nested_payload_values(self):
        model_version_ids = ["version-1", "version-2"]
        nested_step = {"name": "canary"}
        event = create_domain_event(
            idempotency_key="rollout:1:completed:1",
            event_type="rollout.completed",
            severity="info",
            occurred_at=datetime.now(timezone.utc),
            project_id=None,
            actor_id=None,
            resource_type="deployment",
            resource_id=None,
            payload={
                "model_version_ids": model_version_ids,
                "step": nested_step,
            },
        )

        model_version_ids.append("version-3")
        nested_step["name"] = "promoted"

        self.assertEqual(
            event.payload["model_version_ids"],
            ("version-1", "version-2"),
        )
        self.assertEqual(event.payload["step"]["name"], "canary")
        with self.assertRaises(TypeError):
            event.payload["model_version_ids"][0] = "mutated"
        with self.assertRaises(TypeError):
            event.payload["step"]["name"] = "mutated"

    def test_storage_payload_thaws_without_mutating_domain_event(self):
        event = create_domain_event(
            idempotency_key="rollout:1:completed:1",
            event_type="rollout.completed",
            severity="info",
            occurred_at=datetime.now(timezone.utc),
            project_id=None,
            actor_id=None,
            resource_type="deployment",
            resource_id=None,
            payload={
                "model_version_ids": ["version-1", "version-2"],
                "step": {"name": "canary"},
            },
        )

        storage_payload = to_storage_payload(event.payload)

        self.assertEqual(
            storage_payload,
            {
                "model_version_ids": ["version-1", "version-2"],
                "step": {"name": "canary"},
            },
        )
        json.dumps(storage_payload)
        storage_payload["model_version_ids"].append("version-3")
        storage_payload["step"]["name"] = "promoted"
        self.assertEqual(
            event.payload["model_version_ids"],
            ("version-1", "version-2"),
        )
        self.assertEqual(event.payload["step"]["name"], "canary")

    def test_domain_event_accepts_json_native_payload_values(self):
        event = create_domain_event(
            idempotency_key="rollout:1:completed:1",
            event_type="rollout.completed",
            severity="info",
            occurred_at=datetime.now(timezone.utc),
            project_id=None,
            actor_id=None,
            resource_type="deployment",
            resource_id=None,
            payload={
                "revision_id": "revision-1",
                "deployment_id": None,
                "model_version_ids": ("version-1",),
                "step": 2.5,
            },
        )
        self.assertEqual(event.payload["revision_id"], "revision-1")
        self.assertIsNone(event.payload["deployment_id"])
        self.assertEqual(event.payload["model_version_ids"], ("version-1",))
        self.assertEqual(event.payload["step"], 2.5)

    def test_domain_event_rejects_non_json_payload_values(self):
        class UnsupportedValue:
            pass

        invalid_payloads = (
            {"step": uuid4()},
            {"model_version_ids": {"version-1"}},
            {"step": {1: "non-string-key"}},
            {"step": UnsupportedValue()},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaisesRegex(
                ValueError, "DOMAIN_EVENT_PAYLOAD_INVALID"
            ):
                create_domain_event(
                    idempotency_key="rollout:1:completed:1",
                    event_type="rollout.completed",
                    severity="info",
                    occurred_at=datetime.now(timezone.utc),
                    project_id=None,
                    actor_id=None,
                    resource_type="deployment",
                    resource_id=None,
                    payload=payload,
                )

    def test_domain_event_rejects_nonfinite_float_payload_values(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "DOMAIN_EVENT_PAYLOAD_INVALID"
            ):
                create_domain_event(
                    idempotency_key="rollout:1:completed:1",
                    event_type="rollout.completed",
                    severity="info",
                    occurred_at=datetime.now(timezone.utc),
                    project_id=None,
                    actor_id=None,
                    resource_type="deployment",
                    resource_id=None,
                    payload={"step": value},
                )

    def test_runtime_dependencies_default_and_custom_domain_recorder(self):
        target = FastAPI()
        recorder = RecordingEventRecorder()
        configure_runtime_dependencies(target, domain_event_recorder=recorder)
        self.assertIs(target.state.domain_event_recorder, recorder)
        configure_runtime_dependencies(target, domain_event_recorder=None)
        self.assertIsInstance(target.state.domain_event_recorder, NullDomainEventRecorder)


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
