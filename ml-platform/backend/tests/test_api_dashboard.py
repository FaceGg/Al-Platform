"""Dashboard API integration tests."""
import sys, os, unittest
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

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


if __name__ == "__main__":
    unittest.main()
