import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.access import ProjectMember
from app.models.project import Project
from app.models.user import User


class TestProjectAccessAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)
        cls.db = cls.Session()
        cls.users = {
            role: User(username=f"api-access-{role}", password_hash="hash")
            for role in ("owner", "editor", "viewer", "outsider")
        }
        cls.db.add_all(cls.users.values())
        cls.db.flush()
        cls.project = Project(name="Access API project", owner_id=cls.users["owner"].id)
        cls.db.add(cls.project)
        cls.db.commit()
        cls.current_user = cls.users["owner"]
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.current_user
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    def setUp(self):
        self.__class__.current_user = self.users["owner"]

    def test_member_add_list_change_and_remove(self):
        project_id = self.project.id
        added = self.client.post(
            f"/api/projects/{project_id}/members",
            json={"username": self.users["editor"].username, "role": "editor"},
        )
        self.assertEqual(added.status_code, 201, added.text)
        self.assertEqual(added.json()["role"], "editor")

        listed = self.client.get(f"/api/projects/{project_id}/members")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertTrue(
            {"owner", "editor"}.issubset(
                {item["role"] for item in listed.json()["items"]}
            )
        )

        changed = self.client.patch(
            f"/api/projects/{project_id}/members/{self.users['editor'].id}",
            json={"role": "operator"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["role"], "operator")

        removed = self.client.delete(
            f"/api/projects/{project_id}/members/{self.users['editor'].id}"
        )
        self.assertEqual(removed.status_code, 204, removed.text)

    def test_joined_project_list_contains_project_role(self):
        self.db.add(ProjectMember(
            project_id=self.project.id,
            user_id=self.users["viewer"].id,
            role="viewer",
            created_by=self.users["owner"].id,
        ))
        self.db.commit()
        self.__class__.current_user = self.users["viewer"]

        response = self.client.get("/api/projects")

        self.assertEqual(response.status_code, 200, response.text)
        item = next(item for item in response.json()["items"] if item["id"] == str(self.project.id))
        self.assertEqual(item["project_role"], "viewer")

    def test_visible_member_is_forbidden_and_outsider_is_hidden(self):
        self.__class__.current_user = self.users["viewer"]
        forbidden = self.client.get(f"/api/projects/{self.project.id}/members")
        self.assertEqual(forbidden.status_code, 403, forbidden.text)
        self.assertEqual(forbidden.json()["detail"]["code"], "PROJECT_PERMISSION_DENIED")

        self.__class__.current_user = self.users["outsider"]
        hidden = self.client.get(f"/api/projects/{self.project.id}/members")
        self.assertEqual(hidden.status_code, 404, hidden.text)

    def test_owner_can_filter_append_only_audit_events(self):
        response = self.client.get(
            f"/api/projects/{self.project.id}/audit-events",
            params={"action": "project.member.add", "result": "success", "limit": 10},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertGreaterEqual(payload["total"], 1)
        self.assertTrue(all(item["action"] == "project.member.add" for item in payload["items"]))
        self.assertTrue(all(item["result"] == "success" for item in payload["items"]))


if __name__ == "__main__":
    unittest.main()
