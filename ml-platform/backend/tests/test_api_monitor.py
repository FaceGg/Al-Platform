"""Monitor & Resource API integration tests."""
import sys, os, unittest
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


class TestMonitorAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        ensure_admin()
        cls.h = login()

    def test_01_current_metrics(self):
        r = client.get("/api/monitor/current", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("cpu", data)
        self.assertIn("memory", data)
        self.assertIn("disk", data)
        self.assertIn("timestamp", data)

    def test_02_cpu_metrics_format(self):
        r = client.get("/api/monitor/current", headers=self.h)
        cpu = r.json()["cpu"]
        self.assertIn("percent", cpu)
        self.assertIsInstance(cpu["percent"], (int, float))

    def test_03_memory_metrics_format(self):
        r = client.get("/api/monitor/current", headers=self.h)
        mem = r.json()["memory"]
        self.assertIn("total_bytes", mem)
        self.assertIn("used_bytes", mem)
        self.assertIn("percent", mem)

    def test_04_disk_metrics_format(self):
        r = client.get("/api/monitor/current", headers=self.h)
        disk = r.json()["disk"]
        self.assertIn("total", disk)
        self.assertIn("used", disk)
        self.assertIn("free", disk)
        self.assertIn("percent", disk)

    def test_04a_host_memory_and_disk_are_available_without_wmic(self):
        r = client.get("/api/monitor/current", headers=self.h)
        data = r.json()
        self.assertGreater(data["memory"]["total_bytes"], 0)
        self.assertGreater(data["disk"]["total"], 0)

    def test_05_gpu_metrics_format(self):
        r = client.get("/api/monitor/current", headers=self.h)
        self.assertIn("gpu", r.json())
        self.assertIsInstance(r.json()["gpu"], list)

    def test_06_history_metrics(self):
        r = client.get("/api/monitor/history?limit=10", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIsInstance(data, list)

    def test_07_history_default_limit(self):
        r = client.get("/api/monitor/history", headers=self.h)
        self.assertEqual(r.status_code, 200)

    def test_08_history_max_limit(self):
        r = client.get("/api/monitor/history?limit=120", headers=self.h)
        self.assertEqual(r.status_code, 200)

    def test_09_monitor_requires_auth(self):
        r = client.get("/api/monitor/current")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
