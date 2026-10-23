import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app
from tests.auth_test_support import ensure_admin


Base.metadata.create_all(bind=engine)


class TestWorkflowVersions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        # 运行工作流时 csv_import 会从进程 CWD 读取 file_path；测试须自带
        # 该文件（此前依赖开发者机器上的残留 sample.csv，CI 上不存在）。
        cls._sample_csv = Path("sample.csv")
        cls._sample_csv.write_text("f1,f2\n0.1,1.0\n0.2,1.1\n", encoding="utf-8")
        cls.addClassCleanup(cls._sample_csv.unlink, missing_ok=True)
        ensure_admin(username="version_admin")
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

    def test_04_delete_a_published_version(self):
        published = self.client.post(
            f"/api/workflows/{self.workflow_id}/publish", headers=self.headers,
        )
        self.assertEqual(published.status_code, 201)
        version_number = published.json()["version"]
        response = self.client.delete(
            f"/api/workflows/{self.workflow_id}/versions/{version_number}", headers=self.headers,
        )
        self.assertEqual(response.status_code, 204)
        versions = self.client.get(
            f"/api/workflows/{self.workflow_id}/versions", headers=self.headers,
        )
        self.assertNotIn(version_number, [item["version"] for item in versions.json()["items"]])


if __name__ == "__main__":
    unittest.main()
