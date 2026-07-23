"""Tests for app.api.annotations endpoints.

The annotation task CRUD, sample listing, update, and auto-label flows
previously had only smoke-route coverage.
"""
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
from app.models.platform_models import (
    AnnotationResult,
    AnnotationTask,
    Dataset,
)
from app.models.user import User


class TestAnnotationsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)

        with cls.Session() as db:
            cls.owner = User(username="annot-owner", password_hash="hash")
            cls.other = User(username="annot-other", password_hash="hash")
            db.add_all([cls.owner, cls.other])
            db.flush()
            cls.dataset = Dataset(
                name="Annot dataset",
                owner_id=cls.owner.id,
                data_modality="image",
                sample_count=3,
            )
            db.add(cls.dataset)
            db.flush()
            cls.dataset_id = str(cls.dataset.id)
            cls.owner_id = str(cls.owner.id)
            db.commit()

        cls.db = cls.Session()
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.owner
        cls.client = TestClient(app)
        cls.task_id = None

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    def test_01_create_task(self):
        response = self.client.post(
            "/api/annotations/tasks",
            json={
                "name": "Box Task",
                "dataset_id": self.dataset_id,
                "annotation_type": "rectangle",
                "description": "detect defects",
                "guidelines": "mark each weld",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.__class__.task_id = payload["id"]
        self.assertEqual(payload["name"], "Box Task")

    def test_02_list_tasks(self):
        response = self.client.get("/api/annotations/tasks")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["id"], self.task_id)

    def test_03_list_tasks_filter_by_status(self):
        response = self.client.get("/api/annotations/tasks", params={"status": "pending"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        empty = self.client.get("/api/annotations/tasks", params={"status": "completed"})
        self.assertEqual(empty.json()["total"], 0)

    def test_04_list_tasks_filter_by_dataset(self):
        response = self.client.get(
            "/api/annotations/tasks", params={"dataset_id": self.dataset_id}
        )
        self.assertEqual(response.json()["total"], 1)

    def test_05_get_task_detail(self):
        response = self.client.get(f"/api/annotations/tasks/{self.task_id}")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["name"], "Box Task")
        self.assertEqual(data["guidelines"], "mark each weld")

    def test_06_get_missing_task_returns_404(self):
        import uuid
        response = self.client.get(f"/api/annotations/tasks/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 404)

    def test_07_update_task(self):
        response = self.client.put(
            f"/api/annotations/tasks/{self.task_id}",
            json={"name": "Renamed Task", "status": "labeling", "total_samples": 3},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_08_update_missing_task_returns_404(self):
        import uuid
        response = self.client.put(
            f"/api/annotations/tasks/{uuid.uuid4()}", json={"name": "x"}
        )
        self.assertEqual(response.status_code, 404)

    def test_09_list_samples_empty(self):
        response = self.client.get(f"/api/annotations/tasks/{self.task_id}/samples")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 0)

    def test_10_add_samples_and_list(self):
        for index in range(3):
            self.db.add(AnnotationResult(
                task_id=uuid.UUID(self.task_id),
                sample_index=index,
                sample_path=f"/data/{index}.png",
                status="unlabeled",
            ))
        self.db.commit()
        response = self.client.get(f"/api/annotations/tasks/{self.task_id}/samples")
        data = response.json()
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["items"][0]["sample_index"], 0)

    def test_11_list_samples_filter_by_status(self):
        response = self.client.get(
            f"/api/annotations/tasks/{self.task_id}/samples", params={"status": "unlabeled"}
        )
        self.assertEqual(response.json()["total"], 3)
        reviewed = self.client.get(
            f"/api/annotations/tasks/{self.task_id}/samples", params={"status": "reviewed"}
        )
        self.assertEqual(reviewed.json()["total"], 0)

    def test_12_update_sample_updates_progress(self):
        # Fetch the first sample id.
        listing = self.client.get(f"/api/annotations/tasks/{self.task_id}/samples").json()
        sample_id = listing["items"][0]["id"]
        response = self.client.put(
            f"/api/annotations/samples/{sample_id}",
            json={"annotations": [{"label": "defect"}], "status": "labeled"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        # Task progress should now reflect one labeled sample.
        task = self.client.get(f"/api/annotations/tasks/{self.task_id}").json()
        self.assertEqual(task["labeled_samples"], 1)

    def test_13_update_missing_sample_returns_404(self):
        import uuid
        response = self.client.put(
            f"/api/annotations/samples/{uuid.uuid4()}", json={"status": "labeled"}
        )
        self.assertEqual(response.status_code, 404)

    def test_14_auto_label_marks_remaining_samples(self):
        # Two samples remain unlabeled (one was labeled in test_12).
        response = self.client.post(f"/api/annotations/tasks/{self.task_id}/auto-label")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["auto_labeled"], 2)
        task = self.client.get(f"/api/annotations/tasks/{self.task_id}").json()
        self.assertEqual(task["labeled_samples"], 3)

    def test_15_auto_label_missing_task_returns_404(self):
        import uuid
        response = self.client.post(f"/api/annotations/tasks/{uuid.uuid4()}/auto-label")
        self.assertEqual(response.status_code, 404)

    def test_16_delete_task(self):
        # SQLite does not enforce ON DELETE CASCADE like PostgreSQL, and the
        # ORM relationship lacks cascade="delete-orphan", so we remove child
        # AnnotationResult rows first to avoid a NOT NULL constraint violation.
        self.db.query(AnnotationResult).filter(
            AnnotationResult.task_id == uuid.UUID(self.task_id)
        ).delete(synchronize_session=False)
        self.db.commit()
        response = self.client.delete(f"/api/annotations/tasks/{self.task_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"status": "deleted"})
        missing = self.client.get(f"/api/annotations/tasks/{self.task_id}")
        self.assertEqual(missing.status_code, 404)

    def test_17_delete_missing_task_returns_404(self):
        import uuid
        response = self.client.delete(f"/api/annotations/tasks/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
