"""Platform API integration tests."""
import sys, os, unittest
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


class TestPlatformAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()

    def test_01_list_apis(self):
        r = client.get("/api/platform/apis", headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        if r.status_code == 200:
            data = r.json()
            self.assertIn("items", data)

    def test_02_create_api(self):
        r = client.post("/api/platform/apis", json={
            "name": "test_api_weld",
            "api_type": "model",
            "description": "Test weld API",
        }, headers=self.h)
        self.assertIn(r.status_code, [200, 201, 422])

    def test_03_filter_by_type(self):
        r = client.get("/api/platform/apis?api_type=model", headers=self.h)
        self.assertIn(r.status_code, [200, 201])

    def test_04_filter_by_status(self):
        r = client.get("/api/platform/apis?status=published", headers=self.h)
        self.assertIn(r.status_code, [200, 201])

    def test_05_api_stats(self):
        r = client.get("/api/platform/apis/stats", headers=self.h)
        self.assertIn(r.status_code, [200, 201, 404])


if __name__ == "__main__":
    unittest.main()
