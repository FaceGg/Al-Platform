import unittest

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.artifact import Artifact
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentTarget,
    InferenceApiKey,
    InferenceMetricBucket,
    InferenceRequestLog,
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project
from app.models.user import User


class TestInferenceProductionModels(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.user = User(username="production-model-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Production inference", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        artifact = Artifact(
            project_id=self.project.id,
            name="model.onnx",
            type="model",
            storage_path="",
            storage_uri="s3://models/model.onnx",
            file_size=12,
            format="onnx",
            metadata_={"sha256": "a" * 64},
        )
        self.db.add(artifact)
        self.db.flush()
        registered = RegisteredModel(
            project_id=self.project.id,
            name="Fault classifier",
            created_by_id=self.user.id,
        )
        self.db.add(registered)
        self.db.flush()
        version = ModelVersion(
            registered_model_id=registered.id,
            version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=artifact.id,
            onnx_artifact_id=artifact.id,
            framework="onnx",
            algorithm="classifier",
            feature_schema=[{"name": "current", "dtype": "float64"}],
            output_schema={"name": "fault", "dtype": "int64"},
            metrics={"accuracy": 0.95},
            conversion_metadata={"sha256": "a" * 64},
            approval_status="approved",
            created_by_id=self.user.id,
        )
        self.db.add(version)
        self.db.flush()
        self.deployment = InferenceDeployment(
            project_id=self.project.id,
            name="primary",
            model_version_id=version.id,
            created_by_id=self.user.id,
        )
        self.db.add(self.deployment)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def make_revision(self, number=1, flush=True):
        revision = DeploymentRevision(
            deployment_id=self.deployment.id,
            revision_number=number,
            strategy="immediate",
            status="draft",
            created_by_id=self.user.id,
        )
        self.db.add(revision)
        if flush:
            self.db.flush()
        return revision

    def test_revision_number_is_unique_per_deployment(self):
        self.make_revision(flush=False)
        self.make_revision(flush=False)
        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_target_weight_range_is_enforced_by_database(self):
        revision = self.make_revision()
        self.db.add(DeploymentTarget(
            revision_id=revision.id,
            model_version_id=self.deployment.model_version_id,
            weight_bps=10001,
            role="stable",
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_api_key_schema_never_persists_plaintext(self):
        api_key_columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("inference_api_keys")
        }
        self.assertNotIn("secret", api_key_columns)
        self.assertNotIn("plaintext", api_key_columns)

    def test_request_log_columns_are_an_exact_safe_allowlist(self):
        request_columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("inference_request_logs")
        }
        self.assertEqual(request_columns, {
            "id",
            "request_id",
            "deployment_id",
            "revision_id",
            "model_version_id",
            "api_key_id",
            "batch_size",
            "duration_ms",
            "status",
            "error_code",
            "occurred_at",
            "expires_at",
        })

    def test_metric_buckets_are_indexed_by_deployment_and_minute(self):
        indexes = inspect(self.engine).get_indexes("inference_metric_buckets")
        indexed_columns = {
            tuple(index.get("column_names", [])) for index in indexes
        }
        self.assertIn(("deployment_id", "bucket_start"), indexed_columns)


if __name__ == "__main__":
    unittest.main()
