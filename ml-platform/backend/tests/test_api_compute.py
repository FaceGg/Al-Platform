"""Compute Resource & Edge Device API integration tests."""
import sys, os, unittest, uuid
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.api.auth import pwd_context
from app.database import Base, SessionLocal, engine
from app.models.user import User

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def ensure_admin():
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == "admin").first() is None:
            db.add(User(
                username="admin",
                password_hash=pwd_context.hash("admin123"),
                role="admin",
            ))
            db.commit()
    finally:
        db.close()


def login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestComputeAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()
        cls.node_ids = []
        cls.device_ids = []

    # ---- Compute Nodes ----
    def test_01_list_nodes_empty(self):
        r = client.get("/api/compute/nodes", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("items", data)
        self.assertIn("total", data)

    def test_02_create_gpu_node(self):
        r = client.post("/api/compute/nodes", json={
            "name": "GPU-Node-01",
            "node_type": "gpu",
            "purpose": "training",
            "cpu_cores": 32,
            "gpu_count": 4,
            "memory_gb": 256,
            "disk_gb": 2000,
            "ip_address": "192.168.1.100",
            "tags": ["gpu", "high-perf"],
        }, headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        self.__class__.node_ids.append(r.json()["id"])

    def test_03_create_cpu_node(self):
        r = client.post("/api/compute/nodes", json={
            "name": "CPU-Node-01",
            "node_type": "cpu",
            "purpose": "inference",
            "cpu_cores": 16,
            "memory_gb": 64,
            "disk_gb": 500,
        }, headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        self.__class__.node_ids.append(r.json()["id"])

    def test_04_list_nodes_with_data(self):
        r = client.get("/api/compute/nodes", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json()["total"], 2)

    def test_05_filter_nodes_by_purpose(self):
        r = client.get("/api/compute/nodes?purpose=training", headers=self.h)
        self.assertEqual(r.status_code, 200)
        for n in r.json()["items"]:
            self.assertEqual(n["purpose"], "training")

    def test_06_filter_nodes_by_status(self):
        r = client.get("/api/compute/nodes?status=available", headers=self.h)
        self.assertEqual(r.status_code, 200)

    def test_07_update_node(self):
        nid = self.node_ids[0]
        r = client.put(f"/api/compute/nodes/{nid}", json={
            "name": "GPU-Node-01-Updated",
            "status": "busy",
            "tags": ["gpu", "high-perf", "production"],
        }, headers=self.h)
        self.assertEqual(r.status_code, 200)

    def test_08_delete_node(self):
        if len(self.node_ids) > 1:
            nid = self.node_ids.pop()
            r = client.delete(f"/api/compute/nodes/{nid}", headers=self.h)
            self.assertEqual(r.status_code, 200)

    def test_09_nonexistent_node_delete(self):
        r = client.delete(f"/api/compute/nodes/{uuid.uuid4()}", headers=self.h)
        self.assertIn(r.status_code, [200, 404, 204])

    def test_10_create_node_minimal(self):
        r = client.post("/api/compute/nodes", json={"name": "MinimalNode"}, headers=self.h)
        self.assertIn(r.status_code, [200, 201])

    # ---- Edge Devices ----
    def test_11_list_devices_empty(self):
        r = client.get("/api/compute/devices", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("items", data)

    def test_12_create_device(self):
        r = client.post("/api/compute/devices", json={
            "name": "Edge-Box-01",
            "device_type": "box",
            "ip_address": "10.0.0.50",
            "group_id": "factory-1",
            "config": {"model": "weld_quality_v1"},
        }, headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        self.__class__.device_ids.append(r.json()["id"])

    def test_13_list_devices_with_data(self):
        r = client.get("/api/compute/devices", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json()["total"], 1)

    def test_14_filter_devices_by_group(self):
        r = client.get("/api/compute/devices?group_id=factory-1", headers=self.h)
        self.assertEqual(r.status_code, 200)

    def test_15_compute_requires_auth(self):
        r = client.get("/api/compute/nodes")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
