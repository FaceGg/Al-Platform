"""Algorithm Catalog API integration tests."""
import sys, os, unittest
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app.models.algorithm import Algorithm

Base.metadata.create_all(bind=engine)
client = TestClient(app)


class TestAlgorithmAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = SessionLocal()
        if db.query(Algorithm).count() == 0:
            algs = [
                Algorithm(name="YOLOv8", display_name="YOLOv8目标检测", category="cv",
                          benchmark_mAP=0.892, is_active=True),
                Algorithm(name="resnet50", display_name="ResNet50分类", category="cv",
                          benchmark_mAP=0.851, is_active=True),
                Algorithm(name="xgboost_cls", display_name="XGBoost分类", category="ml",
                          benchmark_mAP=0.923, is_active=True),
            ]
            db.add_all(algs)
            db.commit()
        db.close()

    def test_01_list_all(self):
        r = client.get("/api/algorithms")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("items", data)
        self.assertGreaterEqual(len(data["items"]), 1)

    def test_02_filter_category(self):
        r = client.get("/api/algorithms?category=cv")
        self.assertEqual(r.status_code, 200)
        for item in r.json()["items"]:
            self.assertEqual(item["category"], "cv")

    def test_03_filter_status(self):
        r = client.get("/api/algorithms?status=active")
        self.assertEqual(r.status_code, 200)
        for item in r.json()["items"]:
            self.assertTrue(item["is_active"])

    def test_04_list_categories(self):
        r = client.get("/api/algorithms/categories")
        self.assertEqual(r.status_code, 200)
        self.assertIn("categories", r.json())

    def test_05_get_algorithm(self):
        r = client.get("/api/algorithms")
        items = r.json()["items"]
        if items:
            aid = items[0]["id"]
            r = client.get(f"/api/algorithms/{aid}")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["id"], aid)

    def test_06_get_nonexistent(self):
        import uuid
        r = client.get(f"/api/algorithms/{uuid.uuid4()}")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
