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


class TestExtractCache(unittest.TestCase):
    """三种供应商 usage 形态的缓存命中提取；anthropic 分母含缓存读+写。"""

    def test_deepseek_openai_form(self):
        from app.api.chat_stream import _extract_cache

        out = _extract_cache({
            "prompt_tokens": 1000, "completion_tokens": 50,
            "prompt_cache_hit_tokens": 640, "prompt_cache_miss_tokens": 360,
        })
        self.assertEqual(out, {"hit": 640, "prompt": 1000})

    def test_openai_details_form(self):
        from app.api.chat_stream import _extract_cache

        out = _extract_cache({
            "prompt_tokens": 500, "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 128},
        })
        self.assertEqual(out, {"hit": 128, "prompt": 500})

    def test_anthropic_form_denominator_includes_cache(self):
        """input_tokens 不含缓存读/写：分母 = hit + creation + input。
        （976% 荒谬值根因：曾只拿 input 当分母）"""
        from app.api.chat_stream import _extract_cache

        out = _extract_cache({
            "input_tokens": 354, "output_tokens": 200,
            "cache_read_input_tokens": 3540, "cache_creation_input_tokens": 100,
        })
        self.assertEqual(out, {"hit": 3540, "prompt": 3994})

    def test_hit_clamped_to_total(self):
        from app.api.chat_stream import _extract_cache

        out = _extract_cache({"prompt_tokens": 100, "prompt_cache_hit_tokens": 300})
        self.assertEqual(out["hit"], 100)

    def test_no_cache_fields_returns_none(self):
        from app.api.chat_stream import _extract_cache

        self.assertIsNone(_extract_cache({"prompt_tokens": 10, "completion_tokens": 2}))
        self.assertIsNone(_extract_cache("not-a-dict"))


if __name__ == "__main__":
    unittest.main()
