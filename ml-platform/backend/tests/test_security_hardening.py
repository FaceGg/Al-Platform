"""Security boundary regression contracts."""

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import pwd_context
from app.database import Base, get_db
from app.main import app
from app.models.access import ProjectMember
from app.models.api_model import PlatformAPI
from app.models.compute import ComputeNode, EdgeDevice
from app.models.platform_models import AnnotationResult, AnnotationTask, Dataset
from app.models.project import Project
from app.models.user import User

try:
    from app.services.resource_access import ResourceAccessError, ResourceAccessService
except ModuleNotFoundError:
    ResourceAccessError = None
    ResourceAccessService = None


RESOURCE_CASES = (
    {
        "resource": "compute_node",
        "method": "get",
        "path": "/api/compute/nodes/{resource_id}",
        "payload": None,
        "owner_status": 200,
        "outsider_status": 404,
    },
    {
        "resource": "edge_device",
        "method": "get",
        "path": "/api/compute/devices/{resource_id}",
        "payload": None,
        "owner_status": 200,
        "outsider_status": 404,
    },
    {
        "resource": "annotation_task",
        "method": "put",
        "path": "/api/annotations/tasks/{resource_id}",
        "payload": {"name": "owner-updated-task"},
        "owner_status": 200,
        "outsider_status": 404,
    },
    {
        "resource": "platform_api",
        "method": "put",
        "path": "/api/platform/apis/{resource_id}",
        "payload": {"name": "owner-updated-api"},
        "owner_status": 200,
        "outsider_status": 404,
    },
)


class TestSecurityHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)

        with cls.Session() as db:
            owner = User(
                username="security-owner",
                password_hash=pwd_context.hash("safe-password"),
                role="engineer",
            )
            outsider = User(
                username="security-outsider",
                password_hash=pwd_context.hash("safe-password"),
                role="engineer",
            )
            viewer = User(
                username="security-viewer",
                password_hash=pwd_context.hash("safe-password"),
                role="engineer",
            )
            db.add_all([owner, outsider, viewer])
            db.flush()

            node = ComputeNode(
                name="owner-node",
                node_number="security-owner-node",
                owner_id=owner.id,
            )
            dataset = Dataset(name="owner-dataset", owner_id=owner.id)
            edge = EdgeDevice(
                name="owner-edge-device",
                group_id="security",
                owner_id=owner.id,
            )
            db.add_all([node, edge, dataset])
            db.flush()

            task = AnnotationTask(
                name="owner-task",
                dataset_id=dataset.id,
                owner_id=owner.id,
            )
            private_api = PlatformAPI(
                name="owner-private-api",
                owner_id=owner.id,
                is_public=False,
            )
            public_api = PlatformAPI(
                name="owner-public-api",
                owner_id=owner.id,
                is_public=True,
            )
            project = Project(name="security-project", owner_id=owner.id)
            db.add_all([task, private_api, public_api, project])
            db.flush()

            sample = AnnotationResult(task_id=task.id, sample_index=0)
            db.add_all([
                sample,
                ProjectMember(
                    project_id=project.id,
                    user_id=viewer.id,
                    role="viewer",
                    created_by=owner.id,
                ),
            ])
            db.commit()

            cls.resource_ids = {
                "compute_node": str(node.id),
                "edge_device": str(edge.id),
                "annotation_task": str(task.id),
                "platform_api": str(private_api.id),
            }
            cls.private_api_id = str(private_api.id)
            cls.public_api_id = str(public_api.id)
            cls.annotation_sample_id = str(sample.id)
            cls.project_id = str(project.id)

        def override_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        cls.client = TestClient(app)
        cls.owner_headers = cls._login("security-owner")
        cls.outsider_headers = cls._login("security-outsider")
        cls.viewer_headers = cls._login("security-viewer")

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_db, None)
        cls.client.close()
        cls.engine.dispose()

    @classmethod
    def _login(cls, username):
        response = cls.client.post(
            "/api/auth/login",
            data={"username": username, "password": "safe-password"},
        )
        if response.status_code != 200:
            raise AssertionError(response.text)
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    def _request_resource(self, case, headers):
        kwargs = {"headers": headers}
        if case["payload"] is not None:
            kwargs["json"] = case["payload"]
        return getattr(self.client, case["method"])(
            case["path"].format(resource_id=self.resource_ids[case["resource"]]),
            **kwargs,
        )

    def test_01_registration_rejects_role_payload(self):
        response = self.client.post(
            "/api/auth/register",
            json={
                "username": "role-probe",
                "password": "safe-password",
                "role": "admin",
            },
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_02_registration_defaults_to_engineer(self):
        response = self.client.post(
            "/api/auth/register",
            json={"username": "ordinary-user", "password": "safe-password"},
        )
        self.assertEqual(response.status_code, 200, response.text)

        with self.Session() as db:
            user = db.query(User).filter(User.username == "ordinary-user").one()
            self.assertEqual(user.role, "engineer")

    def test_03_resource_cases_enforce_owner_and_hidden_outsider_access(self):
        for case in RESOURCE_CASES:
            with self.subTest(resource=case["resource"], actor="owner"):
                response = self._request_resource(case, self.owner_headers)
                self.assertEqual(response.status_code, case["owner_status"], response.text)
            with self.subTest(resource=case["resource"], actor="outsider"):
                response = self._request_resource(case, self.outsider_headers)
                self.assertEqual(response.status_code, case["outsider_status"], response.text)

    def test_04_foreign_user_cannot_update_another_compute_node(self):
        response = self.client.put(
            f"/api/compute/nodes/{self.resource_ids['compute_node']}",
            json={"name": "probe"},
            headers=self.outsider_headers,
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_05_resource_access_service_hides_direct_and_indirect_foreign_rows(self):
        self.assertIsNotNone(ResourceAccessService)
        self.assertIsNotNone(ResourceAccessError)
        if ResourceAccessService is None or ResourceAccessError is None:
            return

        with self.Session() as db:
            owner = db.query(User).filter(User.username == "security-owner").one()
            outsider = db.query(User).filter(User.username == "security-outsider").one()
            node = ResourceAccessService().require_owned(
                db,
                ComputeNode,
                self.resource_ids["compute_node"],
                owner.id,
            )
            self.assertEqual(node.owner_id, owner.id)
            with self.assertRaises(ResourceAccessError) as denied:
                ResourceAccessService().require_owned(
                    db,
                    ComputeNode,
                    self.resource_ids["compute_node"],
                    outsider.id,
                )
            self.assertEqual(denied.exception.code, "RESOURCE_NOT_FOUND")
            with self.assertRaises(ResourceAccessError):
                ResourceAccessService().require_annotation_sample(
                    db,
                    self.annotation_sample_id,
                    outsider.id,
                )

    def test_06_foreign_user_cannot_access_annotation_samples_or_auto_label(self):
        task_id = self.resource_ids["annotation_task"]
        with self.subTest(endpoint="samples"):
            response = self.client.get(
                f"/api/annotations/tasks/{task_id}/samples",
                headers=self.outsider_headers,
            )
            self.assertEqual(response.status_code, 404, response.text)
        with self.subTest(endpoint="auto-label"):
            response = self.client.post(
                f"/api/annotations/tasks/{task_id}/auto-label",
                headers=self.outsider_headers,
            )
            self.assertEqual(response.status_code, 404, response.text)

    def test_07_platform_api_listing_requires_auth_and_hides_private_apis(self):
        with self.subTest(actor="unauthenticated"):
            response = self.client.get("/api/platform/apis")
            self.assertEqual(response.status_code, 401, response.text)
        with self.subTest(actor="outsider"):
            response = self.client.get(
                "/api/platform/apis",
                headers=self.outsider_headers,
            )
            self.assertEqual(response.status_code, 200, response.text)
            api_ids = {item["id"] for item in response.json()["items"]}
            self.assertNotIn(self.private_api_id, api_ids)
            self.assertIn(self.public_api_id, api_ids)

    def test_08_project_member_denial_happens_before_target_lookup(self):
        response = self.client.post(
            f"/api/projects/{self.project_id}/members",
            json={"username": "security-outsider", "role": "viewer"},
            headers=self.viewer_headers,
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "PROJECT_PERMISSION_DENIED",
        )


if __name__ == "__main__":
    unittest.main()
