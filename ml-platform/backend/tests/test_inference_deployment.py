import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import create_engine
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
from app.services.inference_deployment import (
    InferenceDeploymentError,
    InferenceDeploymentService,
)


class FakeRuntimeClient:
    def __init__(self):
        self.loaded = {}
        self.fail_load = None

    def load(self, deployment_id, specification):
        if self.fail_load:
            raise InferenceDeploymentError(self.fail_load)
        self.loaded[str(deployment_id)] = specification
        return {"already_loaded": False}

    def unload(self, deployment_id):
        self.loaded.pop(str(deployment_id), None)
        return {"already_absent": False}

    def predict(self, deployment_id, records):
        if str(deployment_id) not in self.loaded:
            raise InferenceDeploymentError("DEPLOYMENT_NOT_READY")
        return {"predictions": [1], "records_seen": len(records)}

    def list(self):
        return {"items": [
            {"deployment_id": key} for key in self.loaded
        ]}


class TestInferenceDeploymentService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(username="deployment-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Deployment", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.artifact = Artifact(
            project_id=self.project.id, name="model.onnx", type="model",
            storage_path="", storage_uri="s3://models/model.onnx",
            file_size=12, format="onnx", metadata_={"sha256": "a" * 64},
        )
        self.db.add(self.artifact)
        self.db.flush()
        self.model = RegisteredModel(
            project_id=self.project.id, name="Fault", created_by_id=self.user.id,
        )
        self.db.add(self.model)
        self.db.flush()
        self.version = ModelVersion(
            registered_model_id=self.model.id, version_number=1,
            source_kind="onnx_artifact", source_artifact_id=self.artifact.id,
            onnx_artifact_id=self.artifact.id, framework="onnx", algorithm="",
            feature_schema=[{"name": "current", "dtype": "float64"}],
            output_schema={"name": "fault", "dtype": "int64", "task": "classification"},
            metrics={}, conversion_metadata={
                "sha256": "a" * 64, "size": 12,
                "input_names": ["features"], "output_names": ["label"],
            }, approval_status="approved", created_by_id=self.user.id,
        )
        self.db.add(self.version)
        self.db.commit()
        self.candidate_artifact = Artifact(
            project_id=self.project.id, name="candidate.onnx", type="model",
            storage_path="", storage_uri="s3://models/candidate.onnx",
            file_size=12, format="onnx", metadata_={"sha256": "b" * 64},
        )
        self.db.add(self.candidate_artifact)
        self.db.flush()
        self.candidate_version = ModelVersion(
            registered_model_id=self.model.id, version_number=2,
            source_kind="onnx_artifact", source_artifact_id=self.candidate_artifact.id,
            onnx_artifact_id=self.candidate_artifact.id, framework="onnx", algorithm="",
            feature_schema=[{"name": "current", "dtype": "float64"}],
            output_schema={"name": "fault", "dtype": "int64", "task": "classification"},
            conversion_metadata={
                "sha256": "b" * 64, "size": 12,
                "input_names": ["features"], "output_names": ["label"],
            }, approval_status="approved", created_by_id=self.user.id,
        )
        self.db.add(self.candidate_version)
        self.db.commit()
        self.runtime = FakeRuntimeClient()
        self.service = InferenceDeploymentService(self.runtime, self.Session)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_create_requires_approved_version(self):
        self.version.approval_status = "pending"
        self.db.commit()
        with self.assertRaises(InferenceDeploymentError) as raised:
            self.service.create(
                self.db, project_id=self.project.id, version_id=self.version.id,
                actor_id=self.user.id, name="primary",
            )
        self.assertEqual(raised.exception.code, "MODEL_NOT_APPROVED")

    def test_start_stop_and_predict_update_observed_state(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="primary",
        )
        started = self.service.start(self.db, deployment.id)
        self.assertEqual((started.desired_state, started.observed_state), ("running", "running"))
        self.assertEqual(self.service.predict(self.db, deployment.id, [{"current": 8.0}])["predictions"], [1])
        stopped = self.service.stop(self.db, deployment.id)
        self.assertEqual((stopped.desired_state, stopped.observed_state), ("stopped", "stopped"))
        with self.assertRaises(InferenceDeploymentError) as raised:
            self.service.predict(self.db, deployment.id, [{"current": 8.0}])
        self.assertEqual(raised.exception.code, "DEPLOYMENT_NOT_READY")

    def test_runtime_spec_includes_legacy_runtime_key_and_revision_identity(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="revision-aware",
        )
        self.service.start(self.db, deployment.id)
        specification = self.runtime.loaded[str(deployment.id)]
        self.assertEqual(specification["runtime_key"], str(deployment.id))
        self.assertEqual(specification["deployment_id"], str(deployment.id))
        self.assertIsNotNone(specification["revision_id"])

    def test_stable_weighted_route_uses_legacy_runtime_session(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="stable-routed",
        )
        self.service.start(self.db, deployment.id)
        prediction = self.service.predict(
            self.db,
            deployment.id,
            [{"current": 8.0}],
            routing_key="request-42",
        )
        self.assertEqual(prediction["predictions"], [1])

    def test_stop_unloads_legacy_stable_and_active_candidate_sessions(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="stop-aliases",
        )
        self.service.start(self.db, deployment.id)
        stable = self.db.query(DeploymentRevision).filter_by(
            deployment_id=deployment.id, status="stable",
        ).one()
        candidate = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=2,
            strategy="canary",
            status="candidate",
            created_by_id=self.user.id,
        )
        self.db.add(candidate)
        self.db.flush()
        candidate_target = DeploymentTarget(
            revision_id=candidate.id,
            model_version_id=self.candidate_version.id,
            weight_bps=10000,
            role="candidate",
        )
        self.db.add(candidate_target)
        self.db.add(DeploymentRollout(
            deployment_id=deployment.id,
            from_revision_id=stable.id,
            to_revision_id=candidate.id,
            state="progressing",
            current_step=1000,
            lock_version=1,
            step_schedule=[0, 1000, 5000, 10000],
            thresholds={"max_error_rate": 0.01, "max_p95_ms": 500},
        ))
        self.db.commit()
        candidate_key = f"{candidate.id}:{self.candidate_version.id}"
        self.runtime.load(
            candidate_key,
            self.service._target_specification(
                self.db,
                deployment,
                candidate,
                candidate_target,
            ),
        )

        self.service.stop(self.db, deployment.id)

        self.assertNotIn(str(deployment.id), self.runtime.loaded)
        self.assertNotIn(f"{stable.id}:{self.version.id}", self.runtime.loaded)
        self.assertNotIn(candidate_key, self.runtime.loaded)
        with self.assertRaises(InferenceDeploymentError):
            self.runtime.predict(candidate_key, [{"current": 8.0}])

    def test_reconcile_leaves_active_candidate_alias_recovery_to_rollout_service(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="candidate-restart",
        )
        self.service.start(self.db, deployment.id)
        stable = self.db.query(DeploymentRevision).filter_by(
            deployment_id=deployment.id, status="stable",
        ).one()
        candidate = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=2,
            strategy="canary",
            status="candidate",
            created_by_id=self.user.id,
        )
        self.db.add(candidate)
        self.db.flush()
        self.db.add(DeploymentTarget(
            revision_id=candidate.id,
            model_version_id=self.version.id,
            weight_bps=10000,
            role="candidate",
        ))
        rollout = DeploymentRollout(
            deployment_id=deployment.id,
            from_revision_id=stable.id,
            to_revision_id=candidate.id,
            state="progressing",
            current_step=1000,
            lock_version=1,
            step_schedule=[0, 1000, 5000, 10000],
            thresholds={"max_error_rate": 0.01, "max_p95_ms": 500},
        )
        self.db.add(rollout)
        self.db.commit()
        self.runtime.loaded.pop(str(deployment.id))
        self.runtime.load(str(deployment.id), self.service._specification(self.db, deployment))
        result = self.service.reconcile(self.db)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["loaded"], 0)
        self.assertNotIn(
            f"{candidate.id}:{self.version.id}",
            self.runtime.loaded,
        )

        self.runtime.load(
            f"{candidate.id}:{self.version.id}",
            self.service._target_specification(
                self.db, deployment, candidate, candidate.targets[0],
            ),
        )
        loaded_before_reconcile = list(self.runtime.loaded)
        second_result = self.service.reconcile(self.db)
        self.assertEqual(second_result["loaded"], 0)
        self.assertEqual(loaded_before_reconcile, list(self.runtime.loaded))
        self.assertIn(
            f"{candidate.id}:{self.version.id}",
            self.runtime.loaded,
        )

    def test_runtime_failure_persists_only_stable_code_and_can_retry(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="primary",
        )
        self.runtime.fail_load = "INFERENCE_RUNTIME_UNAVAILABLE"
        with self.assertRaises(InferenceDeploymentError):
            self.service.start(self.db, deployment.id)
        self.db.refresh(deployment)
        self.assertEqual(deployment.observed_state, "failed")
        self.assertEqual(deployment.last_error_code, "INFERENCE_RUNTIME_UNAVAILABLE")
        self.runtime.fail_load = None
        self.assertEqual(self.service.start(self.db, deployment.id).observed_state, "running")

    def test_reconcile_reloads_desired_running_after_runtime_restart(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="primary",
        )
        self.service.start(self.db, deployment.id)
        self.runtime.loaded.clear()
        result = self.service.reconcile(self.db)
        self.assertEqual(result, {"loaded": 1, "unloaded": 0, "failed": 0})
        self.assertIn(str(deployment.id), self.runtime.loaded)


if __name__ == "__main__":
    unittest.main()
