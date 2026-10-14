"""Model Library API integration tests."""
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


class TestModelLibraryAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        ensure_admin()
        cls.h = login()
        cls.model_ids = []

    def test_01_list_models_empty(self):
        r = client.get("/api/model-library", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("items", data)
        self.assertIn("total", data)

    def test_02_create_model(self):
        r = client.post("/api/model-library", json={
            "name": "TestXGBoostModel",
            "framework": "xgboost",
            "backbone": "gbtree",
            "description": "Test model for spot welding",
            "version": "v1.0",
            "params": {"max_depth": 6, "n_estimators": 100},
            "tags": ["welding", "classification"],
        }, headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        data = r.json()
        self.assertIn("id", data)
        self.__class__.model_ids.append(data["id"])

    def test_03_list_models_has_items(self):
        r = client.get("/api/model-library", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreaterEqual(data["total"], 1)

    def test_04_get_model(self):
        mid = self.model_ids[0]
        r = client.get(f"/api/model-library/{mid}", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["name"], "TestXGBoostModel")
        self.assertEqual(data["framework"], "xgboost")

    def test_05_get_nonexistent_model(self):
        import uuid
        r = client.get(f"/api/model-library/{uuid.uuid4()}", headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_06_update_model(self):
        mid = self.model_ids[0]
        r = client.put(f"/api/model-library/{mid}", json={
            "name": "UpdatedXGBoostModel",
            "status": "completed",
            "progress": 1.0,
            "metrics": {"accuracy": 0.95, "mAP": 0.92},
            "is_public": True,
        }, headers=self.h)
        self.assertEqual(r.status_code, 200)

        r = client.get(f"/api/model-library/{mid}", headers=self.h)
        self.assertEqual(r.json()["status"], "completed")

    def test_07_create_second_model(self):
        r = client.post("/api/model-library", json={
            "name": "RandomForestModel",
            "framework": "sklearn",
            "backbone": "random_forest",
            "version": "v1.0",
            "params": {"n_estimators": 200},
        }, headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        self.__class__.model_ids.append(r.json()["id"])

    def test_08_delete_model(self):
        if len(self.model_ids) > 1:
            mid = self.model_ids.pop()
            r = client.delete(f"/api/model-library/{mid}", headers=self.h)
            self.assertEqual(r.status_code, 200)

    def test_09_model_stats(self):
        r = client.get("/api/model-library/stats/summary")
        self.assertIn(r.status_code, [200, 201])
        data = r.json()
        self.assertIn("total_models", data)
        self.assertIn("completed", data)

    def test_10_filter_by_status(self):
        r = client.get("/api/model-library?status=completed", headers=self.h)
        self.assertEqual(r.status_code, 200)

    def test_11_filter_by_framework(self):
        r = client.get("/api/model-library?framework=xgboost", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for item in data["items"]:
            self.assertEqual(item["framework"], "xgboost")

    def test_12_model_requires_auth(self):
        r = client.get("/api/model-library")
        self.assertEqual(r.status_code, 401)

    def test_13_stats_summary_top_models_sorted_by_best_score(self):
        # 回归：metrics 是 JSON 列，SQL 侧 order_by 在 PostgreSQL 直接报
        # "could not identify an ordering operator for type json"（sqlite
        # 按文本排掩盖了问题）。修复后 Python 侧按 best_score 降序。
        import uuid as _uuid

        from app.database import SessionLocal
        from app.models.model_library import ModelLibrary
        from app.models.project import Project
        from app.models.user import User

        marker = f"mlstats-{_uuid.uuid4().hex[:8]}"
        db = SessionLocal()
        try:
            owner_id = db.query(User.id).filter(User.username == "admin").scalar()
            project = Project(name=f"{marker}-project", owner_id=owner_id)
            db.add(project)
            db.flush()
            scores = {"low": 0.42, "high": 0.97, "mid": 0.71}
            for name, score in scores.items():
                db.add(ModelLibrary(
                    project_id=project.id,
                    owner_id=owner_id,
                    name=f"{marker}-{name}",
                    framework="automl",
                    metrics={"best_score": score},
                    status="completed",
                ))
            db.add(ModelLibrary(
                project_id=project.id,
                owner_id=owner_id,
                name=f"{marker}-noscore",
                framework="automl",
                metrics={"f1": 0.9},
                status="completed",
            ))
            db.commit()
        finally:
            db.close()

        r = client.get("/api/model-library/stats/summary")
        self.assertEqual(r.status_code, 200, r.text)
        top = r.json()["top_models"]
        top_names = [item["name"] for item in top]
        self.assertIn(f"{marker}-high", top_names)
        self.assertEqual(top_names.index(f"{marker}-high"), 0)
        # 无 best_score 的条目不得排在高分行前面
        self.assertLess(
            top_names.index(f"{marker}-mid"),
            top_names.index(f"{marker}-low") if f"{marker}-low" in top_names else len(top_names),
        )

        r = client.get("/api/dashboard/top-models", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        dash_top = [item["name"] for item in r.json()["items"]]
        self.assertIn(f"{marker}-high", dash_top)
        self.assertEqual(dash_top.index(f"{marker}-high"), 0)

        # 清理
        db = SessionLocal()
        try:
            db.query(ModelLibrary).filter(ModelLibrary.name.like(f"{marker}-%")).delete(
                synchronize_session=False
            )
            db.query(Project).filter(Project.name == f"{marker}-project").delete(
                synchronize_session=False
            )
            db.commit()
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
