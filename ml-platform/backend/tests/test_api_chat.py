"""Chat API integration tests."""
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


class TestChatAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        ensure_admin()
        cls.h = login()

    def test_01_chat_status(self):
        r = client.get("/api/chat/status")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("configured", data)
        self.assertIn("model", data)

    def test_02_chat_without_api_key(self):
        """Chat should return error message when LLM not configured."""
        r = client.post("/api/chat", json={"message": "Hello"}, headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        data = r.json()
        self.assertIn("type", data)
        self.assertEqual(data["type"], "error")

    def test_03_chat_with_system_prompt(self):
        r = client.post("/api/chat", json={
            "message": "What is spot welding?",
            "system_prompt": "You are an expert in welding manufacturing.",
        }, headers=self.h)
        self.assertIn(r.status_code, [200, 201])

    def test_04_chat_empty_message(self):
        r = client.post("/api/chat", json={"message": ""}, headers=self.h)
        self.assertIn(r.status_code, [200, 201, 422])

    def test_05_chat_requires_auth(self):
        r = client.post("/api/chat", json={"message": "Hello"})
        self.assertEqual(r.status_code, 401)

    def test_06_chat_status_no_auth(self):
        r = client.get("/api/chat/status")
        self.assertEqual(r.status_code, 200)

    def test_07_chat_long_message(self):
        long_msg = "Tell me about " + "welding " * 200
        r = client.post("/api/chat", json={"message": long_msg}, headers=self.h)
        self.assertIn(r.status_code, [200, 201])

    def _create_kb_with_doc(self, name):
        r = client.post("/api/knowledge/bases", json={"name": name, "description": "chat kb test"}, headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        kb_id = r.json()["id"]
        r = client.post(
            f"/api/knowledge/bases/{kb_id}/documents",
            data={"content": "点焊是一种电阻焊。点焊质量取决于焊接电流与电极压力。"},
            headers=self.h,
        )
        self.assertIn(r.status_code, [200, 201])
        return kb_id

    def test_08_chat_with_kb_returns_sources_even_without_llm_key(self):
        from app.config import settings
        if settings.llm_api_key:
            self.skipTest("LLM_API_KEY configured in this environment")
        kb_id = self._create_kb_with_doc("ChatKBBound")
        try:
            r = client.post("/api/chat", json={
                "message": "点焊质量取决于什么？",
                "kb_id": kb_id,
                "top_k": 3,
            }, headers=self.h)
            self.assertEqual(r.status_code, 200)
            data = r.json()
            # Retrieval happens before the LLM call, so sources are present
            # even though the reply itself is the not-configured error.
            self.assertEqual(data["type"], "error")
            self.assertIsInstance(data.get("sources"), list)
            self.assertGreaterEqual(len(data["sources"]), 1)
            self.assertIn("点焊", data["sources"][0]["content"])
            self.assertEqual(data["kb"]["id"], kb_id)
            self.assertTrue(data["kb"]["name"])
        finally:
            client.delete(f"/api/knowledge/bases/{kb_id}", headers=self.h)

    def test_09_chat_with_unknown_kb_404(self):
        r = client.post("/api/chat", json={
            "message": "hello",
            "kb_id": "00000000-0000-0000-0000-000000000000",
        }, headers=self.h)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["detail"]["code"], "KNOWLEDGE_BASE_NOT_FOUND")

    def test_10_chat_stream_with_kb_emits_sources_first(self):
        from app.config import settings
        if settings.llm_api_key:
            self.skipTest("LLM_API_KEY configured in this environment")
        kb_id = self._create_kb_with_doc("ChatKBStream")
        try:
            with client.stream("POST", "/api/chat/stream", json={
                "message": "点焊质量取决于什么？",
                "kb_id": kb_id,
            }, headers=self.h) as response:
                self.assertEqual(response.status_code, 200)
                body = "".join(chunk for chunk in response.iter_text())
            self.assertIn("sources", body)
            self.assertIn("点焊", body)
            self.assertIn("LLM not configured", body)
        finally:
            client.delete(f"/api/knowledge/bases/{kb_id}", headers=self.h)

    def test_11_chat_without_kb_unchanged_contract(self):
        r = client.post("/api/chat", json={"message": "Hello", "kb_id": None}, headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        data = r.json()
        self.assertIn("type", data)
        self.assertNotIn("kb", data)
        self.assertNotIn("sources", data)

    def test_12_chat_with_empty_kb_degrades_to_plain_llm(self):
        """KB with no documents yields no sources: warning set, LLM still called."""
        r = client.post("/api/knowledge/bases", json={"name": "ChatKBEmpty", "description": ""}, headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        kb_id = r.json()["id"]
        try:
            r = client.post("/api/chat", json={"message": "hello", "kb_id": kb_id}, headers=self.h)
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertEqual(data["type"], "error")  # LLM key absent in test env
            self.assertEqual(data.get("sources"), [])
            self.assertTrue(data.get("kb_warning"))
        finally:
            client.delete(f"/api/knowledge/bases/{kb_id}", headers=self.h)

    def test_13_chat_attachments_invalid_kind_rejected(self):
        """附件契约：kind 不在 image/text → 422，不静默丢弃。"""
        r = client.post("/api/chat", json={
            "message": "hello",
            "attachments": [{"name": "a.exe", "kind": "binary", "data": "xx"}],
        }, headers=self.h)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["detail"]["code"], "ATTACHMENT_INVALID")

    def test_14_chat_attachments_image_requires_data_url(self):
        """图片附件必须是 data:image/* data URL。"""
        r = client.post("/api/chat", json={
            "message": "hello",
            "attachments": [{"name": "a.png", "kind": "image", "data": "http://example.com/a.png"}],
        }, headers=self.h)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["detail"]["code"], "ATTACHMENT_INVALID")

    def test_15_chat_attachments_text_too_large_rejected(self):
        r = client.post("/api/chat", json={
            "message": "hello",
            "attachments": [{"name": "big.txt", "kind": "text", "data": "x" * 80001}],
        }, headers=self.h)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["detail"]["code"], "ATTACHMENT_TOO_LARGE")


