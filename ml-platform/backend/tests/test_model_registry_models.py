import unittest

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.artifact import Artifact
from app.models.model_library import ModelLibrary
from app.models.model_registry import (
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project
from app.models.user import User


class TestModelRegistryModels(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.owner = User(username="registry-owner", password_hash="hash")
        self.actor = User(username="registry-editor", password_hash="hash")
        self.db.add_all([self.owner, self.actor])
        self.db.flush()
        self.project = Project(name="Welding registry", owner_id=self.owner.id)
        self.db.add(self.project)
        self.db.flush()
        self.source_artifact = Artifact(
            project_id=self.project.id,
            name="source.joblib",
            type="model",
            storage_path="",
            storage_uri="minio://models/source.joblib",
            format="joblib",
        )
        self.onnx_artifact = Artifact(
            project_id=self.project.id,
            name="model.onnx",
            type="model",
            storage_path="",
            storage_uri="minio://models/model.onnx",
            format="onnx",
        )
        self.library = ModelLibrary(
            name="Training result",
            project_id=self.project.id,
            owner_id=self.owner.id,
            status="completed",
            framework="scikit-learn",
            format="joblib",
        )
        self.db.add_all([
            self.source_artifact,
            self.onnx_artifact,
            self.library,
        ])
        self.db.flush()
        self.model = RegisteredModel(
            project_id=self.project.id,
            name="Weld fault classifier",
            description="Production candidate",
            created_by_id=self.actor.id,
        )
        self.db.add(self.model)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _version(self, number=1, **overrides):
        values = {
            "registered_model_id": self.model.id,
            "version_number": number,
            "source_kind": "platform_joblib",
            "source_model_library_id": self.library.id,
            "source_artifact_id": self.source_artifact.id,
            "onnx_artifact_id": self.onnx_artifact.id,
            "framework": "scikit-learn",
            "algorithm": "LogisticRegression",
            "feature_schema": [
                {"name": "current", "dtype": "float64"},
                {"name": "voltage", "dtype": "float64"},
            ],
            "output_schema": {
                "name": "fault",
                "dtype": "int64",
                "task": "classification",
            },
            "metrics": {"accuracy": 0.95},
            "conversion_metadata": {"opset": 17, "sha256": "a" * 64},
            "approval_status": "pending",
            "created_by_id": self.actor.id,
        }
        values.update(overrides)
        return ModelVersion(**values)

    def test_registered_model_name_is_unique_per_project(self):
        self.db.add(RegisteredModel(
            project_id=self.project.id,
            name=self.model.name,
            created_by_id=self.actor.id,
        ))

        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_version_number_is_unique_per_registered_model(self):
        self.db.add_all([self._version(), self._version()])

        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_platform_source_requires_model_library_reference(self):
        self.db.add(self._version(source_model_library_id=None))

        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_direct_onnx_source_does_not_require_model_library_reference(self):
        version = self._version(
            source_kind="onnx_artifact",
            source_model_library_id=None,
        )
        self.db.add(version)
        self.db.commit()

        self.assertEqual(version.version_number, 1)

    def test_invalid_approval_and_deployment_states_are_rejected(self):
        self.db.add(self._version(approval_status="publishing"))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        version = self._version(approval_status="approved")
        self.db.add(version)
        self.db.flush()
        self.db.add(InferenceDeployment(
            project_id=self.project.id,
            name="primary",
            model_version_id=version.id,
            desired_state="enabled",
            observed_state="running",
            created_by_id=self.actor.id,
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_model_artifacts_cannot_be_deleted_while_version_references_them(self):
        self.db.add(self._version())
        self.db.commit()

        self.db.delete(self.onnx_artifact)
        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_actor_deletion_preserves_registry_history_with_null_actor(self):
        version = self._version()
        self.db.add(version)
        self.db.commit()
        self.db.delete(self.actor)
        self.db.commit()
        self.db.expire_all()

        preserved_model = self.db.query(RegisteredModel).filter_by(
            id=self.model.id,
        ).one()
        preserved_version = self.db.query(ModelVersion).filter_by(
            id=version.id,
        ).one()
        self.assertIsNone(preserved_model.created_by_id)
        self.assertIsNone(preserved_version.created_by_id)

    def test_project_deletion_cascades_registry_and_deployments(self):
        version = self._version(approval_status="approved")
        self.db.add(version)
        self.db.flush()
        deployment = InferenceDeployment(
            project_id=self.project.id,
            name="primary",
            model_version_id=version.id,
            desired_state="stopped",
            observed_state="stopped",
            created_by_id=self.actor.id,
        )
        self.db.add(deployment)
        self.db.commit()

        self.db.delete(self.project)
        self.db.commit()

        self.assertEqual(self.db.query(RegisteredModel).count(), 0)
        self.assertEqual(self.db.query(ModelVersion).count(), 0)
        self.assertEqual(self.db.query(InferenceDeployment).count(), 0)

    def test_registry_query_indexes_are_present(self):
        inspector = inspect(self.engine)
        self.assertIn(
            "ix_registered_models_project_created",
            {item["name"] for item in inspector.get_indexes("registered_models")},
        )
        self.assertIn(
            "ix_model_versions_model_created",
            {item["name"] for item in inspector.get_indexes("model_versions")},
        )
        self.assertIn(
            "ix_inference_deployments_project_state",
            {
                item["name"]
                for item in inspector.get_indexes("inference_deployments")
            },
        )


if __name__ == "__main__":
    unittest.main()
