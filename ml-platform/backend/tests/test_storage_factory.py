"""Tests for app.storage.factory.create_artifact_storage.

The factory branches on settings.artifact_storage_backend and constructs
either LocalStorage or MinioStorage. Previously untested.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, ".")

from app.storage.base import StorageError
from app.storage.factory import create_artifact_storage
from app.storage.local import LocalStorage
from app.storage.minio import MinioStorage


class TestCreateArtifactStorageLocal(unittest.TestCase):
    def test_returns_local_storage_for_local_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = SimpleNamespace(
                artifact_storage_backend="local",
                artifact_storage_dir=tmp,
            )
            storage = create_artifact_storage(settings)
            self.assertIsInstance(storage, LocalStorage)
            self.assertEqual(Path(tmp).resolve(), storage.base_dir)

    def test_local_storage_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "nested" / "store"
            settings = SimpleNamespace(
                artifact_storage_backend="local",
                artifact_storage_dir=str(nested),
            )
            storage = create_artifact_storage(settings)
            self.assertTrue(storage.base_dir.is_dir())


class TestCreateArtifactStorageMinio(unittest.TestCase):
    def _minio_settings(self, **overrides):
        base = dict(
            artifact_storage_backend="minio",
            artifact_storage_dir="./ignored",
            minio_endpoint="localhost:9000",
            minio_bucket="ml-platform",
            minio_secure=False,
            resolved_minio_access_key=None,
            resolved_minio_secret_key=None,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_returns_minio_storage_when_configured(self):
        from pydantic import SecretStr

        settings = self._minio_settings(
            resolved_minio_access_key=SecretStr("access"),
            resolved_minio_secret_key=SecretStr("secret"),
        )
        storage = create_artifact_storage(settings)
        self.assertIsInstance(storage, MinioStorage)
        self.assertEqual(storage.bucket, "ml-platform")

    def test_raises_when_minio_credentials_missing(self):
        settings = self._minio_settings()  # no credentials
        with self.assertRaises(StorageError):
            create_artifact_storage(settings)


class TestCreateArtifactStorageUnknownBackend(unittest.TestCase):
    def test_raises_storage_error_for_unknown_backend(self):
        settings = SimpleNamespace(
            artifact_storage_backend="s3",
            artifact_storage_dir="./store",
        )
        with self.assertRaises(StorageError):
            create_artifact_storage(settings)


if __name__ == "__main__":
    unittest.main()
