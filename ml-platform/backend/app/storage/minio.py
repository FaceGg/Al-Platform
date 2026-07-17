"""MinIO-backed artifact storage."""

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator
from urllib.parse import quote, unquote, urlsplit

from minio import Minio

from app.storage.base import (
    StorageError,
    StoredObject,
    stream_integrity,
    validate_key_segment,
)


class MinioStorage:
    def __init__(self, client, bucket: str, *, temp_root: Path | None = None):
        self.client = client
        self.bucket = validate_key_segment(bucket, "bucket")
        configured_temp = os.getenv("ML_PLATFORM_TEMP_DIR")
        root = temp_root or (Path(configured_temp) if configured_temp else Path(tempfile.gettempdir()))
        self.temp_root = root.expanduser().resolve() / "artifact-cache"
        self.temp_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_settings(cls, settings) -> "MinioStorage":
        access_key = settings.resolved_minio_access_key
        secret_key = settings.resolved_minio_secret_key
        if access_key is None or secret_key is None or not settings.minio_endpoint:
            raise StorageError("MinIO configuration is incomplete")
        client = Minio(
            settings.minio_endpoint,
            access_key=access_key.get_secret_value(),
            secret_key=secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )
        return cls(client, settings.minio_bucket)

    def put(
        self,
        source: Path,
        project_id: str,
        artifact_id: str,
        filename: str,
    ) -> StoredObject:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise StorageError("Artifact source file does not exist")
        key = self._key(project_id, artifact_id, filename)
        size = source.stat().st_size
        with source.open("rb") as stream:
            sha256, measured_size = stream_integrity(stream)
            stream.seek(0)
            try:
                self.client.put_object(self.bucket, key, stream, size)
            except Exception as error:
                self._compensate_delete(key)
                raise StorageError("Could not store MinIO artifact") from error
        if measured_size != size:
            self._compensate_delete(key)
            raise StorageError("Artifact changed while it was being uploaded")
        return StoredObject(
            uri=f"s3://{self.bucket}/{quote(key, safe='/')}",
            size=size,
            sha256=sha256,
        )

    def open(self, uri: str) -> BinaryIO:
        bucket, key = self._parse_uri(uri)
        try:
            return self.client.get_object(bucket, key)
        except Exception as error:
            raise StorageError("Could not open MinIO artifact") from error

    @contextmanager
    def materialize(self, uri: str) -> Iterator[Path]:
        _, key = self._parse_uri(uri)
        suffix = Path(key).suffix
        directory = Path(tempfile.mkdtemp(dir=self.temp_root))
        target = directory / f"artifact{suffix}"
        response = None
        try:
            response = self.open(uri)
            with target.open("xb") as output:
                shutil.copyfileobj(response, output, 1024 * 1024)
            yield target
        except StorageError:
            raise
        except Exception as error:
            raise StorageError("Could not materialize MinIO artifact") from error
        finally:
            if response is not None:
                response.close()
                release = getattr(response, "release_conn", None)
                if release is not None:
                    release()
            shutil.rmtree(directory, ignore_errors=True)

    def exists(self, uri: str) -> bool:
        bucket, key = self._parse_uri(uri)
        try:
            self.client.stat_object(bucket, key)
        except Exception:
            return False
        return True

    def delete(self, uri: str) -> None:
        bucket, key = self._parse_uri(uri)
        try:
            self.client.remove_object(bucket, key)
        except Exception as error:
            raise StorageError("Could not delete MinIO artifact") from error

    def verify(self, uri: str, sha256: str, size: int) -> bool:
        response = None
        try:
            response = self.open(uri)
            actual_sha256, actual_size = stream_integrity(response)
        except StorageError:
            return False
        finally:
            if response is not None:
                response.close()
                release = getattr(response, "release_conn", None)
                if release is not None:
                    release()
        return actual_sha256 == sha256 and actual_size == size

    def _key(self, project_id: str, artifact_id: str, filename: str) -> str:
        return "/".join(
            (
                "projects",
                validate_key_segment(str(project_id), "project_id"),
                "artifacts",
                validate_key_segment(str(artifact_id), "artifact_id"),
                validate_key_segment(filename, "filename"),
            )
        )

    def _parse_uri(self, uri: str) -> tuple[str, str]:
        parsed = urlsplit(uri)
        key = unquote(parsed.path.lstrip("/"))
        if parsed.scheme != "s3" or parsed.netloc != self.bucket or not key:
            raise StorageError("Invalid MinIO artifact URI")
        parts = key.split("/")
        if len(parts) != 5 or parts[0] != "projects" or parts[2] != "artifacts":
            raise StorageError("Invalid MinIO artifact key")
        for index, part in enumerate(parts):
            validate_key_segment(part, f"key segment {index}")
        return parsed.netloc, key

    def _compensate_delete(self, key: str) -> None:
        try:
            self.client.remove_object(self.bucket, key)
        except Exception:
            pass
