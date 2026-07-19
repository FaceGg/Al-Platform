import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.artifact import Artifact
from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
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
