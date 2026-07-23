"""Dashboard API integration tests."""
import sys, os, unittest, uuid
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine
from app.database import SessionLocal
from app.models.artifact import Artifact
from app.models.project import Project
from app.models.user import User

Base.metadata.create_all(bind=engine)
client = TestClient(app)


class TestDashboardAPI(unittest.TestCase):
    def test_01_dashboard_stats(self):
        r = client.get("/api/dashboard/stats")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        # Stats are nested under core_assets
        self.assertIn("core_assets", data)
        self.assertIn("total_algorithms", data["core_assets"])

    def test_02_dashboard_stats_business(self):
        r = client.get("/api/dashboard/stats")
        data = r.json()
        self.assertIn("business_stats", data)
        self.assertIn("total_projects", data["business_stats"])

    def test_03_dashboard_stats_models(self):
        r = client.get("/api/dashboard/stats")
        data = r.json()
        self.assertIn("model_status", data)

    def test_04_dashboard_algorithm_coverage(self):
        r = client.get("/api/dashboard/stats")
        data = r.json()
        self.assertIn("algorithm_coverage", data)

    def test_05_dashboard_stats_types(self):
        r = client.get("/api/dashboard/stats")
        data = r.json()
        self.assertIsInstance(data["core_assets"]["total_algorithms"], int)
        self.assertIsInstance(data["business_stats"]["total_projects"], int)
        self.assertIsInstance(data["algorithm_coverage"], list)

    def test_06_dataset_stats_include_artifact_datasets(self):
        before = client.get("/api/dashboard/stats").json()["core_assets"]["total_datasets"]
        with SessionLocal() as db:
            owner = User(username=f"dashboard-owner-{uuid.uuid4().hex}", password_hash="hash")
            db.add(owner)
            db.flush()
            project = Project(name=f"dashboard-project-{uuid.uuid4().hex}", owner_id=owner.id)
            db.add(project)
            db.flush()
            db.add(Artifact(
                project_id=project.id,
                name="dashboard-dataset.csv",
                type="dataset",
                storage_path="datasets/dashboard-dataset.csv",
                storage_uri="file:///datasets/dashboard-dataset.csv",
                file_size=16,
                format="csv",
            ))
            db.commit()

        after = client.get("/api/dashboard/stats").json()["core_assets"]["total_datasets"]
        self.assertGreaterEqual(after, before + 1)


if __name__ == "__main__":
    unittest.main()
