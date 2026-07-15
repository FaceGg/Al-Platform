"""Workflows API integration tests."""
import sys, os, unittest, uuid
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestWorkflowsCRUD(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        client.post("/api/auth/register", json={"username": "admin", "password": "admin123", "role": "admin"})
        cls.h = login()
        r = client.post("/api/projects", json={"name": "WF_Test_Project"}, headers=cls.h)
        if r.status_code == 201:
            cls.project_id = r.json()["id"]
        else:
            r = client.get("/api/projects", headers=cls.h)
            cls.project_id = r.json()["items"][0]["id"]
        cls.workflow_ids = []

    def test_01_create_empty_workflow(self):
        wf = {"name": "Empty WF", "nodes": [], "edges": []}
        r = client.post(f"/api/projects/{self.project_id}/workflows", json=wf, headers=self.h)
        self.assertEqual(r.status_code, 201)
        self.__class__.workflow_ids.append(r.json()["id"])

    def test_02_create_second_empty_workflow(self):
        wf = {"name": "Second WF", "nodes": [], "edges": []}
        r = client.post(f"/api/projects/{self.project_id}/workflows", json=wf, headers=self.h)
        self.assertEqual(r.status_code, 201)
        self.__class__.workflow_ids.append(r.json()["id"])

    def test_03_list_workflows(self):
        r = client.get(f"/api/projects/{self.project_id}/workflows", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)
        self.assertGreaterEqual(len(r.json()), 2)

    def test_04_get_workflow(self):
        wfid = self.workflow_ids[0]
        r = client.get(f"/api/projects/{self.project_id}/workflows/{wfid}", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("nodes", data)
        self.assertIn("edges", data)

    def test_05_get_nonexistent_workflow(self):
        fake_id = str(uuid.uuid4())
        r = client.get(f"/api/projects/{self.project_id}/workflows/{fake_id}", headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_06_save_workflow_add_nodes(self):
        wfid = self.workflow_ids[0]
        wf = {
            "nodes": [
                {"id": "n1", "operator_id": "csv_import", "label": "Import",
                 "position": {"x": 50, "y": 50}, "params": {}},
                {"id": "n2", "operator_id": "scaler", "label": "Scale",
                 "position": {"x": 250, "y": 50}, "params": {"method": "standard"}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "source_port": "data", "target": "n2", "target_port": "data"},
            ],
        }
        r = client.put(f"/api/projects/{self.project_id}/workflows/{wfid}", json=wf, headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("nodes", data)
        self.assertEqual(len(data["nodes"]), 2)

    def test_07_save_nonexistent_workflow(self):
        fake_id = str(uuid.uuid4())
        wf = {"name": "X", "nodes": [], "edges": []}
        r = client.put(f"/api/projects/{self.project_id}/workflows/{fake_id}", json=wf, headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_08_delete_workflow(self):
        if len(self.workflow_ids) > 1:
            wfid = self.workflow_ids.pop()
            r = client.delete(f"/api/projects/{self.project_id}/workflows/{wfid}", headers=self.h)
            self.assertEqual(r.status_code, 204)
            r = client.get(f"/api/projects/{self.project_id}/workflows/{wfid}", headers=self.h)
            self.assertEqual(r.status_code, 404)

    def test_09_delete_nonexistent_workflow(self):
        r = client.delete(f"/api/projects/{self.project_id}/workflows/{uuid.uuid4()}", headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_10_list_workflows_invalid_project(self):
        r = client.get(f"/api/projects/{uuid.uuid4()}/workflows", headers=self.h)
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
