import hashlib
import shutil
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.models.artifact import Artifact


class ArtifactAccessError(ValueError):
    pass


class ArtifactService:
    def __init__(self, db: Session, base_dir: str | Path):
        self.db = db
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def create_from_file(
        self, project_id, source_path: str | Path, name: str, artifact_type: str,
        metadata: dict | None = None,
    ) -> Artifact:
        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(str(source))
        artifact_id = uuid.uuid4()
        target_dir = self.base_dir / str(project_id) / str(artifact_id)
        target_dir.mkdir(parents=True, exist_ok=False)
        target = target_dir / source.name
        shutil.copy2(source, target)
        artifact_metadata = {
            **(metadata or {}),
            "sha256": self._sha256(target),
            "source": (metadata or {}).get("source", "generated"),
        }
        artifact = Artifact(
            id=artifact_id,
            project_id=project_id,
            name=name,
            type=artifact_type,
            storage_path=str(target),
            file_size=target.stat().st_size,
            format=target.suffix.lstrip(".").lower(),
            metadata_=artifact_metadata,
        )
        self.db.add(artifact)
        self.db.commit()
        self.db.refresh(artifact)
        return artifact

    def create_dataset(self, project_id, source_path: str | Path, name: str) -> Artifact:
        source = Path(source_path)
        if source.suffix.lower() in {".xls", ".xlsx"}:
            frame = pd.read_excel(source)
        else:
            frame = pd.read_csv(source)
        schema = [{
            "name": str(column),
            "dtype": str(frame[column].dtype),
            "null_count": int(frame[column].isna().sum()),
        } for column in frame.columns]
        return self.create_from_file(
            project_id, source, name, "dataset",
            metadata={
                "source": "upload",
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "schema": schema,
            },
        )

    def resolve(self, artifact_id, project_id, expected_type: str | None = None) -> Artifact:
        artifact = self.db.query(Artifact).filter(
            Artifact.id == artifact_id,
            Artifact.project_id == project_id,
        ).first()
        if artifact is None:
            raise ArtifactAccessError("Artifact not found in project")
        if expected_type is not None and artifact.type != expected_type:
            raise ArtifactAccessError(f"Expected artifact type '{expected_type}'")
        if not Path(artifact.storage_path).is_file():
            raise ArtifactAccessError("Artifact file is missing")
        return artifact
