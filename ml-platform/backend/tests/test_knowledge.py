"""Knowledge base, vector store, and template tests."""
import sys, os, unittest
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.api.knowledge import normalize_chat_messages
from app.database import Base, engine
from tests.auth_test_support import ensure_admin
from app.services.security import rate_limiter

Base.metadata.create_all(bind=engine)
client = TestClient(app)

# Ensure admin exists for fresh DB
ensure_admin()


def login_headers():
    rate_limiter().clear()
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestKnowledgeAPI(unittest.TestCase):
    def test_chat_messages_strip_internal_ids_and_accept_legacy_shape(self):
        normalized = normalize_chat_messages({
            "chat_id": "session-1",
            "message": "How much current?",
            "history": [{
                "id": "fc_087e6e046878738d016a84fcf0022087d095864ef8775a5ed8",
                "role": "assistant",
                "content": "Use the process specification.",
                "sources": [{"id": "fc_source"}],
            }],
        })

        self.assertEqual(normalized["session_id"], "session-1")
        self.assertEqual(
            normalized["messages"],
            [
                {"role": "assistant", "content": "Use the process specification."},
                {"role": "user", "content": "How much current?"},
            ],
        )

    def test_01_create_kb(self):
        h = login_headers()
        r = client.post("/api/knowledge/bases", json={
            "name": "WeldKB", "description": "Welding KB",
        }, headers=h)
        self.assertIn(r.status_code, [200, 201])
        self.__class__.kb_id = r.json()["id"]

    def test_02_list_kbs(self):
        r = client.get("/api/knowledge/bases", headers=login_headers())
        self.assertEqual(r.status_code, 200)

    def test_03_upload_and_search(self):
        h = login_headers()
        r = client.post("/api/knowledge/bases", json={
            "name": "SearchKB", "description": "Search test",
        }, headers=h)
        kbid = r.json()["id"]
        r = client.post(f"/api/knowledge/bases/{kbid}/documents", data={
            "title": "Weld Params", "content": "Optimal current is 8-12 kA for spot welding.",
        }, headers=h)
        self.assertIn(r.status_code, [200, 201])
        r = client.post(f"/api/knowledge/bases/{kbid}/vectorize",
                        json={"chunk_size": 500}, headers=h)
        self.assertIn(r.status_code, [200, 201])
        r = client.post(f"/api/knowledge/bases/{kbid}/search",
                        json={"query": "welding current"}, headers=h)
        self.assertEqual(r.status_code, 200)
        client.delete(f"/api/knowledge/bases/{kbid}", headers=h)

    def test_03b_upload_and_delete_document_use_canonical_routes(self):
        h = login_headers()
        kb = client.post("/api/knowledge/bases", json={"name": "Document route test"}, headers=h).json()
        uploaded = client.post(
            f"/api/knowledge/bases/{kb['id']}/documents",
            files={"file": ("weld.txt", b"Spot welding process knowledge.", "text/plain")},
            headers=h,
        )
        self.assertEqual(uploaded.status_code, 200)
        deleted = client.delete(f"/api/knowledge/documents/{uploaded.json()['id']}", headers=h)
        self.assertEqual(deleted.status_code, 200)
        client.delete(f"/api/knowledge/bases/{kb['id']}", headers=h)

    def test_03c_list_bases_returns_document_count(self):
        h = login_headers()
        kb = client.post(
            "/api/knowledge/bases",
            json={"name": "Document count test"},
            headers=h,
        ).json()
        uploaded = client.post(
            f"/api/knowledge/bases/{kb['id']}/documents",
            data={"title": "Weld document", "content": "Spot welding knowledge."},
            headers=h,
        )
        self.assertEqual(uploaded.status_code, 200)

        listed = client.get("/api/knowledge/bases", headers=h)
        self.assertEqual(listed.status_code, 200)
        item = next(entry for entry in listed.json() if entry["id"] == kb["id"])
        self.assertEqual(item["document_count"], 1)

        client.delete(f"/api/knowledge/bases/{kb['id']}", headers=h)

    def test_04_add_entity_and_graph(self):
        h = login_headers()
        r = client.post("/api/knowledge/bases", json={
            "name": "GraphKB", "description": "Graph test",
        }, headers=h)
        kbid = r.json()["id"]
        r = client.post(f"/api/knowledge/bases/{kbid}/graph/entities",
                        json={"name": "SpotWeld", "type": "process"}, headers=h)
        self.assertIn(r.status_code, [200, 201])
        r = client.get(f"/api/knowledge/bases/{kbid}/graph/entities", headers=h)
        self.assertEqual(r.status_code, 200)
        client.delete(f"/api/knowledge/bases/{kbid}", headers=h)

    def test_05_reembed_recomputes_all_chunks(self):
        h = login_headers()
        r = client.post("/api/knowledge/bases", json={
            "name": "ReembedKB", "description": "reembed test",
        }, headers=h)
        kbid = r.json()["id"]
        try:
            r = client.post(f"/api/knowledge/bases/{kbid}/documents", data={
                "content": "点焊质量取决于焊接电流。点焊飞溅与电流过大有关。",
            }, headers=h)
            self.assertIn(r.status_code, [200, 201])
            r = client.post(f"/api/knowledge/bases/{kbid}/reembed", headers=h)
            self.assertEqual(r.status_code, 200)
            self.assertGreaterEqual(r.json()["reembedded"], 1)
            # Chinese retrieval works with jieba tokenization
            r = client.post(f"/api/knowledge/bases/{kbid}/search",
                            json={"query": "点焊 电流", "top_k": 3}, headers=h)
            self.assertEqual(r.status_code, 200)
            self.assertGreaterEqual(len(r.json()), 1)
        finally:
            client.delete(f"/api/knowledge/bases/{kbid}", headers=h)

    def test_06_graph_extract_creates_auto_layer_and_preserves_manual(self):
        h = login_headers()
        r = client.post("/api/knowledge/bases", json={
            "name": "ExtractKB", "description": "extract test",
        }, headers=h)
        kbid = r.json()["id"]
        try:
            for i in range(2):
                r = client.post(f"/api/knowledge/bases/{kbid}/documents", data={
                    "content": "点焊是一种电阻焊。点焊质量取决于焊接电流与电极压力。"
                               "焊接电流过大时点焊会产生飞溅。电极压力影响点焊强度。",
                }, headers=h)
                self.assertIn(r.status_code, [200, 201])
            # Manual entity created before extraction must survive it.
            r = client.post(f"/api/knowledge/bases/{kbid}/graph/entities",
                            json={"name": "手动实体", "type": "manual"}, headers=h)
            self.assertIn(r.status_code, [200, 201])

            r = client.post(f"/api/knowledge/bases/{kbid}/graph/extract", headers=h)
            self.assertEqual(r.status_code, 200, r.text)
            report = r.json()
            self.assertGreaterEqual(report["entities_created"], 2)
            self.assertGreaterEqual(report["relations_created"], 1)

            r = client.get(f"/api/knowledge/bases/{kbid}/graph/entities", headers=h)
            entities = r.json()
            names = [e["name"] for e in entities]
            self.assertIn("手动实体", names)
            auto = [e for e in entities if (e.get("properties") or {}).get("source") == "auto"]
            self.assertGreaterEqual(len(auto), 2)
            self.assertTrue(all("freq" in (e.get("properties") or {}) for e in auto))

            # Re-run is idempotent for the auto layer; manual rows survive again.
            r = client.post(f"/api/knowledge/bases/{kbid}/graph/extract", headers=h)
            self.assertEqual(r.status_code, 200)
            r = client.get(f"/api/knowledge/bases/{kbid}/graph/entities", headers=h)
            names_after = [e["name"] for e in r.json()]
            self.assertEqual(names_after.count("手动实体"), 1)

            # Graph endpoint returns properties for source badges
            r = client.get(f"/api/knowledge/bases/{kbid}/graph", headers=h)
            graph = r.json()
            self.assertTrue(all("properties" in n for n in graph["nodes"]))
        finally:
            client.delete(f"/api/knowledge/bases/{kbid}", headers=h)

    def test_07_graph_extract_requires_documents(self):
        h = login_headers()
        r = client.post("/api/knowledge/bases", json={
            "name": "ExtractEmptyKB", "description": "extract empty",
        }, headers=h)
        kbid = r.json()["id"]
        try:
            r = client.post(f"/api/knowledge/bases/{kbid}/graph/extract", headers=h)
            self.assertEqual(r.status_code, 422)
        finally:
            client.delete(f"/api/knowledge/bases/{kbid}", headers=h)

    def test_08_graph_extract_caps_entities_and_flags_truncation(self):
        from unittest import mock
        from app.config import settings
        h = login_headers()
        r = client.post("/api/knowledge/bases", json={
            "name": "ExtractCapKB", "description": "extract cap",
        }, headers=h)
        kbid = r.json()["id"]
        try:
            for i in range(2):
                r = client.post(f"/api/knowledge/bases/{kbid}/documents", data={
                    "content": "点焊是一种电阻焊。点焊质量取决于焊接电流与电极压力。"
                               "焊接电流过大时点焊会产生飞溅。电极压力影响点焊强度。",
                }, headers=h)
                self.assertIn(r.status_code, [200, 201])
            with mock.patch.object(settings, "knowledge_graph_max_entities", 2):
                r = client.post(f"/api/knowledge/bases/{kbid}/graph/extract", headers=h)
            self.assertEqual(r.status_code, 200)
            report = r.json()
            self.assertLessEqual(report["entities_created"], 2)
            self.assertTrue(report["truncated"])
        finally:
            client.delete(f"/api/knowledge/bases/{kbid}", headers=h)

    def test_09_graph_extract_rejects_oversized_selection(self):
        from unittest import mock
        from app.config import settings
        h = login_headers()
        r = client.post("/api/knowledge/bases", json={
            "name": "ExtractBigKB", "description": "extract oversize",
        }, headers=h)
        kbid = r.json()["id"]
        try:
            r = client.post(f"/api/knowledge/bases/{kbid}/documents", data={
                "content": "点焊质量取决于焊接电流。" * 50,
            }, headers=h)
            self.assertIn(r.status_code, [200, 201])
            with mock.patch.object(settings, "knowledge_graph_max_extract_chars", 100):
                r = client.post(f"/api/knowledge/bases/{kbid}/graph/extract", headers=h)
            self.assertEqual(r.status_code, 422)
            self.assertIn("char", r.json()["detail"])
        finally:
            client.delete(f"/api/knowledge/bases/{kbid}", headers=h)


class TestTemplatesAPI(unittest.TestCase):
    def test_list_templates(self):
        r = client.get("/api/templates", headers=login_headers())
        self.assertEqual(r.status_code, 200)
        items = r.json()["items"]
        self.assertGreaterEqual(len(items), 7)
        template_ids = [t["id"] for t in items]
        self.assertIn("weld_quality", template_ids)
        self.assertIn("condition_branch", template_ids)
        self.assertIn("loop_optimize", template_ids)
        self.assertIn("multi_agent_quality", template_ids)

    def test_get_template(self):
        r = client.get("/api/templates/condition_branch", headers=login_headers())
        self.assertEqual(r.status_code, 200)
        self.assertIn("nodes", r.json())

    def test_instantiate_template(self):
        h = login_headers()
        r = client.post("/api/projects", json={"name": "TplTest"}, headers=h)
        self.assertIn(r.status_code, [200, 201])
        pid = r.json()["id"]
        r = client.post(f"/api/templates/loop_optimize/instantiate?project_id={pid}", headers=h)
        self.assertIn(r.status_code, [200, 201])
        self.assertIn("workflow_id", r.json())


if __name__ == "__main__":
    unittest.main()
