import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.config import Settings
from app.database import Base, get_db
from app.main import app
from app.models.access import ProjectMember
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


class DenyingRateLimiter:
    def consume(self, *_args, **_kwargs):
        return SimpleNamespace(allowed=False, retry_after_seconds=4)


class FrozenWeek9Week10ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)
        cls.db = cls.Session()
        cls._had_settings = hasattr(app.state, "settings")
        cls._previous_settings = getattr(app.state, "settings", None)
        app.state.settings = Settings(
            notification_master_key=Fernet.generate_key().decode("ascii"),
        )

        cls.users = {
            role: User(
                username=f"week11-contract-{role}",
                password_hash="hash",
                role="engineer",
            )
            for role in ("owner", "editor", "operator", "viewer", "outsider")
        }
        cls.db.add_all(cls.users.values())
        cls.db.flush()

        cls.project = Project(
            name="Week 11 frozen contracts",
            owner_id=cls.users["owner"].id,
        )
        cls.db.add(cls.project)
        cls.db.flush()
        cls.db.add_all(
            ProjectMember(
                project_id=cls.project.id,
                user_id=cls.users[role].id,
                role=role,
                created_by=cls.users["owner"].id,
            )
            for role in ("editor", "operator", "viewer")
        )

        stable_artifact = Artifact(
            project_id=cls.project.id,
            name="stable-contract.onnx",
            type="model",
            storage_path="",
            storage_uri="s3://week11-contracts/stable.onnx",
            format="onnx",
        )
        candidate_artifact = Artifact(
            project_id=cls.project.id,
            name="candidate-contract.onnx",
            type="model",
            storage_path="",
            storage_uri="s3://week11-contracts/candidate.onnx",
            format="onnx",
        )
        cls.db.add_all((stable_artifact, candidate_artifact))
        cls.db.flush()
        model = RegisteredModel(
            project_id=cls.project.id,
            name="Week 11 contract model",
            created_by_id=cls.users["owner"].id,
        )
        cls.db.add(model)
        cls.db.flush()
        cls.stable_version = ModelVersion(
            registered_model_id=model.id,
            version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=stable_artifact.id,
            onnx_artifact_id=stable_artifact.id,
            approval_status="approved",
            created_by_id=cls.users["owner"].id,
        )
        cls.candidate_version = ModelVersion(
            registered_model_id=model.id,
            version_number=2,
            source_kind="onnx_artifact",
            source_artifact_id=candidate_artifact.id,
            onnx_artifact_id=candidate_artifact.id,
            approval_status="approved",
            created_by_id=cls.users["owner"].id,
        )
        cls.db.add_all((cls.stable_version, cls.candidate_version))
        cls.db.flush()

        cls.deployment = InferenceDeployment(
            project_id=cls.project.id,
            name="week11-contract-deployment",
            model_version_id=cls.stable_version.id,
            desired_state="running",
            observed_state="running",
            created_by_id=cls.users["owner"].id,
        )
        cls.db.add(cls.deployment)
        cls.db.flush()
        cls.stable_revision = DeploymentRevision(
            deployment_id=cls.deployment.id,
            revision_number=1,
            strategy="immediate",
            status="stable",
            created_by_id=cls.users["owner"].id,
        )
        cls.candidate_revision = DeploymentRevision(
            deployment_id=cls.deployment.id,
            revision_number=2,
            strategy="canary",
            status="candidate",
            created_by_id=cls.users["owner"].id,
        )
        cls.db.add_all((cls.stable_revision, cls.candidate_revision))
        cls.db.flush()
        cls.db.add_all((
            DeploymentTarget(
                revision_id=cls.stable_revision.id,
                model_version_id=cls.stable_version.id,
                weight_bps=10000,
                role="stable",
            ),
            DeploymentTarget(
                revision_id=cls.candidate_revision.id,
                model_version_id=cls.candidate_version.id,
                weight_bps=10000,
                role="candidate",
            ),
        ))
        cls.rollout = DeploymentRollout(
            deployment_id=cls.deployment.id,
            from_revision_id=cls.stable_revision.id,
            to_revision_id=cls.candidate_revision.id,
            state="progressing",
            current_step=1000,
            lock_version=1,
            step_schedule=[0, 1000, 10000],
            thresholds={"max_error_rate": 0.01, "max_p95_ms": 500},
        )
        cls.db.add(cls.rollout)
        cls.db.commit()

        cls.current_user = cls.users["owner"]
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.current_user
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        app.dependency_overrides.clear()
        if cls._had_settings:
            app.state.settings = cls._previous_settings
        else:
            delattr(app.state, "settings")
        cls.db.close()
        cls.engine.dispose()

    def setUp(self):
        self._as("owner")

    def _as(self, role):
        self.__class__.current_user = self.users[role]

    def _create_api_key(self, *, expires_at=None):
        body = {"scopes": ["inference.predict"]}
        if expires_at is not None:
            body["expires_at"] = expires_at.isoformat()
        response = self.client.post(
            f"/api/inference-deployments/{self.deployment.id}/api-keys",
            json=body,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["plaintext"]

    def _create_in_app_endpoint(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/notification-endpoints",
            json={
                "kind": "in_app",
                "name": f"contract-in-app-{uuid.uuid4().hex}",
                "config": {"recipient_user_ids": [str(self.users["owner"].id)]},
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_rollout_response_exposes_revision_and_actual_model_target(self):
        response = self.client.get(
            f"/api/inference-deployments/{self.deployment.id}/rollouts/{self.rollout.id}",
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["state"], "progressing")
        self.assertEqual(payload["to_revision_id"], str(self.candidate_revision.id))
        self.assertEqual(
            payload["targets"],
            [{
                "model_version_id": str(self.candidate_version.id),
                "weight_bps": 10000,
            }],
        )

    def test_production_inference_rejects_missing_and_expired_api_keys(self):
        url = f"/api/v1/inference/{self.deployment.id}/predict"
        missing = self.client.post(url, json={"records": [{"current": 0.0}]})
        self.assertEqual(missing.status_code, 401, missing.text)
        self.assertEqual(
            missing.json()["detail"]["code"],
            "INFERENCE_API_KEY_INVALID",
        )

        expired_key = self._create_api_key(
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        expired = self.client.post(
            url,
            headers={"X-Inference-Api-Key": expired_key},
            json={"records": [{"current": 0.0}]},
        )
        self.assertEqual(expired.status_code, 401, expired.text)
        self.assertEqual(
            expired.json()["detail"]["code"],
            "INFERENCE_API_KEY_EXPIRED",
        )

    def test_production_inference_rate_limit_returns_retry_after(self):
        api_key = self._create_api_key()
        with patch(
            "app.api.inference_production._default_rate_limiter",
            return_value=DenyingRateLimiter(),
        ):
            response = self.client.post(
                f"/api/v1/inference/{self.deployment.id}/predict",
                headers={"X-Inference-Api-Key": api_key},
                json={"records": [{"current": 0.0}]},
            )

        self.assertEqual(response.status_code, 429, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "INFERENCE_RATE_LIMITED",
        )
        retry_after = int(response.headers["Retry-After"])
        self.assertGreaterEqual(retry_after, 1)
        self.assertLessEqual(retry_after, 60)

    def test_notification_endpoint_test_never_returns_secret_records_or_predictions(self):
        signing_secret = "week11-contract-signing-secret"
        header_secret = "Bearer week11-contract-header-secret"
        with patch(
            "app.services.webhook_security._resolve_host",
            return_value=["8.8.8.8"],
        ):
            created = self.client.post(
                f"/api/projects/{self.project.id}/notification-endpoints",
                json={
                    "kind": "webhook",
                    "name": f"contract-webhook-{uuid.uuid4().hex}",
                    "config": {
                        "url": "https://hooks.example.invalid/notification",
                        "headers": {"X-Contract-Authorization": header_secret},
                        "signature_mode": "hmac-sha256",
                        "signing_secret": signing_secret,
                    },
                },
            )
        self.assertEqual(created.status_code, 201, created.text)

        with patch(
            "app.services.webhook_security._resolve_host",
            return_value=["8.8.8.8"],
        ), patch(
            "app.services.notification_channels.httpx.post",
            return_value=Mock(status_code=202),
        ):
            tested = self.client.post(
                f"/api/projects/{self.project.id}/notification-endpoints/{created.json()['id']}/test",
            )

        self.assertEqual(tested.status_code, 200, tested.text)
        self.assertEqual(set(tested.json()), {"status", "error_code"})
        body = tested.text.lower()
        self.assertNotIn(signing_secret.lower(), body)
        self.assertNotIn(header_secret.lower(), body)
        self.assertNotIn("records", body)
        self.assertNotIn("prediction", body)

    def test_notification_authorization_matrix_preserves_403_and_404_semantics(self):
        endpoint_id = self._create_in_app_endpoint()
        list_url = f"/api/projects/{self.project.id}/notification-endpoints"
        test_url = f"{list_url}/{endpoint_id}/test"

        for role in ("owner", "editor"):
            with self.subTest(role=role, action="manage"):
                self._as(role)
                response = self.client.post(test_url)
                self.assertEqual(response.status_code, 200, response.text)

        for role in ("operator", "viewer"):
            with self.subTest(role=role, action="read"):
                self._as(role)
                readable = self.client.get(list_url)
                self.assertEqual(readable.status_code, 200, readable.text)
            with self.subTest(role=role, action="manage"):
                denied = self.client.post(test_url)
                self.assertEqual(denied.status_code, 403, denied.text)
                self.assertEqual(
                    denied.json()["detail"]["code"],
                    "PROJECT_PERMISSION_DENIED",
                )

        self._as("outsider")
        hidden_read = self.client.get(list_url)
        self.assertEqual(hidden_read.status_code, 404, hidden_read.text)
        self.assertEqual(
            hidden_read.json()["detail"]["code"],
            "PROJECT_NOT_FOUND",
        )
        hidden_manage = self.client.post(test_url)
        self.assertEqual(hidden_manage.status_code, 404, hidden_manage.text)
        self.assertEqual(
            hidden_manage.json()["detail"]["code"],
            "PROJECT_NOT_FOUND",
        )


if __name__ == "__main__":
    unittest.main()
