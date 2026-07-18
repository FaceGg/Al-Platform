import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.project import Project
from app.models.user import User
from app.models.workflow import Workflow


class TestScheduleAPI(unittest.TestCase):
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
            cls.owner = User(username="schedule-api-owner", password_hash="hash")
            cls.other = User(username="schedule-api-other", password_hash="hash")
            db.add_all([cls.owner, cls.other])
            db.flush()
            cls.project = Project(name="Schedule API project", owner_id=cls.owner.id)
            cls.other_project = Project(name="Other project", owner_id=cls.other.id)
            db.add_all([cls.project, cls.other_project])
            db.flush()
            cls.workflow = Workflow(
                project_id=cls.project.id,
                name="API workflow",
                created_by=cls.owner.id,
            )
            db.add(cls.workflow)
            db.commit()
            cls.project_id = str(cls.project.id)
            cls.workflow_id = str(cls.workflow.id)
            cls.schedule_id = None

        cls.db = cls.Session()
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.owner
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    def test_create_and_list_schedule(self):
        response = self.client.post(
            f"/api/projects/{self.project_id}/schedules",
            json={
                "name": "Every hour",
                "workflow_id": self.workflow_id,
                "cron_expression": "0 * * * *",
                "timezone": "UTC",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertEqual(payload["name"], "Every hour")
        self.__class__.schedule_id = payload["id"]

        listed = self.client.get(f"/api/projects/{self.project_id}/schedules")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["total"], 1)

    def test_invalid_cron_returns_stable_error(self):
        response = self.client.post(
            f"/api/projects/{self.project_id}/schedules",
            json={
                "name": "Invalid",
                "workflow_id": self.workflow_id,
                "cron_expression": "invalid",
                "timezone": "UTC",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "SCHEDULE_INVALID_CRON")

    def test_pause_resume_and_cross_project_isolation(self):
        if self.schedule_id is None:
            self.test_create_and_list_schedule()
        paused = self.client.post(f"/api/schedules/{self.schedule_id}/pause")
        self.assertEqual(paused.status_code, 200, paused.text)
        resumed = self.client.post(f"/api/schedules/{self.schedule_id}/resume")
        self.assertEqual(resumed.status_code, 200, resumed.text)

        app.dependency_overrides[get_current_user] = lambda: self.other
        hidden = self.client.get(f"/api/schedules/{self.schedule_id}")
        self.assertEqual(hidden.status_code, 404)
        app.dependency_overrides[get_current_user] = lambda: self.owner

    def test_update_backfill_and_paginated_run_history(self):
        from app.services.pipeline_scheduler import PipelineScheduler

        if self.schedule_id is None:
            self.test_create_and_list_schedule()
        updated = self.client.patch(
            f"/api/schedules/{self.schedule_id}",
            json={"cron_expression": "30 * * * *", "max_concurrency": 2},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["max_concurrency"], 2)

        scheduler = PipelineScheduler(enqueue=lambda run_id: "api-backfill-task")
        with patch("app.api.schedules._scheduler", return_value=scheduler):
            backfilled = self.client.post(
                f"/api/schedules/{self.schedule_id}/backfill",
                json={"occurrences": ["2026-07-17T12:00:00Z"]},
            )
        self.assertEqual(backfilled.status_code, 200, backfilled.text)
        self.assertEqual(backfilled.json()["items"][0]["status"], "claimed")

        history = self.client.get(
            f"/api/schedules/{self.schedule_id}/runs?offset=0&limit=10"
        )
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(history.json()["total"], 1)


if __name__ == "__main__":
    unittest.main()
