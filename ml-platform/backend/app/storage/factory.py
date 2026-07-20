"""Artifact storage construction from application settings."""

from pathlib import Path

from app.storage.base import ArtifactStorage, StorageError
from app.storage.local import LocalStorage
from app.storage.minio import MinioStorage


def create_artifact_storage(settings) -> ArtifactStorage:
    if settings.artifact_storage_backend == "local":
        return LocalStorage(Path(settings.artifact_storage_dir))
    if settings.artifact_storage_backend == "minio":
        return MinioStorage.from_settings(settings)
    raise StorageError("Unsupported artifact storage backend")
