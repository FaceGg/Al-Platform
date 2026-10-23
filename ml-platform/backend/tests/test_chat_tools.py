"""Chat tools whitelist tests (AutoML Agent plan, Task A6.2)."""

import os
import unittest
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.experience_entry import ExperienceEntry  # noqa: E402
from app.models.platform_audit import PlatformAuditEvent  # noqa: E402
from app.models.recipe import PipelineRecipe, PipelineRecipeVersion  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent.recipe import create_recipe  # noqa: E402
from app.services.chat_tools import (  # noqa: E402
    ToolConfirmationRequired,
    ToolNotInWhitelist,
    WHITELIST,
    execute_tool,
)
from tests.auth_test_support import ensure_admin  # noqa: E402

Base.metadata.create_all(bind=engine)


class TestChatTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        db = SessionLocal()
        try:
            cls.user = db.query(User).filter(User.username == "admin").one()
        finally:
            db.close()

    def setUp(self):
        with SessionLocal() as db:
            db.query(ExperienceEntry).delete()
            db.query(PlatformAuditEvent).filter(
                PlatformAuditEvent.resource_type == "chat_tool"
            ).delete()
            db.commit()

    def test_whitelist_is_closed_and_has_no_dangerous_tools(self):
        for banned in (
            "execute_command",
            "read_file",
            "write_file",
            "query_database",
            "delete_dataset",
            "change_permissions",
            "manage_keys",
        ):
            self.assertNotIn(banned, WHITELIST)

    def test_unknown_tool_raises_structural_boundary(self):
        with SessionLocal() as db:
            with self.assertRaises(ToolNotInWhitelist):
                execute_tool(
                    db, user=self.user, tool="run_arbitrary_code", params={}
                )

    def test_save_insight_requires_confirmation(self):
        with SessionLocal() as db:
            with self.assertRaises(ToolConfirmationRequired):
                execute_tool(
                    db,
                    user=self.user,
                    tool="save_insight",
                    params={"text": "未确认的洞察"},
                )

    def test_save_insight_writes_human_experience_and_audits(self):
        with SessionLocal() as db:
            payload = execute_tool(
                db,
                user=self.user,
                tool="save_insight",
                params={"text": "二轴扭矩缺失在单轴工位属正常"},
                confirmed=True,
            )
            self.assertEqual(payload["status"], "active")
            entry = db.get(ExperienceEntry, __import__("uuid").UUID(payload["entry_id"]))
            self.assertEqual(entry.origin, "human")
            self.assertEqual(entry.confidence, 0.75)
            events = (
                db.query(PlatformAuditEvent)
                .filter(
                    PlatformAuditEvent.action == "chat_tool.invoke",
                    PlatformAuditEvent.resource_id == "save_insight",
                )
                .all()
            )
        self.assertEqual(len(events), 1)

    def test_query_recipe_reports_reads_current_version(self):
        with SessionLocal() as db:
            recipe = create_recipe(
                db,
                project_id=None,
                name="tool-recipe-%s" % uuid4().hex[:6],
                content={
                    "domain": "tightening",
                    "optimization_report": {"strengths": ["召回达标"]},
                    "analysis_digest": "扭矩域",
                },
            )
            payload = execute_tool(
                db,
                user=self.user,
                tool="query_recipe_reports",
                params={"recipe_id": str(recipe.id)},
            )
        self.assertEqual(payload["optimization_report"]["strengths"], ["召回达标"])

    def test_write_tool_without_handler_declares_boundary(self):
        with SessionLocal() as db:
            with self.assertRaises(ToolConfirmationRequired):
                execute_tool(
                    db, user=self.user, tool="create_loop_task", params={}
                )
            with self.assertRaises(LookupError):
                execute_tool(
                    db,
                    user=self.user,
                    tool="create_loop_task",
                    params={},
                    confirmed=True,
                )
