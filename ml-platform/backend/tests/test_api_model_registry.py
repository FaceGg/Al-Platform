import io
import json
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
from app.models.api_model import PlatformAPI
from app.models.model_library import ModelLibrary
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentRollout,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project
from app.models.training import TrainingJob
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

        def fake_converter(_source, destination, **_kwargs):
            destination.write_bytes(b"converted-onnx")
            return ConversionResult(
                input_names=("features",), output_names=("label", "probabilities"),
                opset=17, sha256="c" * 64, size=destination.stat().st_size,
                converter="test-converter",
                feature_schema=[{"name": "current", "dtype": "float64"}],
                output_schema={"name": "fault", "dtype": "int64", "task": "classification"},
            )

        cls.registry_service = ModelRegistryService(
            artifact_service=cls.artifact_service,
            converter=fake_converter,
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
        # Approval must also enable the lifecycle so the version satisfies the
        # enabled gate used by automatic annotation and deployments.
        self.assertEqual(approved.json()["lifecycle_state"], "enabled")
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
        published = self.db.query(PlatformAPI).filter(
            PlatformAPI.source_kind == "model",
            PlatformAPI.source_id == uuid.UUID(deployment_id),
        ).all()
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].status, "published")
        self.assertEqual(
            published[0].endpoint,
            f"/api/inference-deployments/{deployment_id}/predict",
        )

        repeated = self.client.post(f"/api/inference-deployments/{deployment_id}/start")
        self.assertEqual(repeated.json()["observed_state"], "running")
        self.assertEqual(
            self.db.query(PlatformAPI).filter(
                PlatformAPI.source_kind == "model",
                PlatformAPI.source_id == uuid.UUID(deployment_id),
            ).count(),
            1,
        )
        predicted = self.client.post(
            f"/api/inference-deployments/{deployment_id}/predict",
            json={"records": [{"current": 8.0}]},
        )
        self.assertEqual(predicted.json()["predictions"], [1])
        stopped = self.client.post(f"/api/inference-deployments/{deployment_id}/stop")
        self.assertEqual(stopped.json()["observed_state"], "stopped")
        self.db.expire_all()
        self.assertEqual(
            self.db.query(PlatformAPI).filter(
                PlatformAPI.source_kind == "model",
                PlatformAPI.source_id == uuid.UUID(deployment_id),
            ).one().status,
            "offline",
        )

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
        paths = self.app.openapi()["paths"]
        rollout_operations = paths["/api/inference-deployments/{deployment_id}/rollouts"]
        self.assertIn("get", rollout_operations)
        self.assertIn("post", rollout_operations)
        self.assertNotIn("/api/inference-deployments/{deployment_id}/releases", paths)

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

    def test_11_automl_result_registration_is_atomic_idempotent_and_permissioned(self):
        unique = uuid.uuid4().hex
        job = TrainingJob(
            project_id=self.project.id,
            user_id=self.users["owner"].id,
            name=f"AutoML {unique}",
            status="completed",
        )
        self.db.add(job)
        self.db.flush()
        source_path = Path(self.temporary.name) / f"{job.id}.joblib"
        source_path.write_bytes(b"trusted-joblib")
        artifact = self.artifact_service.create_from_file(
            self.project.id,
            source_path,
            source_path.name,
            "model",
            metadata={
                "source": "automl",
                "training_job_id": str(job.id),
                "best_algorithm": "random_forest",
            },
            commit=False,
        )
        library = ModelLibrary(
            name=f"AutoML source {unique}",
            project_id=self.project.id,
            owner_id=self.users["owner"].id,
            status="completed",
            framework="sklearn",
            backbone="RandomForestClassifier",
            format="joblib",
            training_job_id=job.id,
            model_artifact_id=artifact.id,
        )
        self.db.add(library)
        self.db.flush()
        job.metrics = {
            "algorithm_results": [{
                "algorithm_id": "random_forest",
                "name": "随机森林",
                "status": "completed",
                "model_library_id": str(library.id),
            }],
            "all_results": [{
                "algorithm_id": "random_forest",
                "name": "随机森林",
                "status": "completed",
                "model_library_id": str(library.id),
            }],
        }
        self.db.add(RegisteredModel(
            project_id=self.project.id,
            name=f"{job.name} - 随机森林",
            description="Existing model from another AutoML task",
            created_by_id=self.users["owner"].id,
        ))
        self.db.commit()
        path = f"/api/projects/{self.project.id}/automl-jobs/{job.id}/results/random_forest/register"

        self.as_role("owner")
        first = self.client.post(path)
        second = self.client.post(path)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(first.json()["created"])
        self.assertFalse(second.json()["created"])
        self.assertEqual(
            first.json()["registered_model"]["name"],
            f"{job.name} - 随机森林 [{str(job.id)[:8]}]",
        )
        self.assertEqual(
            first.json()["registered_model"]["id"],
            second.json()["registered_model"]["id"],
        )
        self.assertEqual(
            self.db.query(ModelVersion).filter(ModelVersion.source_model_library_id == library.id).count(),
            1,
        )

        self.as_role("operator")
        self.assertEqual(self.client.post(path).status_code, 403)
        self.as_role("outsider")
        self.assertEqual(self.client.post(path).status_code, 404)

    def test_12_deployment_delete_cleans_marketplace_row(self):
        # 回归：市场里的模型 API 行是部署的派生数据；删除部署必须连带清除，
        # 否则残留指向已删部署的 published 孤儿行（模型 API 在市场无删除入口）。
        self.as_role("editor")
        deployment = self.client.post(
            f"/api/projects/{self.project.id}/inference-deployments",
            json={"name": f"cleanup-{uuid.uuid4().hex[:6]}", "model_version_id": self.version_id},
        )
        self.assertEqual(deployment.status_code, 201, deployment.text)
        deployment_id = deployment.json()["id"]
        started = self.client.post(f"/api/inference-deployments/{deployment_id}/start")
        self.assertEqual(started.json()["observed_state"], "running")
        self.assertGreaterEqual(
            self.db.query(PlatformAPI).filter(
                PlatformAPI.source_kind == "model",
                PlatformAPI.source_id == uuid.UUID(deployment_id),
            ).count(),
            1,
        )
        # 运行中禁止删除
        running_guard = self.client.delete(f"/api/inference-deployments/{deployment_id}")
        self.assertEqual(running_guard.status_code, 409)
        stopped = self.client.post(f"/api/inference-deployments/{deployment_id}/stop")
        self.assertEqual(stopped.json()["observed_state"], "stopped")
        removed = self.client.delete(f"/api/inference-deployments/{deployment_id}")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.db.expire_all()
        self.assertEqual(
            self.db.query(PlatformAPI).filter(
                PlatformAPI.source_kind == "model",
                PlatformAPI.source_id == uuid.UUID(deployment_id),
            ).count(),
            0,
        )


