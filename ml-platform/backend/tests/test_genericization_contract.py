"""Task 1 contracts for the generic annotation boundary."""

import sys
import unittest
import uuid
import hashlib
from pathlib import Path

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
from app.models.platform_models import GenericAnnotationTask
from app.services.annotation_tasks import migrate_legacy_quality_run
from app.models.spot_weld_quality import SpotWeldQualityRun
from app.models.spot_weld_quality import SpotWeldQualitySample, SpotWeldLabelRevision, SpotWeldLabelSnapshot


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
            headers={"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": "generic-1"},
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

    def test_generic_annotation_idempotency_returns_same_task(self):
        payload = {
            "project_id": str(self.project.id),
            "dataset_version_id": str(uuid.uuid4()),
            "mode": "manual",
            "label_schema_id": str(uuid.uuid4()),
            "sample_scope": {"kind": "all"},
        }
        headers = {"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": "same-key"}
        first = self.client.post("/api/annotation-tasks", json=payload, headers=headers)
        second = self.client.post("/api/annotation-tasks", json=payload, headers=headers)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])

    def test_generic_annotation_requires_explicit_correlation_headers(self):
        payload = {
            "project_id": str(self.project.id),
            "dataset_version_id": str(uuid.uuid4()),
            "mode": "manual",
            "label_schema_id": str(uuid.uuid4()),
            "sample_scope": {"kind": "all"},
        }
        missing_request = self.client.post(
            "/api/annotation-tasks", json=payload,
            headers={"Idempotency-Key": "header-test-1"},
        )
        self.assertEqual(missing_request.status_code, 400)
        missing_idempotency = self.client.post(
            "/api/annotation-tasks", json=payload,
            headers={"X-Request-ID": str(uuid.uuid4())},
        )
        self.assertEqual(missing_idempotency.status_code, 400)

    def test_legacy_spot_weld_write_is_closed(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/spot-weld/runs", json={}
        )
        self.assertEqual(response.status_code, 410, response.text)
        self.assertEqual(response.json()["detail"]["code"], "GENERIC_API_REQUIRED")

    def test_list_is_owner_isolated(self):
        other = User(username="generic-other", password_hash="hash", role="engineer")
        self.db.add(other)
        self.db.commit()
        task = self.db.query(GenericAnnotationTask).filter_by(owner_id=self.owner.id).first()
        if task is None:
            task = GenericAnnotationTask(
                project_id=self.project.id,
                dataset_version_id=uuid.uuid4(),
                label_schema_id=uuid.uuid4(),
                owner_id=self.owner.id,
                mode="manual",
                sample_scope={"kind": "all"},
            )
            self.db.add(task)
            self.db.commit()
        app.dependency_overrides[get_current_user] = lambda: other
        response = self.client.get("/api/annotation-tasks", headers={"X-Request-ID": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)
        app.dependency_overrides[get_current_user] = lambda: self.owner

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
        sample = SpotWeldQualitySample(
            run_id=run.id, source_row_index=0, display_id="row-0",
            table_values={"x": 1}, current_label="ok",
        )
        self.db.add(sample)
        self.db.flush()
        revision = SpotWeldLabelRevision(
            project_id=self.project.id, run_id=run.id, sample_id=sample.id,
            author_id=self.owner.id, label="ok", action="submitted",
            review_comment="reviewed", parent_revision_id=None,
        )
        snapshot = SpotWeldLabelSnapshot(
            project_id=self.project.id, run_id=run.id, created_by_id=self.owner.id,
            name="approved", labels=["ok"], label_counts={"ok": 1},
        )
        self.db.add_all([revision, snapshot])
        self.db.commit()
        task = migrate_legacy_quality_run(self.db, run.id)
        self.assertIn(task.mode, {"manual", "automatic"})
        self.assertEqual(task.source_legacy_id, str(run.id))
        self.assertEqual(task.label_snapshot["samples"][0]["id"], str(sample.id))
        self.assertEqual(task.label_snapshot["revisions"][0]["review_comment"], "reviewed")
        self.assertEqual(task.label_snapshot["snapshots"][0]["run_id"], str(run.id))
        checksum = task.label_snapshot["checksum"]
        self.assertEqual(checksum, hashlib.sha256(
            task.label_snapshot["canonical_json"].encode("utf-8")
        ).hexdigest())

    def test_legacy_migration_authorization_and_missing_run(self):
        other = User(username="generic-third", password_hash="hash", role="engineer")
        self.db.add(other)
        run = SpotWeldQualityRun(
            project_id=self.project.id, dataset_artifact_id=uuid.uuid4(),
            created_by_id=self.owner.id, status="completed",
        )
        self.db.add(run)
        self.db.commit()
        app.dependency_overrides[get_current_user] = lambda: other
        denied = self.client.post(
            f"/api/annotation-tasks/{run.id}/migrate",
            headers={"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": "migration-denied"},
        )
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(self.db.query(GenericAnnotationTask).count(), 0)
        app.dependency_overrides[get_current_user] = lambda: self.owner
        missing = self.client.post(
            f"/api/annotation-tasks/{uuid.uuid4()}/migrate",
            headers={"X-Request-ID": str(uuid.uuid4()), "Idempotency-Key": "migration-missing"},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"]["code"], "LEGACY_QUALITY_RUN_NOT_FOUND")

    def test_generic_task_migration_revision_is_present(self):
        migration = Path(__file__).parents[1] / "alembic" / "versions" / "20260903_15_generic_annotation_tasks.py"
        self.assertTrue(migration.exists())
        contents = migration.read_text(encoding="utf-8")
        self.assertIn('revision = "20260903_15"', contents)
        self.assertIn('down_revision = "20260829_14"', contents)
        self.assertIn("uq_generic_annotation_task_source_legacy_id", contents)


if __name__ == "__main__":
    unittest.main()
