"""Idempotent migration of legacy local artifact files to configured storage."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.models.artifact import Artifact


@dataclass(frozen=True)
class ArtifactMigrationResult:
    candidates: int = 0
    migrated: int = 0
    skipped: int = 0
    failed: int = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migrate_artifacts(db, storage, *, project_id=None, dry_run=False) -> ArtifactMigrationResult:
    scope = db.query(Artifact)
    if project_id is not None:
        scope = scope.filter(Artifact.project_id == project_id)

    skipped = scope.filter(Artifact.storage_uri.is_not(None)).count()
    query = scope.filter(Artifact.storage_uri.is_(None))

    candidates = migrated = failed = 0
    for artifact in query.order_by(Artifact.id).all():
        legacy_path = Path(artifact.storage_path or "")
        if not legacy_path.is_file():
            failed += 1
            continue
        candidates += 1
        if dry_run:
            continue

        try:
            size = legacy_path.stat().st_size
            sha256 = _sha256(legacy_path)
            stored = storage.put(
                legacy_path,
                project_id=str(artifact.project_id),
                artifact_id=str(artifact.id),
                filename=legacy_path.name,
            )
            if stored.size != size or stored.sha256 != sha256:
                storage.delete(stored.uri)
                failed += 1
                continue
            artifact.storage_uri = stored.uri
            artifact.file_size = size
            metadata = dict(artifact.metadata_ or {})
            metadata["sha256"] = sha256
            artifact.metadata_ = metadata
            db.commit()
            migrated += 1
        except Exception:
            db.rollback()
            failed += 1

    return ArtifactMigrationResult(candidates, migrated, skipped, failed)
