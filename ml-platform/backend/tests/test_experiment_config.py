import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.config import Settings


class TestExperimentConfiguration(unittest.TestCase):
    @staticmethod
    def production_values(**overrides):
        values = {
            "app_mode": "production",
            "database_url": "postgresql+psycopg://app:password@db/ml_platform",
            "secret_key": "s" * 32,
            "task_backend": "celery",
            "celery_broker_url": "redis://redis:6379/0",
            "redis_events_url": "redis://redis:6379/1",
            "artifact_storage_backend": "minio",
            "minio_endpoint": "minio:9000",
            "minio_access_key": "access-key",
            "minio_secret_key": "secret-key",
            "mlflow_tracking_uri": "http://mlflow:5000",
            "mlflow_backend_store_uri": "postgresql+psycopg://mlflow:password@db/mlflow",
            "mlflow_artifact_root": "s3://ml-platform/mlflow",
            "tensorboard_gateway_url": "http://tensorboard-gateway:6006",
            "tensorboard_session_secret": "t" * 32,
        }
        values.update(overrides)
        return values

    def test_local_defaults_do_not_require_tracking_services(self):
        with patch.dict("os.environ", {}, clear=True):
            configured = Settings(_env_file=None)

        self.assertIsNone(configured.mlflow_tracking_uri)
        self.assertIsNone(configured.tensorboard_gateway_url)
        self.assertEqual(configured.training_checkpoint_interval_epochs, 5)
        self.assertEqual(configured.training_stale_after_seconds, 300)
        self.assertEqual(configured.tensorboard_session_ttl_seconds, 300)
        self.assertEqual(configured.tensorboard_idle_timeout_seconds, 600)

    def test_production_requires_mlflow_tracking_uri(self):
        with self.assertRaisesRegex(ValidationError, "MLFLOW_TRACKING_URI"):
            Settings(**self.production_values(mlflow_tracking_uri=None))

    def test_production_requires_mlflow_backend_store_uri(self):
        with self.assertRaisesRegex(ValidationError, "MLFLOW_BACKEND_STORE_URI"):
            Settings(**self.production_values(mlflow_backend_store_uri=None))

    def test_production_requires_mlflow_artifact_root(self):
        with self.assertRaisesRegex(ValidationError, "MLFLOW_ARTIFACT_ROOT"):
            Settings(**self.production_values(mlflow_artifact_root="  "))

    def test_production_requires_tensorboard_gateway_and_secret(self):
        with self.assertRaisesRegex(ValidationError, "TENSORBOARD_GATEWAY_URL"):
            Settings(**self.production_values(tensorboard_gateway_url=None))
        with self.assertRaisesRegex(ValidationError, "TENSORBOARD_SESSION_SECRET"):
            Settings(**self.production_values(tensorboard_session_secret=None))

    def test_tensorboard_secret_file_is_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            secret_file = Path(directory) / "tensorboard-session"
            secret_file.write_text("f" * 32 + "\n", encoding="utf-8")
            values = self.production_values(
                tensorboard_session_secret=None,
                tensorboard_session_secret_file=str(secret_file),
            )
            configured = Settings(**values)

        self.assertEqual(
            configured.resolved_tensorboard_session_secret.get_secret_value(),
            "f" * 32,
        )

    def test_complete_production_tracking_configuration_is_redacted(self):
        configured = Settings(**self.production_values())
        rendered = " ".join((
            repr(configured),
            json.dumps(configured.model_dump(mode="json")),
            repr(configured.safe_summary()),
        ))

        self.assertEqual(configured.safe_summary()["mlflow_tracking_uri"], "http://mlflow:5000")
        self.assertTrue(configured.safe_summary()["mlflow_backend_store_configured"])
        self.assertTrue(configured.safe_summary()["tensorboard_session_secret_configured"])
        for secret in ("password", "t" * 32):
            self.assertNotIn(secret, rendered)


if __name__ == "__main__":
    unittest.main()
