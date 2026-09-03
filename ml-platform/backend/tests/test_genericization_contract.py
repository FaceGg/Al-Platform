"""Task 1 contracts for the generic annotation boundary."""

import sys
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, ".")

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.project import Project
from app.models.user import User
from app.services.annotation_tasks import migrate_legacy_quality_run
from app.models.spot_weld_quality import SpotWeldQualityRun


class GenericizationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)
        cls.db = cls.Session()
        cls.owner = User(username="generic-owner", password_hash="hash", role="engineer")
        cls.db.add(cls.owner)
        cls.db.flush()
        cls.project = Project(name="Generic project", owner_id=cls.owner.id)
        cls.db.add(cls.project)
        cls.db.commit()
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.owner
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    def test_generic_annotation_create_does_not_require_industry_columns(self):
        response = self.client.post(
            "/api/annotation-tasks",
            json={
                "project_id": str(self.project.id),
                "dataset_version_id": str(uuid.uuid4()),
                "mode": "manual",
                "label_schema_id": str(uuid.uuid4()),
                "sample_scope": {"kind": "all"},
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn("industry_field", response.json())

    def test_legacy_spot_weld_write_is_closed(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs", json={}
        )
        self.assertIn(response.status_code, (307, 410), response.text)

    def test_legacy_quality_run_migrates_to_generic_task(self):
        run = SpotWeldQualityRun(
            project_id=self.project.id,
            dataset_artifact_id=uuid.uuid4(),
            created_by_id=self.owner.id,
            status="completed",
            field_mapping={"target_column": "label"},
            automl_results=[{"algorithm": "legacy"}],
        )
        self.db.add(run)
        self.db.commit()
        task = migrate_legacy_quality_run(self.db, run.id)
        self.assertIn(task.mode, {"manual", "automatic"})
        self.assertEqual(task.source_legacy_id, str(run.id))


if __name__ == "__main__":
    unittest.main()
