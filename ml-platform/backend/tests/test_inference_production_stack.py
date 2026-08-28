import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

import httpx
import joblib
import numpy as np
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression

import app.main  # noqa: F401 (load the complete production model graph)
from app.api.auth import create_access_token
from app.config import settings
from app.database import SessionLocal
from app.models.access import AuditEvent
from app.models.model_library import ModelLibrary
from app.models.model_registry import InferenceRequestLog
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.artifact_service import build_artifact_service
from app.services.inference_deployment import (
    InferenceDeploymentError,
    InferenceDeploymentService,
)
from app.services.inference_runtime_client import InferenceRuntimeClient
from app.services.inference_rollout import InferenceRolloutService


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def alembic_head():
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


@unittest.skipUnless(
    os.getenv("RUN_INFERENCE_INTEGRATION") == "1",
    "production inference integration disabled",
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
        cls.model_id = model_id
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
        cls.version_id = version_id
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

    def create_approved_deployment(self, *, version_number):
        self.assertEqual(version_number, 1)
        response = self.client.post(
            f"/api/inference-deployments/{self.deployment_id}/start",
            headers=self.headers,
        )
        self._assert_response(response, 200)
        self.assertEqual(
            (response.json()["desired_state"], response.json()["observed_state"]),
            ("running", "running"),
        )
        return {
            "id": str(self.deployment_id),
            "registered_model_id": self.model_id,
        }

    def create_api_key(self, deployment_id):
        response = self.client.post(
            f"/api/inference-deployments/{deployment_id}/api-keys",
            headers=self.headers,
            json={"scopes": ["inference.predict"]},
        )
        self._assert_response(response, 201)
        created = response.json()
        self.assertTrue(created.get("plaintext", "").startswith("mli_"))
        return created

    def predict(self, plaintext, deployment_id, records):
        response = self.client.post(
            f"/api/v1/inference/{deployment_id}/predict",
            headers={"X-Inference-Api-Key": plaintext},
            json={"records": records},
        )
        self._assert_response(response, 200)
        return response.json()

    def create_candidate(self, deployment_id, *, version_number):
        response = self.client.post(
            f"/api/registered-models/{self.model_id}/versions",
            headers=self.headers,
            json={
                "source_kind": "platform_joblib",
                "source_model_library_id": str(self.library_id),
            },
        )
        self._assert_response(response, 201)
        version = response.json()
        self.assertEqual(version["version_number"], version_number)
        response = self.client.post(
            f"/api/model-versions/{version['id']}/approve",
            headers=self.headers,
            json={"comment": "production verified"},
        )
        self._assert_response(response, 200)
        response = self.client.post(
            f"/api/inference-deployments/{deployment_id}/rollouts",
            headers=self.headers,
            json={
                "strategy": "canary",
                "targets": [{"model_version_id": version["id"], "weight_bps": 10000}],
            },
        )
        self._assert_response(response, 201)
        return response.json()

    def advance_to_completion(self, rollout_id):
        service = InferenceRolloutService(self.runtime)
        with SessionLocal() as db:
            rollout = service.preload(db, rollout_id)
            while rollout.state != "completed":
                rollout = service.advance(
                    db,
                    rollout.id,
                    expected_lock_version=rollout.lock_version,
                    observation={"error_rate": 0.0, "p95_ms": 1.0},
                )
            return rollout

    def clear_runtime_sessions(self):
        runtime_keys = [
            item.get("runtime_key") or item["deployment_id"]
            for item in self.runtime.list().get("items", [])
            if str(item.get("deployment_id")) == str(self.deployment_id)
        ]
        self.assertTrue(runtime_keys)
        for runtime_key in runtime_keys:
            self.runtime.unload(runtime_key)
        remaining = {
            item.get("runtime_key") or item["deployment_id"]
            for item in self.runtime.list().get("items", [])
            if str(item.get("deployment_id")) == str(self.deployment_id)
        }
        self.assertFalse(remaining)

    def reconcile(self):
        with SessionLocal() as db:
            return self.deployments.reconcile(db)

    def rollback(self, rollout_id):
        current = self.client.get(
            f"/api/inference-deployments/{self.deployment_id}/rollouts/{rollout_id}",
            headers=self.headers,
        )
        self._assert_response(current, 200)
        response = self.client.post(
            f"/api/inference-deployments/{self.deployment_id}/rollouts/{rollout_id}/rollback",
            headers=self.headers,
            json={"expected_lock_version": current.json()["lock_version"]},
        )
        self._assert_response(response, 200)
        return response.json()

    def _write_outage_context(self, plaintext):
        path_value = os.getenv("INFERENCE_INTEGRATION_CONTEXT_PATH")
        if not path_value:
            return
        path = Path(path_value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "deployment_id": str(self.deployment_id),
                "plaintext": plaintext,
            }),
            encoding="utf-8",
        )
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def _assert_database_is_redacted(self, plaintext, records, predictions):
        with SessionLocal() as db:
            request_logs = db.query(InferenceRequestLog).filter(
                InferenceRequestLog.deployment_id == self.deployment_id,
            ).all()
            audit_events = db.query(AuditEvent).filter(
                AuditEvent.project_id == self.project_id,
            ).all()
            serialized = json.dumps(
                {
                    "request_logs": [
                        {
                            "request_id": item.request_id,
                            "status": item.status,
                            "error_code": item.error_code,
                            "batch_size": item.batch_size,
                        }
                        for item in request_logs
                    ],
                    "audit_events": [
                        {
                            "action": item.action,
                            "changes": item.changes,
                            "error_code": item.error_code,
                        }
                        for item in audit_events
                    ],
                },
                default=str,
                sort_keys=True,
            )
        self.assertGreaterEqual(len(request_logs), 1)
        secret = settings.resolved_inference_internal_secret.get_secret_value()
        for value in (
            plaintext,
            secret,
            json.dumps(records, sort_keys=True),
            json.dumps(predictions),
            "s3://",
            "Traceback",
        ):
            self.assertNotIn(value, serialized)

    def test_rollout_key_restart_and_rollback(self):
        self.assertEqual(alembic_head(), "20260826_13")
        self.assertLessEqual(settings.inference_rate_limit_capacity, 5)
        records = [{"current": 1234.567, "force": 7654.321}]
        deployment = self.create_approved_deployment(version_number=1)
        plaintext = self.create_api_key(deployment["id"])["plaintext"]
        self._write_outage_context(plaintext)
        first = self.predict(plaintext, deployment["id"], records)
        self.assertEqual(first["version_number"], 1)

        rollout = self.create_candidate(deployment["id"], version_number=2)
        completed = self.advance_to_completion(rollout["id"])
        self.assertEqual(completed.state, "completed")
        second = self.predict(plaintext, deployment["id"], records)
        self.assertEqual(second["version_number"], 2)

        self.clear_runtime_sessions()
        reconciled = self.reconcile()
        self.assertGreaterEqual(reconciled["loaded"], 1)
        self.assertEqual(reconciled["failed"], 0)
        restarted = self.predict(plaintext, deployment["id"], records)
        self.assertEqual(restarted["version_number"], 2)

        rolled_back = self.rollback(rollout["id"])
        self.assertEqual(rolled_back["state"], "rolled_back")
        restored = self.predict(plaintext, deployment["id"], records)
        self.assertEqual(restored["version_number"], 1)

        rate_key = self.create_api_key(deployment["id"])["plaintext"]
        for _ in range(settings.inference_rate_limit_capacity):
            self.predict(rate_key, deployment["id"], records)
        limited = self.client.post(
            f"/api/v1/inference/{deployment['id']}/predict",
            headers={"X-Inference-Api-Key": rate_key},
            json={"records": records},
        )
        self.assertEqual(limited.status_code, 429, limited.text)
        self.assertEqual(limited.json()["detail"]["code"], "INFERENCE_RATE_LIMITED")
        self.assertGreaterEqual(int(limited.headers["Retry-After"]), 1)

        self._assert_database_is_redacted(plaintext, records, restored["predictions"])

        health = httpx.get(
            f"{settings.inference_runtime_url.rstrip('/')}/health",
            timeout=5.0,
        )
        self.assertEqual(health.json(), {"status": "ok"})


