import unittest

from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


Base.metadata.create_all(bind=engine)


class TestWorkflowVersions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        cls.client.post("/api/auth/register", json={
            "username": "version_admin", "password": "admin123", "role": "admin",
        })
        login = cls.client.post("/api/auth/login", data={
            "username": "version_admin", "password": "admin123",
        })
        cls.headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        project = cls.client.post("/api/projects", json={"name": "Version Project"}, headers=cls.headers)
        cls.project_id = project.json()["id"]
        workflow = cls.client.post(
            f"/api/projects/{cls.project_id}/workflows",
            json={"name": "Versioned Workflow", "nodes": [], "edges": []},
            headers=cls.headers,
        )
        cls.workflow_id = workflow.json()["id"]
        cls._save_draft("Original node")

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    @classmethod
    def _save_draft(cls, label):
        return cls.client.put(
            f"/api/workflows/{cls.workflow_id}",
            json={
                "name": "Versioned Workflow",
                "nodes": [{
                    "id": "source", "operator_id": "csv_import", "label": label,
                    "position": {"x": 10, "y": 20}, "params": {"file_path": "sample.csv"},
                }],
                "edges": [],
            },
            headers=cls.headers,
        )

    def test_01_publish_versions_are_incrementing_and_immutable(self):
        first = self.client.post(
            f"/api/workflows/{self.workflow_id}/publish", headers=self.headers,
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["version"], 1)

        self._save_draft("Changed node")
        second = self.client.post(
            f"/api/workflows/{self.workflow_id}/publish", headers=self.headers,
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()["version"], 2)

        detail = self.client.get(
            f"/api/workflows/{self.workflow_id}/versions/1", headers=self.headers,
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["nodes"][0]["label"], "Original node")

    def test_02_list_versions_and_restore_to_draft(self):
        versions = self.client.get(
            f"/api/workflows/{self.workflow_id}/versions", headers=self.headers,
        )
        self.assertEqual(versions.status_code, 200)
        self.assertEqual([item["version"] for item in versions.json()["items"]], [2, 1])

        restored = self.client.post(
            f"/api/workflows/{self.workflow_id}/versions/1/restore", headers=self.headers,
        )
        self.assertEqual(restored.status_code, 200)
        draft = self.client.get(f"/api/workflows/{self.workflow_id}", headers=self.headers)
        self.assertEqual(draft.json()["nodes"][0]["label"], "Original node")

    def test_03_run_records_matching_published_version(self):
        published = self.client.post(
            f"/api/workflows/{self.workflow_id}/publish", headers=self.headers,
        ).json()
        started = self.client.post(
            f"/api/workflows/{self.workflow_id}/run", headers=self.headers,
        )
        self.assertEqual(started.status_code, 201)
        detail = self.client.get(
            f"/api/runs/{started.json()['run_id']}", headers=self.headers,
        )
        self.assertEqual(detail.json()["workflow_version"], published["version"])


if __name__ == "__main__":
    unittest.main()
