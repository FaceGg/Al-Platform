"""Deployment-reference binding tests (AutoML Agent plan, Task A3.2a).

Contract under test (spec v0.9 §12.2/§12.3): a serving graph bound to a
deployment resolves the deployment's CURRENT joblib artifact at invoke time —
so closed-loop retrain swaps (which rotate ``deployments.model_version_id``)
are followed without republishing.
"""

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import joblib  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.model_library import ModelLibrary  # noqa: E402
from app.models.model_registry import (  # noqa: E402
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.artifact_service import build_artifact_service  # noqa: E402
from app.services.agent.serving_binding import (  # noqa: E402
    resolve_deployment_model_artifact,
)
from tests.auth_test_support import ensure_admin  # noqa: E402

Base.metadata.create_all(bind=engine)


class TestServingBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.username == "admin").one()
            project = Project(name="bind-%s" % uuid4().hex[:8], owner_id=admin.id)
            db.add(project)
            db.flush()
            service = build_artifact_service(db)

            def make_artifact(label: str) -> str:
                model = LogisticRegression().fit(
                    [[0.0], [0.1], [5.0], [5.1]], [0, 0, 1, 1]
                )
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / (label + ".joblib")
                    joblib.dump(model, path)
                    artifact = service.create_from_file(
                        project.id, path, label, "model"
                    )
                return str(artifact.id)

            cls.artifact_v1 = make_artifact("bind-v1-" + uuid4().hex[:6])
            cls.artifact_v2 = make_artifact("bind-v2-" + uuid4().hex[:6])

            registered = RegisteredModel(
                project_id=project.id, name="bind-model-%s" % uuid4().hex[:6],
                created_by_id=admin.id,
            )
            db.add(registered)
            db.flush()

            def make_library(artifact_id: str) -> ModelLibrary:
                return ModelLibrary(
                    name="bind-lib-%s" % uuid4().hex[:6],
                    project_id=project.id,
                    owner_id=admin.id,
                    status="completed",
                    framework="sklearn",
                    model_artifact_id=uuid.UUID(artifact_id),
                    file_size=1,
                    format="joblib",
                )

            library_v1 = make_library(cls.artifact_v1)
            db.add(library_v1)
            db.flush()
            version_v1 = ModelVersion(
                registered_model_id=registered.id,
                version_number=1,
                source_kind="platform_joblib",
                source_artifact_id=uuid.UUID(cls.artifact_v1),
                onnx_artifact_id=uuid.UUID(cls.artifact_v1),
                approval_status="approved",
                source_model_library_id=library_v1.id,
                created_by_id=admin.id,
            )
            db.add(version_v1)
            db.flush()
            deployment = InferenceDeployment(
                project_id=project.id,
                name="bind-deploy-%s" % uuid4().hex[:6],
                model_version_id=version_v1.id,
                created_by_id=admin.id,
            )
            db.add(deployment)
            db.commit()

            cls.project_id = project.id
            cls.deployment_id = deployment.id
            cls.registered_id = registered.id
            cls.admin_id = admin.id
        finally:
            db.close()

    def _service(self, db):
        return build_artifact_service(db)

    def test_resolves_current_version_artifact(self):
        with SessionLocal() as db:
            resolved = resolve_deployment_model_artifact(
                self._service(db), self.project_id, str(self.deployment_id)
            )
        self.assertEqual(resolved, self.artifact_v1)

    def test_resolves_follows_retrain_swap(self):
        # Simulate complete_retrain_swap: rotate deployment.model_version_id
        # to a new approved version; the binding must follow without changes.
        with SessionLocal() as db:
            library_v2 = ModelLibrary(
                name="bind-lib-%s" % uuid4().hex[:6],
                project_id=self.project_id,
                owner_id=self.admin_id,
                status="completed",
                framework="sklearn",
                model_artifact_id=uuid.UUID(self.artifact_v2),
                file_size=1,
                format="joblib",
            )
            db.add(library_v2)
            db.flush()
            version_v2 = ModelVersion(
                registered_model_id=self.registered_id,
                version_number=2,
                source_kind="platform_joblib",
                source_artifact_id=uuid.UUID(self.artifact_v2),
                onnx_artifact_id=uuid.UUID(self.artifact_v2),
                approval_status="approved",
                source_model_library_id=library_v2.id,
                created_by_id=self.admin_id,
            )
            db.add(version_v2)
            db.flush()
            deployment = db.get(InferenceDeployment, self.deployment_id)
            deployment.model_version_id = version_v2.id
            db.commit()
            resolved = resolve_deployment_model_artifact(
                self._service(db), self.project_id, str(self.deployment_id)
            )
        self.assertEqual(resolved, self.artifact_v2)

    def test_unknown_deployment_raises(self):
        from app.services.artifact_service import build_artifact_service

        with SessionLocal() as db:
            with self.assertRaises(RuntimeError):
                resolve_deployment_model_artifact(
                    build_artifact_service(db), self.project_id, str(uuid4())
                )