@unittest.skipUnless(
    os.getenv("RUN_INFERENCE_INTEGRATION") == "1"
    and os.getenv("INFERENCE_INTEGRATION_CONTEXT_PATH"),
    "production inference integration disabled",
)
class TestInferenceProductionRedisOutage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(os.environ["INFERENCE_INTEGRATION_CONTEXT_PATH"])
        if not path.is_file():
            raise RuntimeError("Missing inference integration outage context")
        cls.context = json.loads(path.read_text(encoding="utf-8"))
        cls.client = TestClient(app.main.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_redis_outage_fails_closed_before_runtime_invocation(self):
        deployment_id = uuid.UUID(self.context["deployment_id"])
        with SessionLocal() as db:
            before = db.query(InferenceRequestLog).filter(
                InferenceRequestLog.deployment_id == deployment_id,
            ).count()

        response = self.client.post(
            f"/api/v1/inference/{deployment_id}/predict",
            headers={"X-Inference-Api-Key": self.context["plaintext"]},
            json={"records": [{"current": 1234.567, "force": 7654.321}]},
        )

        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "RATE_LIMIT_BACKEND_UNAVAILABLE",
        )
        with SessionLocal() as db:
            after = db.query(InferenceRequestLog).filter(
                InferenceRequestLog.deployment_id == deployment_id,
            ).count()
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
