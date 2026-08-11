"""Model Library API integration tests."""
import sys, os, unittest, uuid
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app.models.model_library import ModelLibrary
from app.models.user import User

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestModelLibraryAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        client.post("/api/auth/register", json={"username": "admin", "password": "admin123", "role": "admin"})
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

    def test_13_admin_can_view_private_standalone_models_from_other_users(self):
        marker = f"admin-private-model-{uuid.uuid4().hex}"
        with SessionLocal() as db:
            owner = User(
                username=f"{marker}-owner",
                password_hash="hash",
                role="engineer",
            )
            db.add(owner)
            db.flush()
            model = ModelLibrary(
                name=f"{marker}-model",
                owner_id=owner.id,
                status="completed",
                is_public=False,
            )
            db.add(model)
            db.commit()
            model_id = str(model.id)
            owner_id = owner.id

        try:
            listed = client.get("/api/model-library", headers=self.h)
            self.assertEqual(listed.status_code, 200)
            self.assertIn(
                model_id,
                {item["id"] for item in listed.json()["items"]},
            )
            detail = client.get(f"/api/model-library/{model_id}", headers=self.h)
            self.assertEqual(detail.status_code, 200)
        finally:
            with SessionLocal() as db:
                db.query(ModelLibrary).filter(
                    ModelLibrary.id == uuid.UUID(model_id),
                ).delete(synchronize_session=False)
                db.query(User).filter(User.id == owner_id).delete(
                    synchronize_session=False,
                )
                db.commit()


if __name__ == "__main__":
    unittest.main()
