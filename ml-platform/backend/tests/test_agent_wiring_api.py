"""Prompt template API + chat tools API wiring tests (Agent plan P5/P6)."""

import os
import unittest
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.platform_audit import PlatformAuditEvent  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent.recipe import create_recipe  # noqa: E402
from tests.auth_test_support import ensure_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(__import__("app.main", fromlist=["app"]).app)

_ADMIN_USER = "wiring-admin-" + uuid4().hex[:8]
_ADMIN_PASSWORD = uuid4().hex + uuid4().hex[:4]


class WiringHarness(unittest.TestCase):
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
            from app.models.experience_entry import ExperienceEntry

            db.query(ExperienceEntry).delete()
            db.query(PlatformAuditEvent).filter(
                PlatformAuditEvent.resource_type == "chat_tool"
            ).delete()
            db.commit()


class TestPromptTemplateAPI(WiringHarness, unittest.TestCase):
    def _create(self, name=None, stage="analysis"):
        response = client.post(
            "/api/prompt-templates",
            json={
                "name": name or ("tpl-%s" % uuid4().hex[:6]),
                "stage": stage,
                "content": "重点关注扭矩-目标偏差",
            },
            headers=self.h,
        )
        return response

    def test_create_list_use_delete_roundtrip(self):
        created = self._create()
        self.assertEqual(created.status_code, 201, created.text)
        template_id = created.json()["id"]
        used = client.post(
            "/api/prompt-templates/%s/use" % template_id, headers=self.h
        )
        self.assertEqual(used.json()["usage_count"], 1)
        listed = client.get("/api/prompt-templates", headers=self.h)
        self.assertEqual(len(listed.json()), 1)
        deleted = client.delete("/api/prompt-templates/%s" % template_id, headers=self.h)
        self.assertEqual(deleted.status_code, 204)

    def test_invalid_stage_rejected(self):
        response = self._create(stage="cooking")
        self.assertEqual(response.status_code, 422)

    def test_duplicate_name_conflicts(self):
        name = "dup-%s" % uuid4().hex[:6]
        self.assertEqual(self._create(name=name).status_code, 201)
        self.assertEqual(self._create(name=name).status_code, 409)


class TestChatToolsAPI(WiringHarness, unittest.TestCase):
    def test_whitelist_endpoint_lists_boundary(self):
        response = client.get("/api/chat-tools/whitelist", headers=self.h)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("execute_command", body["write_tools"])
        self.assertIn("save_insight", body["insight_tools"])

    def test_unknown_tool_rejected_without_crash(self):
        response = client.post(
            "/api/chat-tools/execute",
            json={"tool": "run_arbitrary_code", "params": {}},
            headers=self.h,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], "CHAT_TOOL_NOT_IN_WHITELIST")

    def test_write_tool_requires_confirmation_then_succeeds(self):
        recipe = None
        with SessionLocal() as db:
            recipe = create_recipe(
                db,
                project_id=None,
                name="wiring-recipe-%s" % uuid4().hex[:6],
                content={"domain": "tightening", "analysis_digest": "扭矩域"},
            )
            recipe_id = str(recipe.id)
        unconfirmed = client.post(
            "/api/chat-tools/execute",
            json={"tool": "save_insight", "params": {"text": "洞察"}},
            headers=self.h,
        )
        self.assertEqual(unconfirmed.json()["status"], "confirmation_required")
        confirmed = client.post(
            "/api/chat-tools/execute",
            json={"tool": "save_insight", "params": {"text": "二轴缺失属正常"},
                  "confirmed": True},
            headers=self.h,
        )
        self.assertEqual(confirmed.json()["status"], "success")
        self.assertEqual(confirmed.json()["result"]["status"], "active")

        report = client.post(
            "/api/chat-tools/execute",
            json={"tool": "query_recipe_reports", "params": {"recipe_id": recipe_id}},
            headers=self.h,
        )
        self.assertEqual(report.json()["result"]["analysis_digest"], "扭矩域")

    def test_unauthenticated_rejected(self):
        response = client.get("/api/chat-tools/whitelist")
        self.assertIn(response.status_code, (401, 403))
