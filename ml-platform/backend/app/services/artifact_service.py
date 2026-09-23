"""Project-scoped artifact persistence and storage access."""

import logging
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.data_version import DatasetImport, DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.storage.base import ArtifactStorage, StorageError
from app.storage.factory import create_artifact_storage
from app.services.security import validate_upload_filename, validate_upload_magic


logger = logging.getLogger(__name__)


class ArtifactAccessError(ValueError):
    pass


class ArtifactService:
    def __init__(self, db: Session, storage: ArtifactStorage):
        self.db = db
        self.storage = storage

    def create_from_file(
        self,
        project_id,
        source_path: str | Path,
        name: str,
        artifact_type: str,
        metadata: dict | None = None,
        *,
        commit: bool = True,
    ) -> Artifact:
        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(str(source))
        project_id = self._coerce_uuid(project_id)

        artifact_id = uuid.uuid4()
        stored = self.storage.put(
            source,
            project_id=str(project_id),
            artifact_id=str(artifact_id),
            filename=source.name,
        )
        artifact_metadata = {
            **(metadata or {}),
            "sha256": stored.sha256,
            "source": (metadata or {}).get("source", "generated"),
        }
        artifact = Artifact(
            id=artifact_id,
            project_id=project_id,
            name=name,
            type=artifact_type,
            storage_path="",
            storage_uri=stored.uri,
            file_size=stored.size,
            format=source.suffix.lstrip(".").lower(),
            metadata_=artifact_metadata,
        )
        try:
            if commit:
                self.db.add(artifact)
                self.db.commit()
                self.db.refresh(artifact)
            else:
                self.db.add(artifact)
                self.db.flush()
        except Exception:
            if commit:
                self.db.rollback()
            try:
                self.storage.delete(stored.uri)
            except Exception:
                logger.exception(
                    "Artifact upload compensation failed",
                    extra={"artifact_id": str(artifact_id), "storage_uri": stored.uri},
                )
            raise
        return artifact

    def create_from_draft(self, draft, project_id, run_id, node_id) -> Artifact:
        metadata = {
            **(draft.metadata or {}),
            "run_id": str(run_id),
            "node_id": str(node_id),
        }
        data = draft.data
        if isinstance(data, (bytes, bytearray)):
            temporary = Path(self._temporary_draft_path(draft.name))
            try:
                temporary.write_bytes(bytes(data))
                return self.create_from_file(
                    project_id, temporary, draft.name, draft.type, metadata,
                )
            finally:
                temporary.unlink(missing_ok=True)
        if isinstance(data, str):
            return self.create_from_file(project_id, data, draft.name, draft.type, metadata)
        return self.create_from_file(project_id, data, draft.name, draft.type, metadata)

    def create_dataset_version_from_artifact(self, artifact: Artifact, *, operator_id) -> DatasetVersion:
        if artifact.type != "dataset" or not operator_id:
            raise ValueError("Dataset version requires a dataset artifact and operator")
        operator_id = uuid.UUID(str(operator_id))
        with self.storage.materialize(artifact.storage_uri) as path:
            frame = pd.read_csv(path)
        import hashlib
        import json
        content_hash = hashlib.sha256(frame.to_csv(index=False).encode("utf-8")).hexdigest()
        schema = [
            {"name": str(column), "dtype": str(frame[column].dtype), "nullable": bool(frame[column].isna().any())}
            for column in frame.columns
        ]
        schema_hash = hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        latest = self.db.query(DatasetVersion.version).filter(
            DatasetVersion.project_id == artifact.project_id
        ).order_by(DatasetVersion.version.desc()).first()
        version = DatasetVersion(
            project_id=artifact.project_id,
            operator_id=operator_id,
            version=(latest[0] if latest else 0) + 1,
            status="ready",
            row_count=len(frame),
            column_count=len(frame.columns),
            content_hash=content_hash,
            schema_hash=schema_hash,
            parse_contract={"source_format": artifact.format, "source": "workflow_export"},
            original_artifact_id=artifact.id,
            normalized_artifact_id=artifact.id,
        )
        self.db.add(version)
        self.db.flush()
        for position, column in enumerate(frame.columns):
            self.db.add(DatasetSchemaColumn(
                dataset_version_id=version.id,
                name=str(column),
                position=position,
                dtype=str(frame[column].dtype),
                nullable=bool(frame[column].isna().any()),
            ))
        for index, values in enumerate(frame.to_dict(orient="records")):
            self.db.add(DatasetSample(
                dataset_version_id=version.id,
                sample_id=str(index),
                row_index=index,
                values={str(key): (None if pd.isna(value) else value) for key, value in values.items()},
            ))
        self.db.add(DatasetImport(
            dataset_version_id=version.id,
            source_format=artifact.format or "csv",
            parse_contract=version.parse_contract,
            content_hash=content_hash,
            schema_hash=schema_hash,
        ))
        self.db.flush()
        return version

    @staticmethod
    def _temporary_draft_path(name: str) -> str:
        import tempfile
        safe_name = validate_upload_filename(Path(name).name or "artifact.bin")
        return str(Path(tempfile.gettempdir()) / f"artifact-draft-{uuid.uuid4().hex}-{safe_name}")

    def create_dataset(
        self, project_id, source_path: str | Path, name: str, *, commit: bool = True,
    ) -> Artifact:
        source = Path(source_path)
        if source.suffix.lower() in {".xls", ".xlsx"}:
            frame = pd.read_excel(source)
        else:
            frame = pd.read_csv(source)
        schema = [
            {
                "name": str(column),
                "dtype": str(frame[column].dtype),
                "null_count": int(frame[column].isna().sum()),
            }
            for column in frame.columns
        ]
        return self.create_from_file(
            project_id,
            source,
            name,
            "dataset",
            metadata={
                "source": "upload",
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "schema": schema,
            },
            commit=commit,
        )

    def create_from_stream(
        self,
        project_id,
        stream,
        filename: str,
        artifact_type: str,
        metadata: dict | None = None,
        *,
        max_bytes: int,
        commit: bool = True,
    ) -> Artifact:
        if max_bytes <= 0:
            raise ArtifactAccessError("Artifact size limit must be positive")
        import tempfile

        try:
            safe_filename = validate_upload_filename(filename)
        except ValueError as error:
            raise ArtifactAccessError(str(error)) from error
        temporary = Path(tempfile.gettempdir()) / (
            f"artifact-upload-{uuid.uuid4().hex}-{safe_filename}"
        )
        size = 0
        prefix = bytearray()
        try:
            with temporary.open("xb") as output:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise ArtifactAccessError("Artifact stream must be binary")
                    size += len(chunk)
                    if size > max_bytes:
                        raise ArtifactAccessError("Artifact exceeds size limit")
                    if len(prefix) < 8192:
                        prefix.extend(chunk[: 8192 - len(prefix)])
                    output.write(chunk)
            try:
                validate_upload_magic(Path(safe_filename).suffix, bytes(prefix))
            except ValueError as error:
                raise ArtifactAccessError(str(error)) from error
            return self.create_from_file(
                project_id,
                temporary,
                safe_filename,
                artifact_type,
                metadata={**(metadata or {}), "uploaded_size": size},
                commit=commit,
            )
        finally:
            temporary.unlink(missing_ok=True)

    def resolve(self, artifact_id, project_id, expected_type: str | None = None) -> Artifact:
        artifact_id = self._coerce_uuid(artifact_id)
        project_id = self._coerce_uuid(project_id)
        artifact = (
            self.db.query(Artifact)
            .filter(
                Artifact.id == artifact_id,
                Artifact.project_id == project_id,
            )
            .first()
        )
        if artifact is None:
            raise ArtifactAccessError("Artifact not found in project")
        if expected_type is not None and artifact.type != expected_type:
            raise ArtifactAccessError(f"Expected artifact type '{expected_type}'")
        return artifact

    @staticmethod
    def _coerce_uuid(value):
        if isinstance(value, str):
            try:
                return uuid.UUID(value)
            except ValueError as error:
                raise ArtifactAccessError("Invalid Artifact or project ID") from error
        return value

    @contextmanager
    def materialize(
        self,
        artifact_id,
        project_id,
        expected_type: str | None = None,
    ) -> Iterator[Path]:
        artifact = self.resolve(artifact_id, project_id, expected_type)
        if artifact.storage_uri:
            try:
                with self.storage.materialize(artifact.storage_uri) as path:
                    yield path
            except StorageError as error:
                raise ArtifactAccessError("Artifact content is unavailable") from error
            return

        legacy_path = Path(artifact.storage_path or "")
        if not legacy_path.is_file():
            raise ArtifactAccessError("Artifact file is missing")
        yield legacy_path

    def delete_content(self, artifact: Artifact) -> None:
        if artifact.storage_uri:
            self.storage.delete(artifact.storage_uri)
            return
        legacy_path = Path(artifact.storage_path or "")
        if legacy_path.is_file():
            legacy_path.unlink()

    @staticmethod
    def storage_reference(artifact: Artifact) -> str:
        if artifact.storage_uri:
            return artifact.storage_uri
        legacy_path = Path(artifact.storage_path or "")
        if not legacy_path.is_file():
            raise ArtifactAccessError("Artifact file is missing")
        return legacy_path.resolve().as_uri()


def build_artifact_service(db: Session, settings_obj=None) -> ArtifactService:
    if settings_obj is None:
        from app.config import settings as settings_obj
    return ArtifactService(db, create_artifact_storage(settings_obj))
