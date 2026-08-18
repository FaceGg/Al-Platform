"""Knowledge base, vector store, and template tests."""
import sys, os, unittest
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine
from tests.auth_test_support import ensure_admin

Base.metadata.create_all(bind=engine)
client = TestClient(app)

# Ensure admin exists for fresh DB
ensure_admin()


def login_headers():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestKnowledgeAPI(unittest.TestCase):
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
