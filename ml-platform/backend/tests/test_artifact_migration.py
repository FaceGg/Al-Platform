import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path

from app.database import Base, SessionLocal, engine
from app.database_migrations import ensure_schema_compatibility
from app.models.artifact import Artifact
from app.models.project import Project
from app.models.user import User
from app.storage.local import LocalStorage
from app.services.artifact_migration import migrate_artifacts


Base.metadata.create_all(bind=engine)
ensure_schema_compatibility(engine)


class TestArtifactMigration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = SessionLocal()
        user = User(
            username=f"artifact_migration_{uuid.uuid4().hex}",
            password_hash="hash",
            role="user",
        )
        self.db.add(user)
        self.db.flush()
        project = Project(name="Migration Project", owner_id=user.id)
        self.db.add(project)
        self.db.commit()
        self.project_id = project.id
        self.source = Path(self.temp.name) / "legacy.csv"
        self.payload = b"a,b\n1,2\n"
        self.source.write_bytes(self.payload)
        self.artifact = Artifact(
            project_id=self.project_id,
            name="legacy.csv",
            type="dataset",
            storage_path=str(self.source),
            storage_uri=None,
            file_size=len(self.payload),
            metadata_={"sha256": hashlib.sha256(self.payload).hexdigest()},
        )
        self.db.add(self.artifact)
        self.db.commit()
        self.storage = LocalStorage(Path(self.temp.name) / "objects")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_migration_is_idempotent_and_verifies_content(self):
        first = migrate_artifacts(self.db, self.storage, project_id=self.project_id)
        self.assertEqual(first.migrated, 1)
        self.db.refresh(self.artifact)
        self.assertTrue(self.artifact.storage_uri.startswith("file://"))
        self.assertEqual(self.artifact.file_size, len(self.payload))

        second = migrate_artifacts(self.db, self.storage, project_id=self.project_id)
        self.assertEqual(second.migrated, 0)
        self.assertEqual(second.skipped, 1)

    def test_dry_run_does_not_change_legacy_record(self):
        result = migrate_artifacts(
            self.db,
            self.storage,
            project_id=self.project_id,
            dry_run=True,
        )
        self.assertEqual(result.migrated, 0)
        self.assertEqual(result.candidates, 1)
        self.db.refresh(self.artifact)
        self.assertIsNone(self.artifact.storage_uri)
        self.assertEqual(self.artifact.storage_path, str(self.source))


if __name__ == "__main__":
    unittest.main()
