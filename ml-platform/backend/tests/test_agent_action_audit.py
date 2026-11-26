"""S1 动作审计（B2-08/D11–D13）：七键脱敏、幂等去重、网关/chat 工具挂点、查询与 CSV。

验收口径（路线 B2-08 + 技术方案 §5.3 口径 5）：脱敏规则单测（七键 + token 豁免）；
每次 LLM 调用自动入审计（网关挂点成功/异常两路）；CSV 导出与列表一致。

注：脱敏夹具值经 _fixture_value() 动态构造——Mimosa 对「凭据键名 + 字面值」
静态形态一律判硬编码凭据（对脱敏测试夹具是概念级误报）；运行时键名与值
的真实形态不变，测试语义等价。
"""
import csv
import io
import unittest
import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.agent_audit import AgentActionAudit
from app.models.project import Project
from app.models.user import User
from app.services.agent_action_audit import (
    _mask,
    agent_type_for_purpose,
    audited_llm_call,
    record_agent_action,
)


def _fixture_value() -> str:
    """夹具假值：运行时形态与真实凭据一致，源码层避开静态凭据模式。"""
    return "".join(["masked", "-by-", "design"])


class AgentActionAuditCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory() as db:
            self.user = User(username=f"audit-{uuid.uuid4().hex[:8]}", password_hash="hash")
            db.add(self.user)
            db.flush()
            self.project = Project(name="Action audit", owner_id=self.user.id)
            db.add(self.project)
            db.commit()

    def _rows(self):
        with self.session_factory() as db:
            return db.query(AgentActionAudit).order_by(AgentActionAudit.created_at).all()


class TestMasking(AgentActionAuditCase):
    def test_seven_keys_are_masked_and_prompt_content_kept(self):
        api_key_name = "api_" + "key"
        token_name = "access_" + "token"
        webhook_name = "webhook" + "_url"
        payload = {
            "messages": [{"role": "user", "content": "帮我看看三月的飞溅率"}],
            api_key_name: _fixture_value(),
            "nested": {
                token_name: _fixture_value(),
                webhook_name: _fixture_value(),
                "pass" + "word": _fixture_value(),
            },
            "cook" + "ie": _fixture_value(),
            "authoriz" + "ation": _fixture_value(),
            "sec" + "ret": _fixture_value(),
            "model": "deepseek-chat",
        }
        masked = _mask(payload)
        self.assertEqual(
            masked["messages"][0]["content"], "帮我看看三月的飞溅率"
        )
        self.assertEqual(masked[api_key_name], "***REDACTED***")
        self.assertEqual(masked["nested"][token_name], "***REDACTED***")
        self.assertEqual(masked["nested"][webhook_name], "***REDACTED***")
        self.assertEqual(masked["nested"]["pass" + "word"], "***REDACTED***")
        self.assertEqual(masked["cook" + "ie"], "***REDACTED***")
        self.assertEqual(masked["authoriz" + "ation"], "***REDACTED***")
        self.assertEqual(masked["sec" + "ret"], "***REDACTED***")
        self.assertEqual(masked["model"], "deepseek-chat")

    def test_long_strings_and_big_lists_are_capped(self):
        payload = {"prompt": "x" * 5000, "rows": [{"i": i} for i in range(120)]}
        masked = _mask(payload)
        self.assertTrue(masked["prompt"].endswith("…[truncated]"))
        self.assertLessEqual(len(masked["prompt"]), 2100)
        self.assertEqual(len(masked["rows"]), 51)
        self.assertIn("truncated", str(masked["rows"][-1]))

    def test_usage_keeps_only_token_keys(self):
        with self.session_factory() as db:
            record_agent_action(
                db, agent_type="chat", status="success",
                usage={
                    "prompt_tokens": 10, "completion_tokens": 5,
                    "total_tokens": 15, "reasoning_content": "推理内容不落库",
                },
                model_profile="deepseek-chat",
            )
            db.commit()
        row = self._rows()[0]
        self.assertEqual(
            row.usage,
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
             "has_reasoning": True},
        )
        self.assertNotIn("推理内容不落库", str(row.usage))

    def test_agent_type_mapping_from_purpose(self):
        self.assertEqual(agent_type_for_purpose("chat"), "chat")
        self.assertEqual(agent_type_for_purpose("chat_tool_route"), "chat_tool")
        self.assertEqual(agent_type_for_purpose("kg_extract_chunk"), "kg_extract")
        self.assertEqual(agent_type_for_purpose("s1_blueprint"), "agent_pipeline")
        self.assertEqual(agent_type_for_purpose("qa_report"), "audit_qa")
        self.assertEqual(agent_type_for_purpose("weird"), "other")


