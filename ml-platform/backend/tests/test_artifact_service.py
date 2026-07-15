import tempfile
import unittest
import uuid
from pathlib import Path

from app.database import Base, SessionLocal, engine
from app.models.project import Project
from app.models.user import User
from app.services.artifact_service import ArtifactAccessError, ArtifactService


Base.metadata.create_all(bind=engine)


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

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_create_dataset_records_hash_and_schema(self):
        service = ArtifactService(self.db, Path(self.temp_dir.name) / "artifacts")
        artifact = service.create_dataset(self.project_id, self.source, "weld.csv")

        self.assertEqual(artifact.type, "dataset")
        self.assertEqual(artifact.metadata_["row_count"], 2)
        self.assertEqual([item["name"] for item in artifact.metadata_["schema"]], [
            "current", "force", "quality",
        ])
        self.assertEqual(len(artifact.metadata_["sha256"]), 64)
        self.assertNotEqual(Path(artifact.storage_path), self.source)

    def test_resolve_rejects_cross_project_artifact(self):
        service = ArtifactService(self.db, Path(self.temp_dir.name) / "artifacts")
        artifact = service.create_dataset(self.project_id, self.source, "weld.csv")

        with self.assertRaises(ArtifactAccessError):
            service.resolve(artifact.id, self.other_project_id, expected_type="dataset")


if __name__ == "__main__":
    unittest.main()
