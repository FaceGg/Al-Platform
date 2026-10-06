"""Published chat API tests: knowledge-base publication, remote invoke, lifecycle."""
import sys, os, unittest
from unittest import mock

sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine
from app.services.security import rate_limiter
from tests.auth_test_support import ensure_admin

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login(username="admin", password="admin123"):
    # Direct unittest runs do not load conftest, so keep the IP limiter clear.
    rate_limiter().clear()
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def create_kb(h, name):
    r = client.post("/api/knowledge/bases", json={"name": name, "description": "chat api test"}, headers=h)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def upload_doc(h, kb_id, content, filename="doc.txt"):
    r = client.post(
        f"/api/knowledge/bases/{kb_id}/documents",
        data={"content": content},
        files={"file": (filename, content.encode("utf-8"), "text/plain")},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


class TestChatAPIPublication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        ensure_admin("chatpub_other", "chatpub_other_pw")
        cls.h = login()
        cls.other = login(username="chatpub_other", password="chatpub_other_pw")

    def setUp(self):
        self.kb_id = create_kb(self.h, f"ChatPubKB-{self._testMethodName}")

    def tearDown(self):
        client.delete(f"/api/knowledge/bases/{self.kb_id}", headers=self.h)

    def test_01_publish_idempotent_and_listed_in_market(self):
        first = client.post(f"/api/platform/apis/publish/chat/{self.kb_id}", headers=self.h)
        self.assertIn(first.status_code, [200, 201])
        body = first.json()
        self.assertEqual(body["api_type"], "chat")
        self.assertEqual(body["source_kind"], "chat")
        self.assertEqual(body["status"], "published")
        self.assertTrue(body["endpoint"].endswith(f"/chat/{self.kb_id}/invoke"))

        second = client.post(f"/api/platform/apis/publish/chat/{self.kb_id}", headers=self.h)
        self.assertIn(second.status_code, [200, 201])
        self.assertEqual(second.json()["id"], body["id"])

        market = client.get("/api/platform/apis", headers=self.h)
        self.assertEqual(market.status_code, 200)
        items = market.json() if isinstance(market.json(), list) else market.json().get("items", [])
        self.assertTrue(any(a["id"] == body["id"] for a in items))

    def test_02_publish_requires_kb_ownership(self):
        r = client.post(f"/api/platform/apis/publish/chat/{self.kb_id}", headers=self.other)
        self.assertEqual(r.status_code, 404)

    def test_03_invoke_before_publish_404(self):
        r = client.post(f"/api/platform/apis/chat/{self.kb_id}/invoke", json={"message": "hi"}, headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_04_offline_invoke_409(self):
        client.post(f"/api/platform/apis/publish/chat/{self.kb_id}", headers=self.h)
        off = client.post(f"/api/platform/apis/publish/chat/{self.kb_id}/offline", headers=self.h)
        self.assertEqual(off.status_code, 200)
        r = client.post(f"/api/platform/apis/chat/{self.kb_id}/invoke", json={"message": "hi"}, headers=self.h)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["code"], "CHAT_API_OFFLINE")

    def test_05_invoke_invalid_message_422(self):
        client.post(f"/api/platform/apis/publish/chat/{self.kb_id}", headers=self.h)
        r = client.post(f"/api/platform/apis/chat/{self.kb_id}/invoke", json={"message": "   "}, headers=self.h)
        self.assertEqual(r.status_code, 422)

    def test_06_invoke_non_owner_404(self):
        client.post(f"/api/platform/apis/publish/chat/{self.kb_id}", headers=self.h)
        r = client.post(f"/api/platform/apis/chat/{self.kb_id}/invoke", json={"message": "hi"}, headers=self.other)
        self.assertEqual(r.status_code, 404)

    def test_07_invoke_llm_unconfigured_503_with_failed_stats(self):
        from app.config import settings
        if settings.llm_api_key:
            self.skipTest("LLM_API_KEY configured in this environment")
        client.post(f"/api/platform/apis/publish/chat/{self.kb_id}", headers=self.h)
        r = client.post(f"/api/platform/apis/chat/{self.kb_id}/invoke", json={"message": "点焊飞溅原因？"}, headers=self.h)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["detail"]["code"], "CHAT_LLM_NOT_CONFIGURED")
        detail = client.get("/api/platform/apis", headers=self.h)
        items = detail.json() if isinstance(detail.json(), list) else detail.json().get("items", [])
        row = next(a for a in items if a["source_kind"] == "chat" and a["source_id"] == self.kb_id)
        self.assertGreaterEqual(row["total_calls"], 1)
        self.assertGreaterEqual(row["failed_calls"], 1)

    def test_08_invoke_success_mocked_llm_returns_sources_and_counts(self):
        from app.config import settings
        upload_doc(self.h, self.kb_id, "点焊是一种电阻焊。点焊质量取决于焊接电流与电极压力。", filename="process.txt")
        published = client.post(f"/api/platform/apis/publish/chat/{self.kb_id}", headers=self.h)
        api_id = published.json()["id"]

        fake = mock.Mock()
        fake.raise_for_status = mock.Mock()
        fake.json.return_value = {
            "choices": [{"message": {"content": "点焊飞溅与电流过大有关 [1]。"}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 7},
        }
        with mock.patch("requests.post", return_value=fake) as llm_call, \
                mock.patch.object(settings, "llm_api_key", "test-key"):
            r = client.post(
                f"/api/platform/apis/chat/{self.kb_id}/invoke",
                json={"message": "点焊飞溅的原因？", "top_k": 3},
                headers=self.h,
            )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["reply"], "点焊飞溅与电流过大有关 [1]。")
        self.assertIn("点焊", llm_call.call_args.kwargs["json"]["messages"][1]["content"])
        self.assertEqual(body["usage"]["prompt_tokens"], 42)
        self.assertIsInstance(body["sources"], list)
        self.assertGreaterEqual(len(body["sources"]), 1)

        listing = client.get("/api/platform/apis", headers=self.h)
        items = listing.json() if isinstance(listing.json(), list) else listing.json().get("items", [])
        row = next(a for a in items if a["id"] == api_id)
        self.assertGreaterEqual(row["total_calls"], 1)
        self.assertGreaterEqual(row["success_calls"], 1)

    def test_09_delete_kb_takes_chat_api_offline_and_market_delete_allowed(self):
        published = client.post(f"/api/platform/apis/publish/chat/{self.kb_id}", headers=self.h)
        api_id = published.json()["id"]
        deleted = client.delete(f"/api/knowledge/bases/{self.kb_id}", headers=self.h)
        self.assertIn(deleted.status_code, [200, 204])

        def _row():
            listing = client.get("/api/platform/apis", headers=self.h)
            items = listing.json() if isinstance(listing.json(), list) else listing.json().get("items", [])
            return next(a for a in items if a["id"] == api_id)

        self.assertEqual(_row()["status"], "offline")
        r = client.post(f"/api/platform/apis/chat/{self.kb_id}/invoke", json={"message": "hi"}, headers=self.h)
        self.assertEqual(r.status_code, 409)

        market_delete = client.delete(f"/api/platform/apis/{api_id}", headers=self.h)
        self.assertEqual(market_delete.status_code, 200)

        # Recreate for tearDown cleanup path
        self.kb_id = create_kb(self.h, f"ChatPubKB-cleanup-{self._testMethodName}")


if __name__ == "__main__":
    unittest.main()