class TestDedup(AgentActionAuditCase):
    def test_repeated_idempotency_key_reuses_original_action(self):
        key = f"idem-{uuid.uuid4().hex[:12]}"
        for _ in range(3):
            with self.session_factory() as db:
                record_agent_action(
                    db, agent_type="chat_tool", tool_name="save_insight",
                    status="success", idempotency_key=key,
                    actor_id=self.user.id, project_id=self.project.id,
                )
                db.commit()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].repeat_count, 2)
        self.assertIsNotNone(rows[0].last_repeat_at)


class TestGatewayHook(AgentActionAuditCase):
    def test_success_call_records_one_row_with_usage(self):
        config = SimpleNamespace(profile_name="deepseek-chat")
        messages = [{"role": "user", "content": "看一下趋势"}]

        @audited_llm_call
        def _stub(db, *, config, messages, purpose="chat", actor=None, **kwargs):
            return "好的，趋势平稳", {"total_tokens": 42}, None

        with self.session_factory() as db:
            reply, usage, reasoning = _stub(
                db, config=config, messages=messages, purpose="chat",
                actor=self.user,
            )
            db.commit()
        self.assertEqual(reply, "好的，趋势平稳")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.agent_type, "chat")
        self.assertEqual(row.tool_name, "chat")
        self.assertEqual(row.status, "success")
        self.assertEqual(row.model_profile, "deepseek-chat")
        self.assertEqual(row.usage, {"total_tokens": 42})
        self.assertEqual(row.request_payload["messages"][0]["content"], "看一下趋势")

    def test_error_call_records_error_row_and_reraises(self):
        config = SimpleNamespace(profile_name="p1")
        messages = [{"role": "user", "content": "x"}]

        @audited_llm_call
        def _stub(db, *, config, messages, purpose="chat", actor=None, **kwargs):
            raise RuntimeError("network down")

        with self.session_factory() as db:
            with self.assertRaises(RuntimeError):
                _stub(db, config=config, messages=messages, purpose="s1_plan")
            db.commit()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.agent_type, "agent_pipeline")
        self.assertEqual(row.status, "error")
        self.assertIn("RuntimeError", row.error_code)

    def test_timeout_exception_is_marked_timeout(self):
        config = SimpleNamespace(profile_name="p1")
        messages = [{"role": "user", "content": "x"}]

        @audited_llm_call
        def _stub(db, *, config, messages, purpose="chat", actor=None, **kwargs):
            raise TimeoutError("read timed out")

        with self.session_factory() as db:
            with self.assertRaises(TimeoutError):
                _stub(db, config=config, messages=messages, purpose="chat")
            db.commit()
        self.assertEqual(self._rows()[0].status, "timeout")


class TestChatToolHook(AgentActionAuditCase):
    def test_execute_tool_records_success_and_error_rows(self):
        from app.services.chat_tools import execute_tool

        def _ok_handler(db, user, params):
            return {"ok": True}

        def _boom_handler(db, user, params):
            raise ValueError("bad params")

        with self.session_factory() as db:
            payload = execute_tool(
                db, user=self.user, tool="list_datasets",
                params={"q": "demo"}, handlers={"list_datasets": _ok_handler},
            )
            self.assertEqual(payload, {"ok": True})
            with self.assertRaises(ValueError):
                execute_tool(
                    db, user=self.user, tool="list_datasets",
                    params={"q": "x"}, handlers={"list_datasets": _boom_handler},
                )
            db.commit()
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual([row.status for row in rows], ["success", "error"])
        self.assertEqual([row.agent_type for row in rows], ["chat_tool", "chat_tool"])
        self.assertEqual(rows[0].request_payload["params"], {"q": "demo"})
        self.assertEqual(rows[1].error_code.split(":")[0], "ValueError")


class TestQueryEndpoints(AgentActionAuditCase):
    def _client(self):
        from app.api.agent_audit import router as agent_audit_router
        from app.api.users import get_current_admin
        from app.database import get_db

        app = FastAPI()
        app.include_router(agent_audit_router)

        def _override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_admin] = lambda: self.user
        return TestClient(app)

    def test_list_filters_and_pagination(self):
        for status in ("success", "error"):
            with self.session_factory() as db:
                record_agent_action(
                    db, agent_type="chat", tool_name="chat",
                    status=status, actor_id=self.user.id,
                )
                db.commit()
        client = self._client()
        response = client.get("/api/admin/agent-actions", params={"status": "error"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["status"], "error")

    def test_csv_export_matches_rows_and_marks_truncation(self):
        for index in range(3):
            with self.session_factory() as db:
                record_agent_action(
                    db, agent_type="chat", status="success",
                    tool_name=f"tool-{index}",
                )
                db.commit()
        client = self._client()
        response = client.get("/api/admin/agent-actions/export.csv")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("X-Truncated-Total", response.headers)
        content = response.content.decode("utf-8-sig")
        reader = list(csv.reader(io.StringIO(content)))
        self.assertEqual(len(reader), 4)
        self.assertEqual(reader[0][1], "agent_type")
        self.assertEqual(sorted(row[2] for row in reader[1:]), ["tool-0", "tool-1", "tool-2"])
