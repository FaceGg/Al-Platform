import os
import tempfile
import unittest
import uuid
from pathlib import Path

import httpx
import joblib
import numpy as np
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression

import app.main  # noqa: F401 (load the complete production model graph)
from app.api.auth import create_access_token
from app.config import settings
from app.database import SessionLocal
from app.models.access import AuditEvent
from app.models.model_library import ModelLibrary
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.artifact_service import build_artifact_service
from app.services.inference_deployment import (
    InferenceDeploymentError,
    InferenceDeploymentService,
)
from app.services.inference_runtime_client import InferenceRuntimeClient
from app.services.model_registry import ModelRegistryService


@unittest.skipUnless(
    os.getenv("RUN_INFERENCE_INTEGRATION") == "1",
    "RUN_INFERENCE_INTEGRATION is not enabled",
)
class TestInferenceProductionStack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        secret = settings.resolved_inference_internal_secret
        if secret is None or not settings.inference_runtime_url:
            raise RuntimeError("Production inference runtime is not configured")
        cls.runtime = InferenceRuntimeClient(
            settings.inference_runtime_url,
            secret.get_secret_value(),
            load_timeout_seconds=settings.inference_load_timeout_seconds,
            predict_timeout_seconds=settings.inference_predict_timeout_seconds,
        )
        cls.deployments = InferenceDeploymentService(cls.runtime, SessionLocal)
        unique = uuid.uuid4().hex

        with tempfile.TemporaryDirectory() as directory, SessionLocal() as db:
            owner = User(
                username=f"inference-integration-{unique}",
                password_hash="integration-only-hash",
            )
            db.add(owner)
            db.flush()
            project = Project(name=f"Inference integration {unique}", owner_id=owner.id)
            db.add(project)
            db.flush()

            features = [
                {"name": "current", "dtype": "float64"},
                {"name": "force", "dtype": "float64"},
            ]
            target = {
                "name": "fault",
                "dtype": "int64",
                "task": "classification",
            }
            estimator = LogisticRegression(random_state=0).fit(
                np.asarray([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [2.0, 2.0]]),
                np.asarray([0, 0, 0, 1]),
            )
            source_path = Path(directory) / "trusted-weld-model.joblib"
            joblib.dump(
                {
                    "model": estimator,
                    "feature_schema": features,
                    "target_schema": target,
                },
                source_path,
            )
            artifacts = build_artifact_service(db)
            job = TrainingJob(
                project_id=project.id,
                user_id=owner.id,
                name="trusted-weld-model",
                status="completed",
                feature_schema=features,
                target_schema=target,
            )
            db.add(job)
            db.flush()
            source = artifacts.create_from_file(
                project.id,
                source_path,
                source_path.name,
                "model",
                metadata={
                    "source": "training",
                    "training_job_id": str(job.id),
                },
                commit=False,
            )
            library = ModelLibrary(
                name=job.name,
                project_id=project.id,
                owner_id=owner.id,
                status="completed",
                framework="scikit-learn",
                backbone="LogisticRegression",
                metrics={"accuracy": 1.0},
                format="joblib",
                training_job_id=job.id,
                model_artifact_id=source.id,
            )
            db.add(library)
            db.flush()
            job.model_artifact_id = source.id
            job.model_library_id = library.id
            db.commit()

            cls.project_id = project.id
            cls.library_id = library.id
            cls.owner_id = owner.id

        cls.client = TestClient(app.main.app)
        cls.headers = {
            "Authorization": f"Bearer {create_access_token({'sub': str(cls.owner_id)})}",
        }
        response = cls.client.post(
            f"/api/projects/{cls.project_id}/registered-models",
            headers=cls.headers,
            json={
                "name": f"Weld Fault {unique}",
                "description": "Production integration classifier",
            },
        )
        cls._assert_response(response, 201)
        model_id = response.json()["id"]
        response = cls.client.post(
            f"/api/registered-models/{model_id}/versions",
            headers=cls.headers,
            json={
                "source_kind": "platform_joblib",
                "source_model_library_id": str(cls.library_id),
            },
        )
        cls._assert_response(response, 201)
        version_id = response.json()["id"]
        response = cls.client.post(
            f"/api/model-versions/{version_id}/approve",
            headers=cls.headers,
            json={"comment": "production verified"},
        )
        cls._assert_response(response, 200)
        response = cls.client.post(
            f"/api/projects/{cls.project_id}/inference-deployments",
            headers=cls.headers,
            json={
                "name": f"weld-runtime-{unique}",
                "model_version_id": version_id,
            },
        )
        cls._assert_response(response, 201)
        cls.deployment_id = uuid.UUID(response.json()["id"])

    @staticmethod
    def _assert_response(response, expected):
        if response.status_code != expected:
            raise AssertionError(
                f"Expected HTTP {expected}, got {response.status_code}: {response.text}"
            )

    @classmethod
    def tearDownClass(cls):
        try:
            cls.runtime.unload(cls.deployment_id)
        except Exception:
            pass
        cls.client.close()

    def test_real_registration_runtime_restart_reconciliation_and_stop(self):
        records = [
            {"current": 0.0, "force": 0.0},
            {"current": 2.0, "force": 2.0},
        ]
        response = self.client.post(
            f"/api/inference-deployments/{self.deployment_id}/start",
            headers=self.headers,
        )
        self._assert_response(response, 200)
        self.assertEqual(
            (response.json()["desired_state"], response.json()["observed_state"]),
            ("running", "running"),
        )
        response = self.client.post(
            f"/api/inference-deployments/{self.deployment_id}/predict",
            headers=self.headers,
            json={"records": records},
        )
        self._assert_response(response, 200)
        first = response.json()

        self.assertEqual(first["predictions"], [0, 1])
        self.assertEqual(first["deployment_id"], str(self.deployment_id))

        self.runtime.unload(self.deployment_id)
        self.assertNotIn(
            str(self.deployment_id),
            {item["deployment_id"] for item in self.runtime.list()["items"]},
        )
        with SessionLocal() as db:
            reconciled = self.deployments.reconcile(db)
            self.assertEqual(reconciled, {"loaded": 1, "unloaded": 0, "failed": 0})
            second = self.deployments.predict(db, self.deployment_id, records)
            self.assertEqual(second["predictions"], first["predictions"])
            serialized_events = "\n".join(
                str({
                    "action": item.action,
                    "changes": item.changes,
                    "error_code": item.error_code,
                })
                for item in db.query(AuditEvent).filter(
                    AuditEvent.project_id == self.project_id,
                ).all()
            )
        response = self.client.post(
            f"/api/inference-deployments/{self.deployment_id}/stop",
            headers=self.headers,
        )
        self._assert_response(response, 200)
        self.assertEqual(
            (response.json()["desired_state"], response.json()["observed_state"]),
            ("stopped", "stopped"),
        )
        response = self.client.post(
            f"/api/inference-deployments/{self.deployment_id}/predict",
            headers=self.headers,
            json={"records": records},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "DEPLOYMENT_NOT_READY")

        self.assertIn("model_version.register", serialized_events)
        self.assertIn("inference_deployment.start", serialized_events)
        secret = settings.resolved_inference_internal_secret.get_secret_value()
        self.assertNotIn(str(records[0]["current"]), serialized_events)
        self.assertNotIn(str(records[1]["force"]), serialized_events)
        self.assertNotIn(secret, serialized_events)
        self.assertNotIn("s3://", serialized_events)
        self.assertNotIn("Traceback", serialized_events)

        health = httpx.get(
            f"{settings.inference_runtime_url.rstrip('/')}/health",
            timeout=5.0,
        )
        self.assertEqual(health.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
