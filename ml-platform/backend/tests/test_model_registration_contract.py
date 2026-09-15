import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.api.model_registry import build_model_registry_router
from app.database import Base, get_db
from app.models.access import ProjectMember
from app.models.artifact import Artifact
from app.models.model_library import ModelLibrary
from app.models.model_registry import ModelVersion
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.artifact_service import ArtifactService
from app.services.inference_deployment import InferenceDeploymentService
from app.services.model_registry import ModelRegistryService
from app.services.onnx_conversion import ConversionResult
from app.services.project_access import ProjectAccessError
from app.storage.local import LocalStorage


class _Runtime:
    def load(self, *_args, **_kwargs):
        return {"already_loaded": False}

    def unload(self, *_args, **_kwargs):
        return {"already_absent": False}


class TestModelRegistrationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        cls.db = cls.Session()
        cls.owner = User(username="model-registration-owner", password_hash="hash")
        cls.intruder = User(username="model-registration-intruder", password_hash="hash")
        cls.db.add_all([cls.owner, cls.intruder])
        cls.db.flush()
        cls.project = Project(name="Model registration", owner_id=cls.owner.id)
        cls.db.add(cls.project)
        cls.db.commit()
        cls.storage = LocalStorage(Path(cls.temporary.name) / "storage")
        cls.artifacts = ArtifactService(cls.db, cls.storage)

        def fake_converter(_source, destination, **_kwargs):
            destination.write_bytes(b"converted-onnx")
            return ConversionResult(
                input_names=("features",),
                output_names=("prediction",),
                opset=17,
                sha256="c" * 64,
                size=destination.stat().st_size,
                converter="contract-test",
                feature_schema=[{"name": "current", "dtype": "float64"}],
                output_schema={"name": "label_a", "dtype": "int64", "task": "classification"},
            )

        cls.registry = ModelRegistryService(
            artifact_service=cls.artifacts,
            converter=fake_converter,
        )
        app = FastAPI()

        @app.exception_handler(ProjectAccessError)
        async def project_access_error(_request, error):
            return JSONResponse(
                status_code=404 if error.hidden else 403,
                content={"detail": {"code": error.code}},
            )

        app.include_router(build_model_registry_router(
            registry_service=cls.registry,
            deployment_service=InferenceDeploymentService(_Runtime(), cls.Session),
            session_factory=cls.Session,
        ))

        def override_db():
            yield cls.db

        app.dependency_overrides[get_db] = override_db
        cls.current_user = cls.owner
        app.dependency_overrides[get_current_user] = lambda: cls.current_user
        cls.app = app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.db.close()
        cls.engine.dispose()
        cls.temporary.cleanup()

    def _candidate(self, *, status="completed"):
        candidate_id = uuid.uuid4()
        job = TrainingJob(
            project_id=self.project.id,
            user_id=self.owner.id,
            name=f"candidate-{candidate_id.hex[:8]}",
            status="completed",
            dataset_artifact_id=None,
            feature_schema=[
                {"name": "current", "dtype": "float64"},
                {"name": "force", "dtype": "float64"},
            ],
            target_schema=[
                {"name": "label_a", "dtype": "int64", "task": "multioutput_classification", "classes": [0, 1]},
                {"name": "label_b", "dtype": "object", "task": "multioutput_classification", "classes": ["a", "b"]},
            ],
            preprocessing={"imputer": "median", "scaler": "standard"},
        )
        self.db.add(job)
        self.db.flush()
        source = Path(self.temporary.name) / f"{candidate_id}.joblib"
        source.write_bytes(b"trusted-joblib")
        input_contract = {
            "task_type": "multioutput_classification",
            "target_columns": ["label_a", "label_b"],
            "input_columns": ["current", "force"],
            "target_schema": job.target_schema,
            "data_version_id": "dataset-v1",
        }
        artifact = self.artifacts.create_from_file(
            self.project.id,
            source,
            source.name,
            "model",
            metadata={
                "source": "automl",
                "training_job_id": str(job.id),
                "candidate_id": str(candidate_id),
                "input_contract": input_contract,
            },
            commit=False,
        )
        job.metrics = {
            "input_contract": input_contract,
            "preprocessing": job.preprocessing,
            "feature_importance_report": {"features": [{"name": "current", "score": 0.7}]},
            "algorithm_results": [{
                "candidate_id": str(candidate_id),
                "algorithm_id": str(candidate_id),
                "name": "Candidate",
                "status": status,
                "model_artifact_id": str(artifact.id),
                "per_target": {"label_a": {"f1": 0.9}, "label_b": {"f1": 0.8}},
            }],
        }
        self.db.commit()
        return job, candidate_id, artifact

    def setUp(self):
        self.__class__.current_user = self.owner

    def test_only_complete_candidate_can_be_registered(self):
        job, candidate_id, _artifact = self._candidate(status="failed")

        response = self.client.post(
            f"/api/automl-tasks/{job.id}/register",
            json={"candidate_id": str(candidate_id), "model_name": "candidate-a"},
            headers={"Idempotency-Key": "incomplete-candidate-key"},
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "CANDIDATE_NOT_REGISTERABLE")

    def test_registration_is_idempotent_for_same_candidate_and_key(self):
        job, candidate_id, _artifact = self._candidate()
        payload = {"candidate_id": str(candidate_id), "model_name": f"candidate-{candidate_id.hex[:8]}"}

        first = self.client.post(
            f"/api/automl-tasks/{job.id}/register",
            json=payload,
            headers={"Idempotency-Key": "register-1"},
        )
        second = self.client.post(
            f"/api/automl-tasks/{job.id}/register",
            json=payload,
            headers={"Idempotency-Key": "register-1"},
        )

        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["model_version_id"], second.json()["model_version_id"])
        self.assertEqual(
            self.db.query(ModelVersion).filter(ModelVersion.id == uuid.UUID(first.json()["model_version_id"])).count(),
            1,
        )

    def test_registered_model_preserves_multilabel_contract_without_worker_registry_write(self):
        job, candidate_id, _artifact = self._candidate()
        self.assertEqual(
            self.db.query(ModelLibrary).filter(ModelLibrary.training_job_id == job.id).count(),
            0,
        )

        response = self.client.post(
            f"/api/automl-tasks/{job.id}/register",
            json={"candidate_id": str(candidate_id), "model_name": f"candidate-{candidate_id.hex[:8]}"},
            headers={"Idempotency-Key": "register-contract"},
        )

        self.assertEqual(response.status_code, 201, response.text)
        version = self.db.get(ModelVersion, uuid.UUID(response.json()["model_version_id"]))
        self.assertEqual(version.output_schema["target_columns"], ["label_a", "label_b"])
        self.assertEqual(
            [(column["machine_key"], column["dtype"]) for column in version.output_schema["columns"]],
            [("label_a", "int64"), ("label_b", "object")],
        )
        self.assertTrue(version.conversion_metadata["input_contract_hash"])
        self.assertEqual(version.lifecycle_state, "pending_review")

    def test_registration_for_missing_task_returns_job_not_found(self):
        response = self.client.post(
            f"/api/automl-tasks/{uuid.uuid4()}/register",
            json={"candidate_id": str(uuid.uuid4()), "model_name": "missing-task"},
            headers={"Idempotency-Key": "missing-task-key"},
        )

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"]["code"], "AUTOML_JOB_NOT_FOUND")

    def test_registration_requires_an_idempotency_key_before_mutation(self):
        job, candidate_id, _artifact = self._candidate()

        response = self.client.post(
            f"/api/automl-tasks/{job.id}/register",
            json={"candidate_id": str(candidate_id), "model_name": "missing-key"},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["code"], "IDEMPOTENCY_KEY_REQUIRED")
        self.assertEqual(
            self.db.query(ModelVersion).filter(ModelVersion.registration_task_id == job.id).count(),
            0,
        )

    def test_registration_hides_another_projects_candidate(self):
        job, candidate_id, _artifact = self._candidate()
        self.__class__.current_user = self.intruder

        response = self.client.post(
            f"/api/automl-tasks/{job.id}/register",
            json={"candidate_id": str(candidate_id), "model_name": "foreign-candidate"},
            headers={"Idempotency-Key": "foreign-candidate-key"},
        )

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(
            self.db.query(ModelVersion).filter(ModelVersion.registration_task_id == job.id).count(),
            0,
        )

    def test_registration_rejects_same_idempotency_key_with_changed_payload(self):
        job, first_candidate_id, _artifact = self._candidate()

        first = self.client.post(
            f"/api/automl-tasks/{job.id}/register",
            json={"candidate_id": str(first_candidate_id), "model_name": "first-candidate"},
            headers={"Idempotency-Key": "reused-registration-key"},
        )
        second = self.client.post(
            f"/api/automl-tasks/{job.id}/register",
            json={"candidate_id": str(first_candidate_id), "model_name": "renamed-candidate"},
            headers={"Idempotency-Key": "reused-registration-key"},
        )

        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(
            second.json()["detail"]["code"],
            "MODEL_REGISTRATION_IDEMPOTENCY_CONFLICT",
        )
        self.assertEqual(
            self.db.query(ModelVersion).filter(ModelVersion.registration_task_id == job.id).count(),
            1,
        )


if __name__ == "__main__":
    unittest.main()
