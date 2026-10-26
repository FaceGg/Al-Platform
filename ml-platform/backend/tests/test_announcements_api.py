"""Announcements API tests: portal read for any signed-in user, admin-only
write gate, full CRUD round-trip and 404 contract.
"""

import unittest
import uuid

from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.models.user import User
from tests.auth_test_support import ensure_admin

Base.metadata.create_all(bind=engine)
client = TestClient(__import__("app.main", fromlist=["app"]).app)

_ADMIN_USER = "ann-admin-" + uuid.uuid4().hex[:8]
_ADMIN_PASSWORD = uuid.uuid4().hex + uuid.uuid4().hex[:4]
_ENGINEER_USER = "ann-engineer-" + uuid.uuid4().hex[:8]
_ENGINEER_PASSWORD = uuid.uuid4().hex + uuid.uuid4().hex[:4]


def _login(username: str, password: str) -> dict:
    response = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class TestAnnouncementsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin(_ADMIN_USER, _ADMIN_PASSWORD)
        from app.api.auth import pwd_context

        with SessionLocal() as db:
            if db.query(User).filter(User.username == _ENGINEER_USER).first() is None:
                db.add(User(
                    username=_ENGINEER_USER,
                    password_hash=pwd_context.hash(_ENGINEER_PASSWORD),
                    role="engineer",
                ))
                db.commit()
        cls.admin_headers = _login(_ADMIN_USER, _ADMIN_PASSWORD)
        cls.engineer_headers = _login(_ENGINEER_USER, _ENGINEER_PASSWORD)

    def test_admin_creates_reads_updates_and_deletes_an_announcement(self):
        created = client.post(
            "/api/announcements",
            json={"title": "维护窗口", "content": "周六 02:00-04:00 升级", "pinned": True},
            headers=self.admin_headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual(body["title"], "维护窗口")
        self.assertTrue(body["pinned"])
        self.assertEqual(body["created_by"], _ADMIN_USER)

        listing = client.get("/api/announcements", headers=self.engineer_headers)
        self.assertEqual(listing.status_code, 200)
        titles = [item["title"] for item in listing.json()]
        self.assertIn("维护窗口", titles)

        patched = client.patch(
            f"/api/announcements/{body['id']}",
            json={"title": "维护窗口（改期）", "pinned": False},
            headers=self.admin_headers,
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["title"], "维护窗口（改期）")
        self.assertFalse(patched.json()["pinned"])

        deleted = client.delete(
            f"/api/announcements/{body['id']}", headers=self.admin_headers,
        )
        self.assertEqual(deleted.status_code, 204)
        missing = client.get("/api/announcements", headers=self.admin_headers)
        self.assertNotIn("维护窗口（改期）", [item["title"] for item in missing.json()])

    def test_non_admin_cannot_create_update_or_delete(self):
        created = client.post(
            "/api/announcements",
            json={"title": "x"},
            headers=self.engineer_headers,
        )
        self.assertEqual(created.status_code, 403)

        seed = client.post(
            "/api/announcements",
            json={"title": "管理员公告"},
            headers=self.admin_headers,
        )
        announcement_id = seed.json()["id"]

        patched = client.patch(
            f"/api/announcements/{announcement_id}",
            json={"title": "y"},
            headers=self.engineer_headers,
        )
        self.assertEqual(patched.status_code, 403)

        deleted = client.delete(
            f"/api/announcements/{announcement_id}",
            headers=self.engineer_headers,
        )
        self.assertEqual(deleted.status_code, 403)

    def test_unauthenticated_read_is_rejected(self):
        response = client.get("/api/announcements")
        self.assertIn(response.status_code, (401, 403))

    def test_unknown_id_returns_404(self):
        response = client.patch(
            f"/api/announcements/{uuid.uuid4()}",
            json={"title": "x"},
            headers=self.admin_headers,
        )
        self.assertEqual(response.status_code, 404)

        bogus = client.patch(
            "/api/announcements/not-a-uuid",
            json={"title": "x"},
            headers=self.admin_headers,
        )
        self.assertEqual(bogus.status_code, 404)


if __name__ == "__main__":
    unittest.main()
