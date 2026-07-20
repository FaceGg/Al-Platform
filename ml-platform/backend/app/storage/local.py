"""Filesystem-backed artifact storage."""

import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from app.storage.base import (
    StorageError,
    StoredObject,
    stream_integrity,
    validate_key_segment,
)


class LocalStorage:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.expanduser().resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

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

        segments = (
            validate_key_segment(str(project_id), "project_id"),
            validate_key_segment(str(artifact_id), "artifact_id"),
            validate_key_segment(filename, "filename"),
        )
        target = self._require_contained(self.base_dir.joinpath(*segments))
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
            with temporary.open("rb") as stored_stream:
                sha256, size = stream_integrity(stored_stream)
            os.replace(temporary, target)
        except Exception as error:
            temporary.unlink(missing_ok=True)
            if isinstance(error, StorageError):
                raise
            raise StorageError("Could not store local artifact") from error
        return StoredObject(uri=target.as_uri(), size=size, sha256=sha256)

    def open(self, uri: str) -> BinaryIO:
        path = self._path_from_uri(uri)
        try:
            return path.open("rb")
        except OSError as error:
            raise StorageError("Could not open local artifact") from error

    @contextmanager
    def materialize(self, uri: str) -> Iterator[Path]:
        yield self._path_from_uri(uri)

    def exists(self, uri: str) -> bool:
        return self._path_from_uri(uri).is_file()

    def delete(self, uri: str) -> None:
        path = self._path_from_uri(uri)
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise StorageError("Could not delete local artifact") from error

    def verify(self, uri: str, sha256: str, size: int) -> bool:
        try:
            with self.open(uri) as stream:
                actual_sha256, actual_size = stream_integrity(stream)
        except StorageError:
            return False
        return actual_sha256 == sha256 and actual_size == size

    def _path_from_uri(self, uri: str) -> Path:
        parsed = urlsplit(uri)
        if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
            raise StorageError("Invalid local artifact URI")
        path = Path(url2pathname(unquote(parsed.path)))
        return self._require_contained(path)

    def _require_contained(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.base_dir):
            raise StorageError("Artifact path escapes the storage root")
        return resolved
