import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr, ValidationError

from app.config import Settings, settings


class TestSettings(unittest.TestCase):
    def production_values(self, **overrides):
        values = {
            "app_mode": "production",
            "database_url": "postgresql+psycopg://app:db-password@db/ml_platform",
            "secret_key": "j" * 32,
            "task_backend": "celery",
            "celery_broker_url": "redis://:broker-password@redis:6379/0",
            "redis_events_url": "redis://:events-password@redis:6379/1",
            "artifact_storage_backend": "minio",
            "minio_endpoint": "minio:9000",
            "minio_access_key": "minio-access-value",
            "minio_secret_key": "minio-secret-value",
        }
        values.update(overrides)
        return values

    def test_local_defaults_load_without_external_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            local_settings = Settings(_env_file=None)

        self.assertEqual(local_settings.app_mode, "local")
        self.assertEqual(local_settings.database_url, "sqlite:///./ml_platform.db")
        self.assertEqual(local_settings.task_backend, "local")
        self.assertEqual(local_settings.artifact_storage_backend, "local")
        self.assertIsInstance(local_settings.secret_key, SecretStr)
        self.assertIsInstance(settings, Settings)
        self.assertGreater(local_settings.database_pool_size, 0)
        self.assertGreater(local_settings.database_max_overflow, 0)
        self.assertGreater(local_settings.database_pool_timeout_seconds, 0)
        self.assertGreater(
            local_settings.task_hard_timeout_seconds,
            local_settings.task_soft_timeout_seconds,
        )

    def test_production_rejects_sqlite(self):
        with self.assertRaisesRegex(ValidationError, "PostgreSQL"):
            Settings(**self.production_values(database_url="sqlite:///bad.db"))

    def test_production_rejects_malformed_postgresql_url(self):
        with self.assertRaisesRegex(ValidationError, "PostgreSQL"):
            Settings(
                **self.production_values(database_url="postgresql:not-a-url")
            )

    def test_production_rejects_incomplete_postgresql_urls(self):
        invalid_urls = (
            "postgresql://",
            "postgresql:///ml_platform",
            "postgresql://db-host/   ",
            "postgresql://bad host/ml_platform",
            "postgresql+psycopg://db-host/db name",
        )
        for database_url in invalid_urls:
            with self.subTest(database_url=database_url):
                with self.assertRaisesRegex(ValidationError, "PostgreSQL"):
                    Settings(**self.production_values(database_url=database_url))

    def test_production_accepts_postgresql_unix_socket_url(self):
        socket_settings = Settings(
            **self.production_values(
                database_url=(
                    "postgresql+psycopg:///ml_platform"
                    "?host=/var/run/postgresql"
                )
            )
        )

        self.assertEqual(socket_settings.app_mode, "production")

    def test_production_rejects_empty_minio_bucket(self):
        with self.assertRaisesRegex(ValidationError, "MINIO_BUCKET"):
            Settings(**self.production_values(minio_bucket="   "))

    def test_complete_production_configuration_passes(self):
        production_settings = Settings(**self.production_values())

        self.assertEqual(production_settings.app_mode, "production")
        self.assertEqual(production_settings.task_backend, "celery")
        self.assertEqual(production_settings.artifact_storage_backend, "minio")
        self.assertEqual(
            production_settings.resolved_secret_key.get_secret_value(),
            "j" * 32,
        )

    def test_secret_files_are_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jwt_file = root / "jwt"
            access_file = root / "minio-access"
            secret_file = root / "minio-secret"
            jwt_file.write_text("f" * 32 + "\n", encoding="utf-8")
            access_file.write_text("file-access\n", encoding="utf-8")
            secret_file.write_text("file-secret\n", encoding="utf-8")

            file_settings = Settings(
                secret_key_file=str(jwt_file),
                minio_access_key_file=str(access_file),
                minio_secret_key_file=str(secret_file),
            )

        self.assertEqual(
            file_settings.resolved_secret_key.get_secret_value(), "f" * 32
        )
        self.assertEqual(
            file_settings.resolved_minio_access_key.get_secret_value(), "file-access"
        )
        self.assertEqual(
            file_settings.resolved_minio_secret_key.get_secret_value(), "file-secret"
        )

    def test_direct_value_and_file_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            secret_file = Path(directory) / "jwt"
            secret_file.write_text("f" * 32, encoding="utf-8")

            with self.assertRaisesRegex(ValidationError, "SECRET_KEY.*SECRET_KEY_FILE"):
                Settings(secret_key="v" * 32, secret_key_file=str(secret_file))

    def test_empty_secret_file_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            secret_file = Path(directory) / "minio-secret"
            secret_file.write_text("  \n", encoding="utf-8")

            with self.assertRaisesRegex(ValidationError, "must not be empty"):
                Settings(minio_secret_key_file=str(secret_file))

    def test_safe_summary_and_repr_do_not_leak_secrets(self):
        secret_values = (
            "db-password",
            "j" * 32,
            "broker-password",
            "events-password",
            "minio-access-value",
            "minio-secret-value",
            "legacy-llm-secret",
        )
        protected_settings = Settings(
            **self.production_values(),
            llm_api_key="legacy-llm-secret",
        )
        rendered = repr(protected_settings)
        summary = repr(protected_settings.safe_summary())

        for secret_value in secret_values:
            self.assertNotIn(secret_value, rendered)
            self.assertNotIn(secret_value, summary)

    def test_standard_dump_and_json_do_not_leak_secrets(self):
        protected_settings = Settings(
            **self.production_values(
                minio_endpoint=(
                    "https://minio-user:minio-url-password@minio:9000"
                    "/storage?token=minio-query-token"
                )
            ),
            llm_api_url=(
                "https://llm-user:llm-url-password@llm.example/v1/chat"
                "?api_key=llm-query-token"
            ),
            llm_api_key="legacy-llm-secret",
        )

        rendered_values = (
            repr(protected_settings),
            json.dumps(protected_settings.model_dump(), default=str),
            json.dumps(protected_settings.model_dump(mode="json")),
            protected_settings.model_dump_json(),
        )
        for secret_value in (
            "db-password",
            "j" * 32,
            "broker-password",
            "events-password",
            "minio-secret-value",
            "legacy-llm-secret",
            "minio-url-password",
            "minio-query-token",
            "llm-url-password",
            "llm-query-token",
        ):
            for rendered in rendered_values:
                self.assertNotIn(secret_value, rendered)

    def test_safe_summary_removes_url_credentials_and_metadata(self):
        protected_settings = Settings(
            **self.production_values(
                minio_endpoint=(
                    "https://minio-user:minio-password@minio:9000"
                    "/storage?token=minio-token#private"
                )
            ),
            llm_api_url=(
                "https://llm-user:llm-password@llm.example/v1/chat"
                "?api_key=llm-token#private"
            ),
        )

        summary = protected_settings.safe_summary()

        self.assertEqual(summary["minio_endpoint"], "https://minio:9000/storage")
        self.assertEqual(summary["llm_api_url"], "https://llm.example/v1/chat")

    def test_validation_errors_hide_sensitive_inputs(self):
        sensitive_values = self.production_values(
            database_url=(
                "postgresql+psycopg://app:validation-db-secret@bad host/ml_platform"
            ),
            secret_key="validation-jwt-secret-value-1234567890",
            celery_broker_url="redis://:validation-redis-secret@redis:6379/0",
            minio_secret_key="validation-minio-secret",
        )

        with self.assertRaises(ValidationError) as context:
            Settings(**sensitive_values)

        rendered_values = (
            str(context.exception),
            repr(context.exception.errors()),
            context.exception.json(),
        )
        for secret_value in (
            "validation-db-secret",
            "validation-jwt-secret-value-1234567890",
            "validation-redis-secret",
            "validation-minio-secret",
        ):
            for rendered in rendered_values:
                self.assertNotIn(secret_value, rendered)

    def test_env_example_does_not_define_a_usable_known_jwt_secret(self):
        env_example = (Path(__file__).parents[1] / ".env.example").read_text(
            encoding="utf-8"
        )
        configured_secrets = [
            line.partition("=")[2].strip()
            for line in env_example.splitlines()
            if line.startswith("SECRET_KEY=")
        ]

        self.assertTrue(all(not secret for secret in configured_secrets))
        self.assertIn("# SECRET_KEY_FILE=", env_example)

    def test_production_rejects_hard_timeout_not_greater_than_soft_timeout(self):
        with self.assertRaisesRegex(ValidationError, "hard timeout.*soft timeout"):
            Settings(
                **self.production_values(),
                task_soft_timeout_seconds=60,
                task_hard_timeout_seconds=60,
            )

    def test_secret_key_is_plain_secretstr_not_string_subclass(self):
        compatible_settings = Settings(secret_key="z" * 32, _env_file=None)

        self.assertIs(type(compatible_settings.secret_key), SecretStr)
        self.assertNotIsInstance(compatible_settings.secret_key, str)


if __name__ == "__main__":
    unittest.main()
