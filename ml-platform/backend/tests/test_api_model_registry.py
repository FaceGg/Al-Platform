import io
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.api.model_registry import build_model_registry_router
from app.database import Base, get_db
from app.models.access import AuditEvent, ProjectMember
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
from app.services.inference_deployment import InferenceDeploymentService
from app.services.model_registry import ModelRegistryService
from app.services.project_access import ProjectAccessError
from app.services.onnx_conversion import ConversionResult
from app.services.artifact_service import ArtifactService
from app.storage.local import LocalStorage


class FakeRuntime:
    def __init__(self):
        self.loaded = set()

    def load(self, deployment_id, specification):
        self.loaded.add(str(deployment_id))
        return {"already_loaded": False}

    def unload(self, deployment_id):
        self.loaded.discard(str(deployment_id))
        return {"already_absent": False}

    def predict(self, deployment_id, records):
        return {
            "deployment_id": str(deployment_id),
            "model_version_id": "runtime-version",
            "version_number": 1,
            "predictions": [1 for _ in records],
            "probabilities": [[0.08, 0.92] for _ in records],
            "duration_ms": 1.2,
        }

    def list(self):
        return {"items": [{"deployment_id": item} for item in self.loaded]}


class TestModelRegistryAPI(unittest.TestCase):
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
        cls.users = {
            role: User(username=f"registry-api-{role}", password_hash="hash")
            for role in ("owner", "editor", "operator", "viewer", "outsider")
        }
        cls.db.add_all(cls.users.values())
        cls.db.flush()
        cls.project = Project(name="Registry API", owner_id=cls.users["owner"].id)
        cls.db.add(cls.project)
        cls.db.flush()
        for role in ("editor", "operator", "viewer"):
            cls.db.add(ProjectMember(
                project_id=cls.project.id,
                user_id=cls.users[role].id,
                role=role,
                created_by=cls.users["owner"].id,
            ))
        cls.db.commit()
        cls.storage = LocalStorage(Path(cls.temporary.name) / "storage")
        cls.artifact_service = ArtifactService(cls.db, cls.storage)

        def fake_validator(path, feature_schema, output_schema):
            return ConversionResult(
                input_names=("features",), output_names=("label", "probabilities"),
                opset=17, sha256="a" * 64, size=path.stat().st_size,
                converter="upload", feature_schema=feature_schema,
                output_schema=output_schema,
            )

        cls.registry_service = ModelRegistryService(
            artifact_service=cls.artifact_service,
            validator=fake_validator,
        )
        cls.runtime = FakeRuntime()
        cls.deployment_service = InferenceDeploymentService(cls.runtime, cls.Session)
        app = FastAPI()
        @app.exception_handler(ProjectAccessError)
        async def project_access_error(_request, error):
            return JSONResponse(
                status_code=404 if error.hidden else 403,
                content={"detail": {"code": error.code}},
            )
        app.include_router(build_model_registry_router(
            registry_service=cls.registry_service,
            deployment_service=cls.deployment_service,
            session_factory=cls.Session,
        ))

        def override_db():
            yield cls.db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: cls.users["owner"]
        cls.app = app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.db.close()
        cls.engine.dispose()
        cls.temporary.cleanup()

    def as_role(self, role):
        self.app.dependency_overrides[get_current_user] = lambda: self.users[role]

    def test_01_strict_schema_rejects_unknown_fields(self):
        self.as_role("owner")
        response = self.client.post(
            f"/api/projects/{self.project.id}/registered-models",
            json={"name": "Fault", "description": "", "unexpected": True},
        )
        self.assertEqual(response.status_code, 422)

    def test_02_owner_creates_model_and_editor_uploads_registers_and_approves(self):
        self.as_role("owner")
        created = self.client.post(
            f"/api/projects/{self.project.id}/registered-models",
            json={"name": "Fault Classifier", "description": "Weld faults"},
        )
        self.assertEqual(created.status_code, 201)
        model_id = created.json()["id"]

        self.as_role("editor")
        uploaded = self.client.post(
            f"/api/projects/{self.project.id}/model-artifacts",
            files={"file": ("fault.onnx", io.BytesIO(b"onnx-content"), "application/octet-stream")},
        )
        self.assertEqual(uploaded.status_code, 201)
        artifact_id = uploaded.json()["id"]
        registered = self.client.post(
            f"/api/registered-models/{model_id}/versions",
            json={
                "source_kind": "onnx_artifact",
                "source_artifact_id": artifact_id,
                "feature_schema": [{"name": "current", "dtype": "float64"}],
                "output_schema": {"name": "fault", "dtype": "int64", "task": "classification"},
            },
        )
        self.assertEqual(registered.status_code, 201)
        version_id = registered.json()["id"]
        approved = self.client.post(
            f"/api/model-versions/{version_id}/approve",
            json={"comment": "ready"},
        )
        self.assertEqual(approved.json()["approval_status"], "approved")
        self.__class__.model_id = model_id
        self.__class__.version_id = version_id

    def test_03_operator_cannot_register_but_can_operate_and_predict(self):
        self.as_role("operator")
        denied = self.client.post(
            f"/api/projects/{self.project.id}/registered-models",
            json={"name": "Denied", "description": ""},
        )
        self.assertEqual(denied.status_code, 403)
        deployment = self.client.post(
            f"/api/projects/{self.project.id}/inference-deployments",
            json={"name": "primary", "model_version_id": self.version_id},
        )
        self.assertEqual(deployment.status_code, 403)

        self.as_role("editor")
        deployment = self.client.post(
            f"/api/projects/{self.project.id}/inference-deployments",
            json={"name": "primary", "model_version_id": self.version_id},
        )
        self.assertEqual(deployment.status_code, 201)
        deployment_id = deployment.json()["id"]
        self.__class__.deployment_id = deployment_id
        self.as_role("operator")
        started = self.client.post(f"/api/inference-deployments/{deployment_id}/start")
        self.assertEqual(started.json()["observed_state"], "running")
        predicted = self.client.post(
            f"/api/inference-deployments/{deployment_id}/predict",
            json={"records": [{"current": 8.0}]},
        )
        self.assertEqual(predicted.json()["predictions"], [1])
        stopped = self.client.post(f"/api/inference-deployments/{deployment_id}/stop")
        self.assertEqual(stopped.json()["observed_state"], "stopped")

    def test_04_viewer_reads_but_cannot_operate_and_outsider_is_hidden(self):
        self.as_role("viewer")
        listing = self.client.get(
            f"/api/projects/{self.project.id}/registered-models"
        )
        self.assertEqual(listing.status_code, 200)
        self.assertGreaterEqual(len(listing.json()["items"]), 1)
        denied = self.client.post(
            f"/api/model-versions/{self.version_id}/archive",
            json={"comment": "no"},
        )
        self.assertEqual(denied.status_code, 403)

        self.as_role("outsider")
        hidden = self.client.get(f"/api/registered-models/{self.model_id}")
        self.assertEqual(hidden.status_code, 404)

    def test_05_audit_events_are_redacted_and_cover_commands(self):
        events = self.db.query(AuditEvent).all()
        outcomes = {(event.action, event.result) for event in events}
        self.assertIn(("registered_model.create", "success"), outcomes)
        self.assertIn(("registered_model.create", "denied"), outcomes)
        self.assertIn(("model_version.register", "success"), outcomes)
        self.assertIn(("model_version.approve", "success"), outcomes)
        self.assertIn(("inference_deployment.create", "success"), outcomes)
        self.assertIn(("inference_deployment.start", "success"), outcomes)
        self.assertIn(("inference_deployment.stop", "success"), outcomes)
        encoded = str([event.changes for event in events]).lower()
        self.assertNotIn("onnx-content", encoded)
        self.assertNotIn("current", encoded)

    def test_06_rollout_routes_use_the_frozen_canonical_path(self):
        routes = {
            (route.path, method)
            for route in self.app.routes
            for method in getattr(route, "methods", set())
        }
        self.assertIn(("/api/inference-deployments/{deployment_id}/rollouts", "GET"), routes)
        self.assertIn(("/api/inference-deployments/{deployment_id}/rollouts", "POST"), routes)
        self.assertNotIn(("/api/inference-deployments/{deployment_id}/releases", "GET"), routes)

    def test_07_metric_and_log_queries_reject_unknown_parameters(self):
        self.as_role("owner")
        params = {
            "since": "2026-01-01T00:00:00", "until": "2026-01-02T00:00:00",
            "unexpected": "true",
        }
        for suffix in ("request-logs", "metrics"):
            with self.subTest(suffix=suffix):
                response = self.client.get(
                    f"/api/inference-deployments/{self.deployment_id}/{suffix}",
                    params=params,
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_08_rollout_targets_and_key_management_follow_project_roles(self):
        payload = {"targets": [{"model_version_id": self.version_id, "weight_bps": 10000}]}
        self.as_role("operator")
        denied = self.client.post(
            f"/api/inference-deployments/{self.deployment_id}/rollouts", json=payload,
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        self.assertEqual(
            self.client.get(f"/api/inference-deployments/{self.deployment_id}/api-keys").status_code,
            403,
        )

        self.as_role("editor")
        created = self.client.post(
            f"/api/inference-deployments/{self.deployment_id}/rollouts", json=payload,
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["targets"], payload["targets"])

        self.as_role("operator")
        command = self.client.post(
            f"/api/inference-deployments/{self.deployment_id}/rollouts/{created.json()['id']}/pause",
            json={"expected_lock_version": created.json()["lock_version"]},
        )
        self.assertEqual(command.status_code, 200, command.text)

        self.as_role("outsider")
        self.assertEqual(
            self.client.get(f"/api/inference-deployments/{self.deployment_id}/api-keys").status_code,
            404,
        )

    def test_09_rollout_creation_rolls_back_when_audit_commit_fails(self):
        unique = uuid.uuid4().hex
        artifact = Artifact(
            project_id=self.project.id,
            name=f"audit-{unique}.onnx",
            type="model",
            storage_path="",
            storage_uri=f"local://audit/{unique}.onnx",
            file_size=1,
            format="onnx",
        )
        self.db.add(artifact)
        self.db.flush()
        model = RegisteredModel(
            project_id=self.project.id,
            name=f"Audit {unique}",
            created_by_id=self.users["owner"].id,
        )
        self.db.add(model)
        self.db.flush()
        version = ModelVersion(
            registered_model_id=model.id,
            version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=artifact.id,
            onnx_artifact_id=artifact.id,
            approval_status="approved",
            created_by_id=self.users["owner"].id,
        )
        self.db.add(version)
        self.db.flush()
        deployment = InferenceDeployment(
            project_id=self.project.id,
            name=f"audit-{unique}",
            model_version_id=version.id,
            created_by_id=self.users["owner"].id,
        )
        self.db.add(deployment)
        self.db.commit()

        self.as_role("owner")
        before = self.db.query(DeploymentRollout).count()
        payload = {
            "targets": [{"model_version_id": str(version.id), "weight_bps": 10000}],
        }
        with patch.object(self.db, "commit", side_effect=RuntimeError("audit unavailable")):
            with TestClient(self.app, raise_server_exceptions=False) as client:
                response = client.post(
                    f"/api/inference-deployments/{deployment.id}/rollouts",
                    json=payload,
                )
        self.assertEqual(response.status_code, 500, response.text)
        verification_db = self.Session()
        try:
            self.assertEqual(verification_db.query(DeploymentRollout).count(), before)
        finally:
            verification_db.close()

    def test_10_completed_rollback_audit_failure_restores_durable_aliases(self):
        unique = uuid.uuid4().hex
        artifact = Artifact(
            project_id=self.project.id,
            name=f"rollback-audit-{unique}.onnx",
            type="model",
            storage_path="",
            storage_uri=f"local://rollback-audit/{unique}.onnx",
            file_size=1,
            format="onnx",
        )
        self.db.add(artifact)
        self.db.flush()
        model = RegisteredModel(
            project_id=self.project.id,
            name=f"Rollback Audit {unique}",
            created_by_id=self.users["owner"].id,
        )
        self.db.add(model)
        self.db.flush()
        version = ModelVersion(
            registered_model_id=model.id,
            version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=artifact.id,
            onnx_artifact_id=artifact.id,
            approval_status="approved",
            created_by_id=self.users["owner"].id,
        )
        self.db.add(version)
        self.db.flush()
        deployment = InferenceDeployment(
            project_id=self.project.id,
            name=f"rollback-audit-{uuid.uuid4().hex}",
            model_version_id=version.id,
            desired_state="running",
            observed_state="running",
            created_by_id=self.users["owner"].id,
        )
        self.db.add(deployment)
        self.db.flush()
        previous = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=1,
            strategy="immediate",
            status="superseded",
            created_by_id=self.users["owner"].id,
        )
        durable = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=2,
            strategy="canary",
            status="stable",
            created_by_id=self.users["owner"].id,
        )
        self.db.add_all((previous, durable))
        self.db.flush()
        self.db.add_all((
            DeploymentTarget(
                revision_id=previous.id,
                model_version_id=version.id,
                weight_bps=10000,
                role="stable",
            ),
            DeploymentTarget(
                revision_id=durable.id,
                model_version_id=version.id,
                weight_bps=10000,
                role="candidate",
            ),
        ))
        rollout = DeploymentRollout(
            deployment_id=deployment.id,
            from_revision_id=previous.id,
            to_revision_id=durable.id,
            state="completed",
            current_step=10000,
            lock_version=2,
            step_schedule=[0, 1000, 5000, 10000],
            thresholds={"max_error_rate": 0.01, "max_p95_ms": 500},
        )
        self.db.add(rollout)
        self.db.commit()

        candidate_alias = f"{durable.id}:{version.id}"
        self.runtime.load(deployment.id, {"revision_id": str(durable.id)})
        self.runtime.load(candidate_alias, {"revision_id": str(durable.id)})
        self.as_role("owner")
        with patch.object(self.db, "commit", side_effect=RuntimeError("audit unavailable")):
            with TestClient(self.app, raise_server_exceptions=False) as client:
                response = client.post(
                    f"/api/inference-deployments/{deployment.id}/rollouts/{rollout.id}/rollback",
                    json={"expected_lock_version": rollout.lock_version},
                )

        self.assertEqual(response.status_code, 500, response.text)
        self.assertIn(str(deployment.id), self.runtime.loaded)
        self.assertIn(candidate_alias, self.runtime.loaded)


if __name__ == "__main__":
    unittest.main()