class TestLabelRecalibrateAPI(unittest.TestCase):
    """M6 半监督档 1 API 入口：POST /api/model-versions/{id}/recalibrate-labels。

    覆盖：路由顺序坑（不被 `{action}` 通配吞掉）、happy path（新版本 + 新阈值）、
    门槛 fail-closed 稳定码、非 anomaly 版本拒绝、未知版本/未知数据集 404、
    请求级 feedback 标记落位、挂载替换语义。
    """

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
        cls.user = User(username="m6-api-owner", password_hash="hash")
        cls.db.add(cls.user)
        cls.db.flush()
        cls.project = Project(name="M6 API", owner_id=cls.user.id)
        cls.db.add(cls.project)
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

        def fake_converter(_source, destination, **_kwargs):
            destination.write_bytes(b"converted-onnx")
            return ConversionResult(
                input_names=("features",), output_names=("label", "probabilities"),
                opset=17, sha256="c" * 64, size=destination.stat().st_size,
                converter="test-converter",
                feature_schema=[{"name": "current", "dtype": "float64"}],
                output_schema={"name": "fault", "dtype": "int64", "task": "classification"},
            )

        cls.registry_service = ModelRegistryService(
            artifact_service=cls.artifact_service,
            converter=fake_converter,
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

        cls.router = build_model_registry_router(
            registry_service=cls.registry_service,
            deployment_service=cls.deployment_service,
            session_factory=cls.Session,
        )
        app.include_router(cls.router)

        def override_db():
            yield cls.db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: cls.user
        cls.app = app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.db.close()
        cls.engine.dispose()
        cls.temporary.cleanup()

    def _make_score_stats_artifact(self, unique, threshold=0.1):
        path = Path(self.temporary.name) / f"score-stats-{unique}.json"
        path.write_text(
            json.dumps({"kind": "anomaly_score_stats", "threshold_score": threshold}),
            encoding="utf-8",
        )
        artifact = Artifact(
            project_id=self.project.id, name=path.name, type="report",
            storage_path=str(path), storage_uri="",
            file_size=path.stat().st_size, format="json", metadata_={},
        )
        self.db.add(artifact)
        self.db.flush()
        return artifact

    def _make_bundle_artifact(self, unique):
        """真 joblib bundle（服务在回流行缺分数列时用它补打分）。"""
        import joblib
        from sklearn.ensemble import IsolationForest
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        pipeline = Pipeline([
            ("imputer", StandardScaler()),
            ("detector", IsolationForest(n_estimators=10, random_state=0)),
        ]).fit([[0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 1.0, 1.0]])
        path = Path(self.temporary.name) / f"bundle-{unique}.joblib"
        joblib.dump({
            "model": pipeline,
            "feature_schema": [{"name": f"f{i}", "dtype": "float64"} for i in range(4)],
            "target_schema": [],
            "score_stats": {"threshold_score": 0.1, "contamination": 0.01},
        }, path)
        artifact = Artifact(
            project_id=self.project.id, name=path.name, type="model",
            storage_path=str(path), storage_uri="",
            file_size=path.stat().st_size, format="joblib", metadata_={},
        )
        self.db.add(artifact)
        self.db.flush()
        return artifact

    def _make_source_version(self, *, task="anomaly", approved=True):
        unique = uuid.uuid4().hex[:8]
        bundle = self._make_bundle_artifact(unique)
        stats = self._make_score_stats_artifact(unique)
        model = RegisteredModel(
            project_id=self.project.id, name=f"m6-source-{unique}",
            created_by_id=self.user.id,
        )
        self.db.add(model)
        self.db.flush()
        version = ModelVersion(
            registered_model_id=model.id,
            version_number=1,
            source_kind="onnx_artifact",
            source_model_library_id=None,
            source_artifact_id=bundle.id,
            onnx_artifact_id=bundle.id,
            framework="sklearn",
            algorithm="iforest",
            feature_schema=[{"name": f"f{i}", "dtype": "float64"} for i in range(4)],
            output_schema={"name": "anomaly_score", "dtype": "float64", "task": task},
            metrics={},
            approval_status="approved" if approved else "pending",
            lifecycle_state="enabled" if approved else "pending_review",
            conversion_metadata={"anomaly_score_stats_artifact_id": str(stats.id)},
            created_by_id=self.user.id,
        )
        self.db.add(version)
        self.db.commit()
        return version

    def _make_labeled_dataset(self, *, confirmed=60, false_alarm=30, seed=1, include_feedback=True):
        import numpy as np
        import pandas as pd

        rng = np.random.RandomState(seed)
        rows = []
        for _ in range(confirmed):
            row = {f"f{index}": 8.0 + rng.randn() for index in range(4)}
            row["anomaly_score"] = 5.0
            if include_feedback:
                row["feedback"] = "confirmed_fault"
            rows.append(row)
        for _ in range(false_alarm):
            row = {f"f{index}": rng.randn() for index in range(4)}
            row["anomaly_score"] = -1.0
            if include_feedback:
                row["feedback"] = "false_alarm"
            rows.append(row)
        path = Path(self.temporary.name) / f"labeled-{uuid.uuid4().hex[:8]}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        artifact = Artifact(
            project_id=self.project.id, name=path.name, type="dataset",
            storage_path=str(path), storage_uri="",
            file_size=path.stat().st_size, format="csv", metadata_={},
        )
        self.db.add(artifact)
        self.db.commit()
        return artifact

    def _post(self, version, artifact, **extra):
        payload = {"labeled_artifact_id": str(artifact.id)}
        payload.update(extra)
        return self.client.post(
            f"/api/model-versions/{version.id}/recalibrate-labels",
            json=payload,
        )

    def test_13_route_is_registered_before_wildcard_action_route(self):
        exact = "/api/model-versions/{version_id}/recalibrate-labels"
        wildcard = "/api/model-versions/{version_id}/{action}"
        registered = [route.path for route in self.router.routes]
        self.assertIn(exact, registered)
        self.assertIn(wildcard, registered)
        self.assertLess(registered.index(exact), registered.index(wildcard))
        openapi_paths = list(self.app.openapi()["paths"].keys())
        self.assertLess(openapi_paths.index(exact), openapi_paths.index(wildcard))
        # 实际调用：通配在前会把本路由吞成 LifecycleComment body（422 extra_forbidden）
        version = self._make_source_version()
        artifact = self._make_labeled_dataset()
        response = self._post(version, artifact)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn("detail", response.json())

    def test_26_derive_route_is_registered_before_wildcard_action_route(self):
        """回归锁（2026-11-14 第八轮审计 P0）：派生导出端点曾注册在
        `{action}` 通配路由**之后** → FastAPI 按顺序匹配，通配在前把请求体
        当 LifecycleComment 解析 → 422 extra_forbidden → 端点 100% 不可用。
        同时锁住权限键：project_access.PERMISSIONS 里没有 `model_version.*`
        （那是审计 action 名），写错会被判 403 全角色被拒。"""
        exact = "/api/model-versions/{version_id}/derive-supervised-dataset"
        wildcard = "/api/model-versions/{version_id}/{action}"
        registered = [route.path for route in self.router.routes]
        self.assertIn(exact, registered)
        self.assertEqual(registered.count(exact), 1, "派生端点不得重复注册")
        self.assertLess(registered.index(exact), registered.index(wildcard))
        openapi_paths = list(self.app.openapi()["paths"].keys())
        self.assertLess(openapi_paths.index(exact), openapi_paths.index(wildcard))
        # 权限键必须来自 project_access.PERMISSIONS（否则 audit 判 denied 403）
        from app.services.project_access import PERMISSIONS

        source = Path(__file__).resolve().parents[1] / "app" / "api" / "model_registry.py"
        body = source.read_text(encoding="utf-8")
        for key in ("model_version.approve", "model_version.register"):
            self.assertNotIn(f'permission="{key}"', body, f"{key} 是审计 action 名，不是权限键")
        self.assertIn('permission="model.register"', body)
        self.assertIn("model.register", PERMISSIONS)

    def test_27_derive_endpoint_is_not_swallowed_by_wildcard(self):
        """实际调用：命中自身处理器并真的产出带标签数据集（修复前恒 422
        extra_forbidden——端点 100% 不可用）。"""
        version = self._make_source_version()
        artifact = self._make_labeled_dataset()
        response = self.client.post(
            f"/api/model-versions/{version.id}/derive-supervised-dataset",
            json={"labeled_artifact_id": str(artifact.id)},
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertTrue(body["dataset_artifact_id"])
        self.assertEqual(body["positives"], 60)
        self.assertEqual(body["negatives"], 30)

    def test_14_happy_path_creates_version_with_new_threshold(self):
        version = self._make_source_version()
        artifact = self._make_labeled_dataset(confirmed=60, false_alarm=30, seed=5)
        response = self._post(version, artifact)
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertTrue(body["gate"]["unlocked"])
        self.assertEqual(body["threshold_score"]["old"], 0.1)
        self.assertGreater(body["threshold_score"]["new"], body["threshold_score"]["old"])
        self.assertEqual(body["metrics"]["confirmed_count"], 60)
        self.assertEqual(body["metrics"]["false_alarm_count"], 30)
        self.assertEqual(body["approval_status"], "pending")
        self.assertTrue(body["next_steps"])
        self.assertIn("false_alarm_report", body)
        new_version = self.db.query(ModelVersion).filter(
            ModelVersion.id == uuid.UUID(body["version_id"]),
        ).one()
        self.assertTrue((new_version.conversion_metadata or {}).get("m6_recalibration"))
        self.assertEqual(
            new_version.conversion_metadata["anomaly_score_stats_artifact_id"],
            body["stats_artifact_id"],
        )
        self.assertEqual(new_version.source_artifact_id, version.source_artifact_id)
        self.assertEqual(new_version.output_schema["task"], "anomaly")

    def test_15_gate_not_unlocked_surfaces_stable_code(self):
        version = self._make_source_version()
        artifact = self._make_labeled_dataset(confirmed=30, false_alarm=20)
        response = self._post(version, artifact)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "M6_GATE_NOT_UNLOCKED")

    def test_16_non_anomaly_version_is_rejected(self):
        version = self._make_source_version(task="classification")
        artifact = self._make_labeled_dataset()
        response = self._post(version, artifact)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "RECALIBRATE_REQUIRES_ANOMALY_VERSION",
        )

    def test_17_unknown_version_returns_404(self):
        response = self.client.post(
            f"/api/model-versions/{uuid.uuid4()}/recalibrate-labels",
            json={"labeled_artifact_id": str(uuid.uuid4())},
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"]["code"], "MODEL_VERSION_NOT_FOUND")

    def test_18_unknown_labeled_dataset_returns_404(self):
        version = self._make_source_version()
        response = self.client.post(
            f"/api/model-versions/{version.id}/recalibrate-labels",
            json={"labeled_artifact_id": str(uuid.uuid4())},
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"]["code"], "LABELED_DATASET_NOT_FOUND")

    def test_19_request_feedback_marks_unlock_the_gate(self):
        version = self._make_source_version()
        artifact = self._make_labeled_dataset(include_feedback=False)
        marks = {str(index): "confirmed_fault" for index in range(60)}
        marks.update({str(60 + index): "false_alarm" for index in range(30)})
        response = self._post(version, artifact, feedback_marks=marks)
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertTrue(body["gate"]["unlocked"])
        self.assertEqual(body["metrics"]["confirmed_count"], 60)
        self.assertEqual(body["metrics"]["false_alarm_count"], 30)

    def test_20_request_marks_keep_existing_dataset_labels(self):
        version = self._make_source_version()
        artifact = self._make_labeled_dataset(confirmed=60, false_alarm=30)
        # 只标 1 行为 none：其余标签必须保留（apply_feedback_marks 整列覆盖坑）
        response = self._post(version, artifact, feedback_marks={"0": "none"})
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["metrics"]["confirmed_count"], 59)
        self.assertEqual(body["metrics"]["false_alarm_count"], 30)

    def test_21_mount_replaces_source_version_in_deployment(self):
        version = self._make_source_version()
        artifact = self._make_labeled_dataset()
        deployment = self.client.post(
            f"/api/projects/{self.project.id}/inference-deployments",
            json={
                "name": f"m6-mount-{uuid.uuid4().hex[:6]}",
                "model_version_id": str(version.id),
            },
        )
        self.assertEqual(deployment.status_code, 201, deployment.text)
        deployment_id = deployment.json()["id"]
        response = self._post(version, artifact, mount=True)
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["mount"]["status"], "mounted")
        self.assertEqual(body["mount"]["deployment_id"], deployment_id)
        self.assertEqual(body["mount"]["approval"]["status"], "inherited_from_source")
        self.assertEqual(body["approval_status"], "approved")
        self.db.expire_all()
        row = self.db.query(InferenceDeployment).filter(
            InferenceDeployment.id == uuid.UUID(deployment_id),
        ).one()
        self.assertEqual(str(row.model_version_id), body["version_id"])
        stable = self.db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == row.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        self.assertEqual(
            [str(target.model_version_id) for target in stable.targets],
            [body["version_id"]],
        )

    def test_22_mount_without_deployment_reports_next_steps(self):
        version = self._make_source_version()
        artifact = self._make_labeled_dataset()
        response = self._post(version, artifact, mount=True)
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["mount"]["status"], "not_mounted")
        self.assertEqual(body["mount"]["reason"], "SOURCE_VERSION_NOT_MOUNTED")
        self.assertEqual(body["approval_status"], "pending")
        self.assertTrue(any("approve" in step for step in body["next_steps"]))

    def test_23_operator_cannot_run_label_recalibration(self):
        operator = User(username="m6-api-operator", password_hash="hash")
        self.db.add(operator)
        self.db.flush()
        self.db.add(ProjectMember(
            project_id=self.project.id,
            user_id=operator.id,
            role="operator",
            created_by=self.user.id,
        ))
        self.db.commit()
        version = self._make_source_version()
        artifact = self._make_labeled_dataset()
        self.app.dependency_overrides[get_current_user] = lambda: operator
        try:
            response = self._post(version, artifact)
        finally:
            self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.assertEqual(response.status_code, 403, response.text)

    def _make_deployment(self, version):
        created = self.client.post(
            f"/api/projects/{self.project.id}/inference-deployments",
            json={
                "name": f"fleet-shard-{uuid.uuid4().hex[:6]}",
                "model_version_id": str(version.id),
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()["id"]

    def test_24_fleet_shard_accepts_explicit_condition_column(self):
        """挂载请求可显式声明工况列：服务端据此落 deployment.condition_column
        （不再只能隐式用 device_id），避免挂出永不被路由命中的分片。"""
        deployed = self._make_source_version()
        deployment_id = self._make_deployment(deployed)
        shard_version = self._make_source_version()
        response = self.client.post(
            f"/api/inference-deployments/{deployment_id}/fleet-shards",
            json={
                "model_version_id": str(shard_version.id),
                "condition_value": "ZZQX113",
                "condition_column": "station",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        # 新分片按 model_version_id 定位（targets 列表顺序不保证）
        mounted = next(
            item for item in body["targets"]
            if str(item["model_version_id"]) == str(shard_version.id)
        )
        self.assertEqual(mounted["condition_value"], "ZZQX113")
        self.assertEqual(len(body["targets"]), 2)
        self.db.expire_all()
        row = self.db.query(InferenceDeployment).filter(
            InferenceDeployment.id == uuid.UUID(deployment_id),
        ).one()
        self.assertEqual(row.condition_column, "station")

    def test_25_fleet_shard_rejects_condition_column_mismatch(self):
        """部署已有工况列时，挂载声明不同工况列必须 fail-closed
        （FLEET_SHARD_CONDITION_COLUMN_MISMATCH），不得静默产出不可达分片。"""
        deployed = self._make_source_version()
        deployment_id = self._make_deployment(deployed)
        self.db.expire_all()
        row = self.db.query(InferenceDeployment).filter(
            InferenceDeployment.id == uuid.UUID(deployment_id),
        ).one()
        row.condition_column = "station"
        self.db.commit()
        shard_version = self._make_source_version()
        response = self.client.post(
            f"/api/inference-deployments/{deployment_id}/fleet-shards",
            json={
                "model_version_id": str(shard_version.id),
                "condition_value": "ZZQX113",
                "condition_column": "device_id",
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "FLEET_SHARD_CONDITION_COLUMN_MISMATCH",
        )


if __name__ == "__main__":
    unittest.main()
