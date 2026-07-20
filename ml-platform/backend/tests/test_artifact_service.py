import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.database import Base, SessionLocal, engine
from app.database_migrations import ensure_schema_compatibility
from app.models.artifact import Artifact
from app.models.project import Project
from app.models.user import User
from app.services.artifact_service import ArtifactAccessError, ArtifactService
from app.storage.base import StoredObject
from app.storage.local import LocalStorage


Base.metadata.create_all(bind=engine)
ensure_schema_compatibility(engine)


class RecordingStorage:
    def __init__(self, uri: str):
        self.uri = uri
        self.deleted: list[str] = []

    def put(self, source, project_id, artifact_id, filename):
        return StoredObject(
            uri=self.uri,
            size=source.stat().st_size,
            sha256="digest",
        )

    def delete(self, uri):
        self.deleted.append(uri)


class TestArtifactService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = SessionLocal()
        user = User(username=f"artifact_user_{uuid.uuid4().hex}", password_hash="hash", role="user")
        self.db.add(user)
        self.db.flush()
        project = Project(name="Artifact Project", owner_id=user.id)
        other = Project(name="Other Project", owner_id=user.id)
        self.db.add_all([project, other])
        self.db.commit()
        self.project_id = project.id
        self.other_project_id = other.id
        self.source = Path(self.temp_dir.name) / "weld.csv"
        self.source.write_text("current,force,quality\n8,3,1\n9,4,0\n", encoding="utf-8")
        self.storage = LocalStorage(Path(self.temp_dir.name) / "artifacts")
        self.service = ArtifactService(self.db, self.storage)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_create_dataset_records_hash_and_schema(self):
        artifact = self.service.create_dataset(self.project_id, self.source, "weld.csv")

        self.assertEqual(artifact.type, "dataset")
        self.assertEqual(artifact.metadata_["row_count"], 2)
        self.assertEqual([item["name"] for item in artifact.metadata_["schema"]], [
            "current", "force", "quality",
        ])
        self.assertEqual(len(artifact.metadata_["sha256"]), 64)
        self.assertTrue(artifact.storage_uri.startswith("file://"))
        self.assertEqual(artifact.storage_path, "")

    def test_resolve_rejects_cross_project_artifact(self):
        artifact = self.service.create_dataset(self.project_id, self.source, "weld.csv")

        with self.assertRaises(ArtifactAccessError):
            self.service.resolve(artifact.id, self.other_project_id, expected_type="dataset")

    def test_db_failure_deletes_uploaded_object(self):
        storage = RecordingStorage("file:///uploaded/model.bin")
        service = ArtifactService(self.db, storage)

        with patch.object(self.db, "commit", side_effect=RuntimeError("db failed")):
            with self.assertRaisesRegex(RuntimeError, "db failed"):
                service.create_from_file(
                    project_id=self.project_id,
                    source_path=self.source,
                    name="model",
                    artifact_type="model",
                )

        self.assertEqual(storage.deleted, ["file:///uploaded/model.bin"])

    def test_materialize_falls_back_to_legacy_storage_path(self):
        artifact = Artifact(
            project_id=self.project_id,
            name="legacy.csv",
            type="dataset",
            storage_path=str(self.source),
            storage_uri=None,
        )
        self.db.add(artifact)
        self.db.commit()

        with self.service.materialize(artifact.id, artifact.project_id) as path:
            self.assertEqual(path.read_bytes(), self.source.read_bytes())


if __name__ == "__main__":
    unittest.main()