class TestAssembleMessagesAttachments(unittest.TestCase):
    """附件组装：文本拼进问题、图片走 OpenAI 多模态 content 数组。"""

    def _assemble(self, attachments):
        from app.api.chat import _assemble_messages
        return _assemble_messages("sys", "问题", None, None, attachments)

    def test_text_attachment_quoted_into_question(self):
        messages = self._assemble([{"name": "note.txt", "kind": "text", "data": "扭矩数据异常"}])
        self.assertEqual(len(messages), 2)
        content = messages[-1]["content"]
        self.assertIsInstance(content, str)
        self.assertIn("[附件 note.txt]", content)
        self.assertIn("扭矩数据异常", content)
        self.assertIn("问题", content)

    def test_image_attachment_builds_multimodal_content(self):
        data_url = "data:image/png;base64,aGVsbG8="
        messages = self._assemble([{"name": "weld.png", "kind": "image", "data": data_url}])
        content = messages[-1]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[0], {"type": "text", "text": "问题"})
        self.assertEqual(content[1], {"type": "image_url", "image_url": {"url": data_url}})

    def test_mixed_attachments_keep_order_and_text_join(self):
        messages = self._assemble([
            {"name": "a.txt", "kind": "text", "data": "AAA"},
            {"name": "b.png", "kind": "image", "data": "data:image/png;base64,Qg=="},
            {"name": "c.txt", "kind": "text", "data": "CCC"},
        ])
        content = messages[-1]["content"]
        self.assertIsInstance(content, list)
        self.assertIn("[附件 a.txt]\nAAA", content[0]["text"])
        self.assertIn("[附件 c.txt]\nCCC", content[0]["text"])
        self.assertEqual(content[1]["type"], "image_url")

    def test_no_attachments_keeps_plain_string(self):
        messages = self._assemble([])
        self.assertEqual(messages[-1]["content"], "问题")


if __name__ == "__main__":
    unittest.main()
