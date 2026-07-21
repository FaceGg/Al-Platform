import unittest

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.artifact import Artifact
from app.models.model_registry import (
    REVISION_STATES,
    REVISION_STRATEGIES,
    ROLLOUT_STATES,
    DeploymentRevision,
    DeploymentRollout,
    DeploymentTarget,
    InferenceApiKey,
    InferenceMetricBucket,
    InferenceRequestLog,
    InferenceDeployment,
    ModelCard,
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

    def test_production_inference_state_constants_are_frozen(self):
        self.assertEqual(
            REVISION_STRATEGIES,
            ("immediate", "canary", "rolling"),
        )
        self.assertEqual(
            REVISION_STATES,
            ("draft", "candidate", "stable", "superseded", "failed"),
        )
        self.assertEqual(
            ROLLOUT_STATES,
            (
                "pending",
                "preloading",
                "progressing",
                "paused",
                "completed",
                "failed",
                "rolled_back",
            ),
        )

    def test_revision_strategy_status_and_positive_number_are_enforced(self):
        self.db.add(DeploymentRevision(
            deployment_id=self.deployment.id,
            revision_number=0,
            strategy="blue_green",
            status="publishing",
            created_by_id=self.user.id,
        ))
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

    def test_target_model_is_unique_per_revision_and_role_is_frozen(self):
        revision = self.make_revision()
        self.db.add_all([
            DeploymentTarget(
                revision_id=revision.id,
                model_version_id=self.deployment.model_version_id,
                weight_bps=5000,
                role="stable",
            ),
            DeploymentTarget(
                revision_id=revision.id,
                model_version_id=self.deployment.model_version_id,
                weight_bps=5000,
                role="candidate",
            ),
        ])
        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_only_one_active_rollout_exists_per_deployment(self):
        revision = self.make_revision()
        self.db.add_all([
            DeploymentRollout(
                deployment_id=self.deployment.id,
                from_revision_id=revision.id,
                to_revision_id=revision.id,
                state="pending",
            ),
            DeploymentRollout(
                deployment_id=self.deployment.id,
                from_revision_id=revision.id,
                to_revision_id=revision.id,
                state="paused",
            ),
        ])
        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_api_key_schema_never_persists_plaintext(self):
        api_key_columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("inference_api_keys")
        }
        self.assertEqual(api_key_columns, {
            "id",
            "deployment_id",
            "prefix",
            "secret_hash",
            "scopes",
            "expires_at",
            "revoked_at",
            "last_used_at",
            "created_by_id",
            "created_at",
        })
        self.assertNotIn("raw_secret", api_key_columns)
        self.assertNotIn("secret_value", api_key_columns)
        self.assertNotIn("encrypted_secret", api_key_columns)
        self.assertNotIn("plaintext", api_key_columns)

    def test_api_key_prefix_must_be_exactly_twelve_characters(self):
        self.db.add(InferenceApiKey(
            deployment_id=self.deployment.id,
            prefix="too-short",
            secret_hash="pbkdf2_sha256$fixture",
            scopes=["inference.predict"],
            created_by_id=self.user.id,
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()

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

    def test_request_log_status_requires_explicit_domain_outcome(self):
        column = InferenceRequestLog.__table__.c.status
        self.assertIsNone(column.default)
        self.assertIsNone(column.server_default)
        self.assertFalse(column.nullable)

    def test_model_card_has_one_safe_snapshot_per_model_version(self):
        card_columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("model_cards")
        }
        self.assertEqual(card_columns, {
            "id",
            "model_version_id",
            "training_data_lineage",
            "source_artifact_ids",
            "input_schema",
            "output_schema",
            "metrics",
            "approval_history",
            "approval_status",
            "release_status",
            "risk_notes",
            "intended_use",
            "limitations",
            "operational_guidance",
            "guidance_revision",
            "created_at",
            "updated_at",
        })
        self.db.add_all([
            ModelCard(model_version_id=self.deployment.model_version_id),
            ModelCard(model_version_id=self.deployment.model_version_id),
        ])
        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_all_week9_models_are_publicly_exported(self):
        from app import models

        expected = {
            "DeploymentRevision",
            "DeploymentTarget",
            "DeploymentRollout",
            "InferenceApiKey",
            "InferenceRequestLog",
            "InferenceMetricBucket",
            "ModelCard",
        }
        self.assertTrue(expected.issubset(set(models.__all__)))


if __name__ == "__main__":
    unittest.main()
