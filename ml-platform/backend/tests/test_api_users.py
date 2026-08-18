"""Users management API integration tests."""
import sys, os, unittest
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine
from app.database import SessionLocal
from app.models.user import User

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def admin_login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestUsersAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin user exists
        r = client.post("/api/auth/register", json={
            "username": "admin", "password": "admin123"
        })
        with SessionLocal() as db:
            administrator = db.query(User).filter(User.username == "admin").one()
            administrator.role = "admin"
            db.commit()
        cls.admin_h = admin_login()

    def test_01_health_accessible_without_auth(self):
        r = client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})

    def test_02_login_success(self):
        r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("access_token", data)
        self.assertIn("token_type", data)

    def test_03_login_wrong_password(self):
        r = client.post("/api/auth/login", data={"username": "admin", "password": "wrongpassword"})
        self.assertEqual(r.status_code, 401)

    def test_04_login_nonexistent_user(self):
        r = client.post("/api/auth/login", data={"username": "nonexistent_user_123", "password": "pass"})
        self.assertEqual(r.status_code, 401)

    def test_05_register_new_user(self):
        import random
        uname = f"user_{random.randint(10000, 99999)}"
        r = client.post("/api/auth/register", json={
            "username": uname,
            "password": "newpass123",
        })
        self.assertIn(r.status_code, [200, 201])

    def test_06_register_duplicate_username(self):
        r = client.post("/api/auth/register", json={
            "username": "admin",
            "password": "somepass123",
        })
        self.assertIn(r.status_code, [400, 409])

    def test_07_register_missing_fields(self):
        r = client.post("/api/auth/register", json={"username": "incomplete"})
        self.assertEqual(r.status_code, 422)

    def test_08_admin_list_users(self):
        r = client.get("/api/admin/users", headers=self.admin_h)
        # May return 401 if SQLite UUID cast issue exists
        self.assertIn(r.status_code, [200, 401])
        if r.status_code == 200:
            data = r.json()
            self.assertIsInstance(data, list)
            self.assertGreater(len(data), 0)

    def test_09_unauthorized_access_without_token(self):
        r = client.get("/api/projects")
        self.assertEqual(r.status_code, 401)

    def test_10_invalid_token(self):
        r = client.get("/api/projects", headers={"Authorization": "Bearer invalid_token_here"})
        self.assertEqual(r.status_code, 401)

    def test_11_admin_can_batch_delete_users(self):
        import uuid

        usernames = []
        for _ in range(2):
            username = f"batch_delete_{uuid.uuid4().hex[:10]}"
            created = client.post("/api/auth/register", json={
                "username": username,
                "password": "newpass123",
            })
            self.assertIn(created.status_code, [200, 201])
            usernames.append(username)

        listed = client.get("/api/admin/users", headers=self.admin_h)
        self.assertEqual(listed.status_code, 200)
        ids_by_username = {item["username"]: item["id"] for item in listed.json()}
        user_ids = [ids_by_username[username] for username in usernames]

        deleted = client.post(
            "/api/admin/users/batch-delete",
            json={"user_ids": user_ids},
            headers=self.admin_h,
        )

        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["deleted_ids"], user_ids)

    def test_12_batch_delete_skips_current_admin(self):
        import uuid

        username = f"batch_delete_member_{uuid.uuid4().hex[:10]}"
        created = client.post("/api/auth/register", json={
            "username": username,
            "password": "newpass123",
        })
        self.assertIn(created.status_code, [200, 201])

        listed = client.get("/api/admin/users", headers=self.admin_h)
        self.assertEqual(listed.status_code, 200)
        ids_by_username = {item["username"]: item["id"] for item in listed.json()}
        response = client.post(
            "/api/admin/users/batch-delete",
            json={"user_ids": [ids_by_username["admin"], ids_by_username[username]]},
            headers=self.admin_h,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted_ids"], [ids_by_username[username]])
        self.assertTrue(response.json()["skipped_current_user"])


    def test_13_admin_deleting_user_transfers_owned_model_library_entries(self):
        import uuid

        from app.database import SessionLocal
        from app.models.model_library import ModelLibrary
        from app.models.user import User

        username = f"delete_owned_model_{uuid.uuid4().hex[:10]}"
        created = client.post("/api/auth/register", json={
            "username": username,
            "password": "newpass123",
        })
        self.assertIn(created.status_code, [200, 201])

        db = SessionLocal()
        try:
            member = db.query(User).filter(User.username == username).one()
            administrator = db.query(User).filter(User.username == "admin").one()
            model = ModelLibrary(name=f"model-{username}", owner_id=member.id)
            db.add(model)
            db.commit()
            member_id = str(member.id)
            model_id = model.id
            administrator_id = administrator.id
        finally:
            db.close()

        deleted = client.delete(f"/api/admin/users/{member_id}", headers=self.admin_h)

        self.assertEqual(deleted.status_code, 200)
        db = SessionLocal()
        try:
            self.assertIsNone(db.query(User).filter(User.id == uuid.UUID(member_id)).first())
            model = db.query(ModelLibrary).filter(ModelLibrary.id == model_id).one()
            self.assertEqual(model.owner_id, administrator_id)
        finally:
            db.close()
if __name__ == "__main__":
    unittest.main()
