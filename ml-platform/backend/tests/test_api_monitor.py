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

    def test_04b_load_metrics_format(self):
        r = client.get("/api/monitor/current", headers=self.h)
        load = r.json()["load"]
        self.assertIn("load1", load)
        self.assertIn("load5", load)
        self.assertIn("load15", load)
        self.assertGreaterEqual(load["cpu_cores"], 1)
        for key in ("load1", "load5", "load15"):
            self.assertIsInstance(load[key], (int, float))
            self.assertGreaterEqual(load[key], 0)

    def test_04c_network_io_counters_are_cumulative_bytes(self):
        r = client.get("/api/monitor/current", headers=self.h)
        net = r.json()["net"]
        self.assertIn("rx_bytes", net)
        self.assertIn("tx_bytes", net)
        self.assertGreaterEqual(net["rx_bytes"], 0)
        self.assertGreaterEqual(net["tx_bytes"], 0)

    def test_04d_disk_io_counters_are_cumulative_bytes(self):
        r = client.get("/api/monitor/current", headers=self.h)
        disk_io = r.json()["disk_io"]
        self.assertIn("read_bytes", disk_io)
        self.assertIn("write_bytes", disk_io)
        self.assertGreaterEqual(disk_io["read_bytes"], 0)
        self.assertGreaterEqual(disk_io["write_bytes"], 0)

    def test_04e_uptime_is_non_negative_seconds(self):
        r = client.get("/api/monitor/current", headers=self.h)
        self.assertIsInstance(r.json()["uptime_seconds"], int)
        self.assertGreaterEqual(r.json()["uptime_seconds"], 0)

    def test_04f_history_includes_extended_metrics(self):
        r = client.get("/api/monitor/history", headers=self.h, params={"limit": 5})
        self.assertEqual(r.status_code, 200)
        items = r.json()
        self.assertIsInstance(items, list)
        for snapshot in items:
            self.assertIn("net", snapshot)
            self.assertIn("disk_io", snapshot)
            self.assertIn("load", snapshot)
            self.assertIn("uptime_seconds", snapshot)

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
