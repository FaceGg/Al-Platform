"""Agent center read-only listing API tests (Agent plan, front-end wiring)."""

import os
import unittest
import uuid
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.recipe import PipelineRecipe, PipelineRecipeVersion  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent.recipe import create_recipe  # noqa: E402
from tests.auth_test_support import ensure_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(__import__("app.main", fromlist=["app"]).app)

_ADMIN_USER = "agent-center-admin-" + uuid4().hex[:8]
_ADMIN_PASSWORD = uuid4().hex + uuid4().hex[:4]


class AgentCenterHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin(_ADMIN_USER, _ADMIN_PASSWORD)
        token = client.post(
            "/api/auth/login",
            data={"username": _ADMIN_USER, "password": _ADMIN_PASSWORD},
        ).json()["access_token"]
        cls.h = {"Authorization": "Bearer " + token}
        with SessionLocal() as db:
            cls.user_id = str(
                db.query(User).filter(User.username == _ADMIN_USER).one().id
            )

    def setUp(self):
        with SessionLocal() as db:
            db.query(AgentRun).delete()
            db.query(PipelineRecipeVersion).delete()
            db.query(PipelineRecipe).delete()
            db.query(Project).filter(Project.name.like("agent-center-%")).delete()
            db.commit()

    def _project(self, name="agent-center-proj"):
        with SessionLocal() as db:
            project = Project(name=name, owner_id=None, description="")
            db.add(project)
            db.commit()
            return str(project.id), project.name


class TestAgentRunsListing(AgentCenterHarness, unittest.TestCase):
    def test_lists_runs_with_project_name_and_metadata_only(self):
        project_id, project_name = self._project()
        with SessionLocal() as db:
            db.add(AgentRun(
                project_id=uuid.UUID(project_id),
                target_column="DECIDE",
                status="waiting_escalate",
                current_stage="s4",
                round_count=1,
                token_used=9588,
                error_code="AGENT_REVIEW_ESCALATE",
                memory_json={"rounds": [{"round": 1}]},
                result_json={"secret": "no-leak"},
            ))
            db.add(AgentRun(
                target_column="fault",
                status="running",
                current_stage="s2",
            ))
            db.commit()

        response = client.get("/api/agent/runs", headers=self.h)
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertEqual(len(items), 2)
        # Updated-first ordering (the running row has no timestamps edge-case;
        # both rows exist, ordering by updated_at desc).
        by_status = {item["status"]: item for item in items}
        escalated = by_status["waiting_escalate"]
        self.assertEqual(escalated["project_name"], project_name)
        self.assertEqual(escalated["current_stage"], "s4")
        self.assertEqual(escalated["round_count"], 1)
        self.assertEqual(escalated["token_used"], 9588)
        # Memory/result payloads must not be exposed.
        self.assertNotIn("memory_json", escalated)
        self.assertNotIn("result_json", escalated)
        self.assertNotIn("secret", response.text)
        self.assertIsNone(by_status["running"]["project_name"])

    def test_requires_authentication(self):
        response = client.get("/api/agent/runs")
        self.assertEqual(response.status_code, 401)


class TestRecipeListing(AgentCenterHarness, unittest.TestCase):
    def test_lists_recipes_with_current_version_metadata(self):
        project_id, project_name = self._project()
        with SessionLocal() as db:
            create_recipe(
                db,
                project_id=uuid.UUID(project_id),
                name="tightening-v1",
                domain="tightening",
                target_column="DECIDE",
                content={"features": {"keep": ["TORQUE_DEVIATION"]}},
                change_note="验收通过固化",
                created_by=uuid.UUID(self.user_id),
            )

        response = client.get("/api/agent/recipes", headers=self.h)
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertEqual(len(items), 1)
        recipe = items[0]
        self.assertEqual(recipe["name"], "tightening-v1")
        self.assertEqual(recipe["project_name"], project_name)
        self.assertEqual(recipe["current_version"], 1)
        self.assertEqual(recipe["version_status"], "current")
        self.assertEqual(recipe["change_note"], "验收通过固化")
        # Recipe version content must not be exposed.
        self.assertNotIn("content_json", recipe)
        self.assertNotIn("TORQUE_DEVIATION", response.text)

    def test_requires_authentication(self):
        response = client.get("/api/agent/recipes")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
