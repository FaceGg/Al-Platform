"""Common artifact storage contract and integrity helpers."""

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, Protocol


class StorageError(RuntimeError):
    """Raised when an artifact storage operation cannot be completed safely."""


@dataclass(frozen=True)
class StoredObject:
    uri: str
    size: int
    sha256: str


class ArtifactStorage(Protocol):
    def put(
        self,
        source: Path,
        project_id: str,
        artifact_id: str,
        filename: str,
    ) -> StoredObject: ...

    def open(self, uri: str) -> BinaryIO: ...

    @contextmanager
    def materialize(self, uri: str) -> Iterator[Path]: ...

    def exists(self, uri: str) -> bool: ...

    def delete(self, uri: str) -> None: ...

    def verify(self, uri: str, sha256: str, size: int) -> bool: ...


def validate_key_segment(value: str, label: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or Path(value).is_absolute()
    ):
        raise StorageError(f"Invalid {label}")
    return value


def stream_integrity(stream: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size
