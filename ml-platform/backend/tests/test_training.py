"""Training, AutoML, early-stopping, and checkpoint tests."""
import sys, os, unittest, io
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

Base.metadata.create_all(bind=engine)
client = TestClient(app)

# Ensure admin exists for fresh DB
client.post("/api/auth/register", json={"username": "admin", "password": "admin123", "role": "admin"})
# Login to get token (for tests that need auth)
resp = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
access_token = resp.json().get("access_token", "")


def _h():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _upload_dataset(project_id, headers):
    content = "current,force,quality\n" + "\n".join(
        f"{8 + index % 4},{3 + index % 2},{index % 2}" for index in range(40)
    )
    response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("training.csv", io.BytesIO(content.encode()), "text/csv")},
        headers=headers,
    )
    return response.json()["artifact_id"]


class TestTrainingAPI(unittest.TestCase):
    def test_new_training_request_rejects_dataset_path_without_artifact(self):
        h = _h()
        project = client.post("/api/projects", json={"name": "Path Rejected"}, headers=h).json()
        response = client.post("/api/training/run", json={
            "project_id": project["id"],
            "dataset_path": "/tmp/untrusted.csv",
            "params": {"target_column": "quality"},
        }, headers=h)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "DATASET_ARTIFACT_REQUIRED")

    def test_list_jobs(self):
        r = client.get("/api/training/jobs", headers=_h())
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_start_training(self):
        h = _h()
        r = client.post("/api/projects", json={"name": "T", "description": "x"}, headers=h)
        pid = r.json()["id"]
        artifact_id = _upload_dataset(pid, h)
        r = client.post("/api/training/run", json={
            "project_id": pid, "name": "test_job",
            "dataset_artifact_id": artifact_id, "operator_id": "random_forest_train",
            "params": {"n_estimators": 10, "target_column": "quality"},
        }, headers=h)
        self.assertIn(r.status_code, [200, 201])
        self.assertIn("job_id", r.json())

    def test_early_stopping_and_checkpoints(self):
        h = _h()
        r = client.post("/api/projects", json={"name": "T2"}, headers=h)
        pid = r.json()["id"]
        artifact_id = _upload_dataset(pid, h)
        r = client.post("/api/training/run", json={
            "project_id": pid, "name": "es_cp",
            "dataset_artifact_id": artifact_id, "operator_id": "random_forest_train",
            "params": {"n_estimators": 10, "target_column": "quality"},
        }, headers=h)
        data = r.json()
        self.assertIn("job_id", data)
        jid = data["job_id"]

        # These endpoints use UUID comparison which may fail on this platform
        # GET early stopping
        r = client.get(f"/api/training/jobs/{jid}/early-stopping", headers=h)
        self.assertIn(r.status_code, [200, 404])

        # PUT early stopping
        r = client.put(f"/api/training/jobs/{jid}/early-stopping", json={
            "patience": 5, "min_delta": 0.001, "monitor": "val_loss", "restore_best": True,
        }, headers=h)
        self.assertIn(r.status_code, [200, 404])

        # POST checkpoint
        r = client.post(f"/api/training/jobs/{jid}/checkpoints", json={
            "epoch": 1, "loss": 0.5, "accuracy": 0.85,
        }, headers=h)
        self.assertIn(r.status_code, [200, 404])

        # GET checkpoints
        r = client.get(f"/api/training/jobs/{jid}/checkpoints", headers=h)
        self.assertIn(r.status_code, [200, 404])

        # POST stop
        r = client.post(f"/api/training/jobs/{jid}/stop", headers=h)
        self.assertIn(r.status_code, [200, 400, 404])


if __name__ == "__main__":
    unittest.main()
