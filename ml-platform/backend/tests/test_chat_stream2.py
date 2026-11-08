"""流式端点 /api/chat/stream2 测试（编排前置/参数校验/事件协议）。"""
import json
import sys, os, unittest
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine
from tests.auth_test_support import ensure_admin

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            events.append(json.loads(data))
        except ValueError:
            pass
    return events


class TestChatStream2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()

    def test_01_requires_auth(self):
        r = client.post("/api/chat/stream2", json={"message": "hi"})
        self.assertEqual(r.status_code, 401)

    def test_02_invalid_attachment_rejected(self):
        r = client.post("/api/chat/stream2", json={
            "message": "hi",
            "attachments": [{"name": "a.bin", "kind": "binary", "data": "xx"}],
        }, headers=self.h)
        self.assertEqual(r.status_code, 422)

    def test_03_no_key_yields_error_event_then_done(self):
        """无可用 LLM key → error 事件（含可读信息）+ [DONE] 哨兵。"""
        from app.config import settings
        if settings.llm_api_key:
            self.skipTest("LLM_API_KEY configured in this environment")
        r = client.post("/api/chat/stream2", json={"message": "hello"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/event-stream", r.headers.get("content-type", ""))
        events = parse_sse(r.text)
        kinds = [e.get("type") for e in events]
        self.assertIn("error", kinds)
        self.assertTrue(r.text.rstrip().endswith("[DONE]"))

    def test_04_tool_orchestration_short_circuits_as_reply_event(self):
        """编排命中 → 一次性 reply 事件（带 tool_call），无 delta。"""
        from unittest import mock

        from app.services.chat_tool_orchestrator import ToolOrchestration

        outcome = ToolOrchestration(
            "done", "测试摘要", {"tool": "list_datasets", "status": "done", "ok": True},
        )
        # patch 使用方命名空间（chat_stream 模块级绑定的引用）
        with mock.patch(
            "app.services.chat_tool_orchestrator.orchestrate", return_value=outcome,
        ), mock.patch(
            "app.api.chat_stream.resolve_profile",
        ) as profile_mock:
            profile_mock.side_effect = lambda db, **kw: mock.MagicMock(
                api_key="sk-test", provider="openai_compatible", timeout_seconds=30,
            )
            r = client.post("/api/chat/stream2", json={"message": "查点焊项目的数据集"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        events = parse_sse(r.text)
        reply_events = [e for e in events if e.get("type") == "reply"]
        self.assertEqual(len(reply_events), 1)
        self.assertEqual(reply_events[0]["text"], "测试摘要")
        self.assertEqual(reply_events[0]["tool_call"]["tool"], "list_datasets")
        self.assertNotIn("delta", [e.get("type") for e in events])
        self.assertTrue(r.text.rstrip().endswith("[DONE]"))


if __name__ == "__main__":
    unittest.main()
