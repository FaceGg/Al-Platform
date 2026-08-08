"""Datasets API integration tests."""
import sys, os, unittest, uuid, io
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


class TestDatasetsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        ensure_admin()
        cls.h = login()
        r = client.post("/api/projects", json={"name": "DatasetTestProject"}, headers=cls.h)
        cls.project_id = r.json()["id"]
        cls.artifact_ids = []
        cls.csv_path = ""

    def _make_csv(self, content="col1,col2\n1,2\n3,4\n5,6\n"):
        return io.BytesIO(content.encode("utf-8"))

    def test_01_upload_csv_dataset(self):
        csv = self._make_csv()
        r = client.post(
            f"/api/projects/{self.project_id}/datasets/upload",
            files={"file": ("test.csv", csv, "text/csv")},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("id", data)
        self.assertEqual(data["artifact_id"], data["id"])
        self.assertEqual(data["row_count"], 3)
        self.assertEqual([column["name"] for column in data["schema"]], ["col1", "col2"])
        self.assertEqual(len(data["sha256"]), 64)
        self.__class__.artifact_ids.append(data["id"])

    def test_02_upload_second_csv(self):
        csv = self._make_csv("col1,col2\n10,20\n30,40\n50,60\n")
        r = client.post(
            f"/api/projects/{self.project_id}/datasets/upload",
            files={"file": ("test2.csv", csv, "text/csv")},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.__class__.artifact_ids.append(data["id"])

    def test_03_preview_dataset(self):
        aid = self.artifact_ids[0]
        r = client.get(f"/api/datasets/{aid}/preview", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("columns", data)
        self.assertIn("preview", data)
        self.assertIn("total_rows", data)

    def test_03a_list_project_dataset_artifacts(self):
        r = client.get(f"/api/projects/{self.project_id}/datasets", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreaterEqual(data["total"], 2)
        self.assertTrue(all(item["type"] == "dataset" for item in data["items"]))
        self.assertTrue(all(item["project_id"] == self.project_id for item in data["items"]))
        self.assertTrue(all("storage_path" not in item for item in data["items"]))

    def test_03b_list_all_owned_datasets_without_selecting_a_project(self):
        r = client.get("/api/datasets", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreaterEqual(data["total"], 2)
        self.assertTrue(all(item["type"] == "dataset" for item in data["items"]))
        self.assertTrue(all(item["project_id"] for item in data["items"]))

    def test_03c_delete_dataset_removes_the_owned_artifact(self):
        uploaded = client.post(
            f"/api/projects/{self.project_id}/datasets/upload",
            files={"file": ("delete-me.csv", self._make_csv(), "text/csv")},
            headers=self.h,
        )
        self.assertEqual(uploaded.status_code, 200)
        dataset_id = uploaded.json()["id"]
        response = client.delete(f"/api/datasets/{dataset_id}", headers=self.h)
        self.assertEqual(response.status_code, 204)
        preview = client.get(f"/api/datasets/{dataset_id}/preview", headers=self.h)
        self.assertEqual(preview.status_code, 404)

    def test_04_preview_nonexistent_dataset(self):
        r = client.get(f"/api/datasets/{uuid.uuid4()}/preview", headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_05_upload_to_nonexistent_project(self):
        csv = self._make_csv()
        r = client.post(
            f"/api/projects/{uuid.uuid4()}/datasets/upload",
            files={"file": ("test.csv", csv, "text/csv")},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 404)

    def test_06_upload_large_csv(self):
        """Upload a CSV with 500 rows."""
        csv = io.BytesIO(("col1,col2\n" + "\n".join(f"{i},{i*2}" for i in range(500))).encode("utf-8"))
        r = client.post(
            f"/api/projects/{self.project_id}/datasets/upload",
            files={"file": ("large.csv", csv, "text/csv")},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200)

    def test_07_export_dataset(self):
        r = client.get(f"/api/projects/{self.project_id}/datasets/export?format=csv", headers=self.h)
        self.assertIn(r.status_code, [200, 404])

    def test_08_batch_upload_datasets(self):
        csv1 = ("col1,col2\n1,2\n", "batch1.csv", "text/csv")
        csv2 = ("a,b\nx,y\n", "batch2.csv", "text/csv")
        files = [
            ("files", csv1),
            ("files", csv2),
        ]
        r = client.post(
            f"/api/projects/{self.project_id}/datasets/batch",
            files=files,
            headers=self.h,
        )
        self.assertIn(r.status_code, [200, 201])
        if r.status_code == 200:
            data = r.json()
            self.assertIn("success", data)


if __name__ == "__main__":
    unittest.main()
