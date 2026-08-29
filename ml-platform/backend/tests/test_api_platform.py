"""Platform API integration tests."""
import sys, os, unittest, uuid
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.api.auth import pwd_context
from app.database import Base, SessionLocal, engine
from app.models.user import User
from app.models.access import ProjectMember
from app.models.artifact import Artifact
from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
from app.models.project import Project

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


def login(username="admin", password="admin123"):
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestPlatformAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()
        db = SessionLocal()
        try:
            cls.user_id = db.query(User).filter(User.username == "admin").one().id
        finally:
            db.close()

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
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for key in ("total_apis", "published", "offline", "failed", "total_calls"):
            self.assertIn(key, data)

    def test_06_rejects_invalid_api_contract(self):
        cases = [
            {"api_type": "model", "endpoint": "/api/model"},
            {"name": "bad-method", "method": "TRACE", "endpoint": "/api/model"},
            {"name": "bad-type", "api_type": "unknown", "endpoint": "/api/model"},
            {"name": "external", "endpoint": "https://example.com/predict"},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                r = client.post("/api/platform/apis", json=payload, headers=self.h)
                self.assertEqual(r.status_code, 422)

    def test_07_create_returns_complete_resource_contract(self):
        r = client.post(
            "/api/platform/apis",
            json={
                "name": "contract-api",
                "api_type": "custom",
                "endpoint": "/api/contract-api",
                "method": "POST",
                "version": "v1",
            },
            headers=self.h,
        )
        self.assertEqual(r.status_code, 201)
        data = r.json()
        for key in ("id", "name", "api_type", "status", "version", "source_kind", "source_id"):
            self.assertIn(key, data)
        self.assertEqual(data["source_kind"], "custom")
        self.assertIsNone(data["source_id"])

    def test_08_update_rejects_unknown_status_and_returns_resource(self):
        created = client.post(
            "/api/platform/apis",
            json={"name": "status-api", "api_type": "custom", "endpoint": "/api/status-api"},
            headers=self.h,
        )
        self.assertEqual(created.status_code, 201)
        api_id = created.json()["id"]
        invalid = client.put(
            f"/api/platform/apis/{api_id}",
            json={"status": "running"},
            headers=self.h,
        )
        self.assertEqual(invalid.status_code, 422)
        offline = client.put(
            f"/api/platform/apis/{api_id}",
            json={"status": "offline"},
            headers=self.h,
        )
        self.assertEqual(offline.status_code, 200)
        self.assertEqual(offline.json()["status"], "offline")

    def create_deployment(self, *, running: bool) -> str:
        db = SessionLocal()
        try:
            project = Project(name=f"api-project-{uuid.uuid4().hex}", owner_id=self.user_id)
            db.add(project)
            db.flush()
            artifact = Artifact(
                project_id=project.id, name="model.onnx", type="model",
                storage_path="models/model.onnx", storage_uri="file:///models/model.onnx", format="onnx",
            )
            model = RegisteredModel(project_id=project.id, name=f"registered-{uuid.uuid4().hex}", created_by_id=self.user_id)
            db.add_all([artifact, model])
            db.flush()
            version = ModelVersion(
                registered_model_id=model.id, version_number=1, source_kind="onnx_artifact",
                source_artifact_id=artifact.id, onnx_artifact_id=artifact.id, approval_status="approved",
                feature_schema=[{"name": "x", "type": "number"}], output_schema={"type": "number"},
                created_by_id=self.user_id,
            )
            db.add(version)
            db.flush()
            deployment = InferenceDeployment(
                project_id=project.id, name=f"deployment-{uuid.uuid4().hex}", model_version_id=version.id,
                desired_state="running" if running else "stopped",
                observed_state="running" if running else "stopped", created_by_id=self.user_id,
            )
            db.add(deployment)
            db.commit()
            db.refresh(deployment)
            self.__class__.last_project_id = project.id
            return str(deployment.id)
        finally:
            db.close()

    def test_09_publish_running_deployment_is_idempotent(self):
        deployment_id = self.create_deployment(running=True)
        first = client.post(f"/api/platform/apis/publish/deployment/{deployment_id}", headers=self.h)
        second = client.post(f"/api/platform/apis/publish/deployment/{deployment_id}", headers=self.h)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(first.json()["source_kind"], "model")
        self.assertEqual(first.json()["endpoint"], f"/api/inference-deployments/{deployment_id}/predict")
        api_id = first.json()["id"]
        edited = client.put(
            f"/api/platform/apis/{api_id}",
            json={"endpoint": "/api/incorrect"},
            headers=self.h,
        )
        deleted = client.delete(f"/api/platform/apis/{api_id}", headers=self.h)
        self.assertEqual(edited.status_code, 409)
        self.assertEqual(deleted.status_code, 409)

    def test_10_publish_stopped_deployment_is_rejected(self):
        deployment_id = self.create_deployment(running=False)
        response = client.post(f"/api/platform/apis/publish/deployment/{deployment_id}", headers=self.h)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "DEPLOYMENT_NOT_READY")

    def test_11_manual_creation_only_accepts_custom_apis(self):
        for api_type in ("model", "orchestration"):
            with self.subTest(api_type=api_type):
                response = client.post(
                    "/api/platform/apis",
                    json={
                        "name": f"fake-{api_type}",
                        "api_type": api_type,
                        "source_kind": api_type,
                        "endpoint": f"/api/fake-{api_type}",
                    },
                    headers=self.h,
                )
                self.assertEqual(response.status_code, 422)

    def test_12_public_api_is_read_only_for_non_owner(self):
        marker = uuid.uuid4().hex
        username = f"api-reader-{marker}"
        password = "reader-password"
        registered = client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )
        self.assertEqual(registered.status_code, 200)
        reader_headers = login(username, password)
        created = client.post(
            "/api/platform/apis",
            json={
                "name": f"public-{marker}",
                "api_type": "custom",
                "endpoint": f"/api/public-{marker}",
                "is_public": True,
            },
            headers=self.h,
        )
        self.assertEqual(created.status_code, 201)
        api_id = created.json()["id"]
        listing = client.get("/api/platform/apis", headers=reader_headers)
        self.assertIn(api_id, {item["id"] for item in listing.json()["items"]})
        self.assertEqual(
            client.put(
                f"/api/platform/apis/{api_id}",
                json={"name": "forbidden"},
                headers=reader_headers,
            ).status_code,
            404,
        )
        self.assertEqual(
            client.delete(f"/api/platform/apis/{api_id}", headers=reader_headers).status_code,
            404,
        )

    def test_13_publish_permission_distinguishes_viewer_and_outsider(self):
        deployment_id = self.create_deployment(running=True)
        marker = uuid.uuid4().hex
        credentials = {}
        db = SessionLocal()
        try:
            for role in ("viewer", "outsider"):
                username = f"api-{role}-{marker}"
                password = f"{role}-password"
                user = User(
                    username=username,
                    password_hash=pwd_context.hash(password),
                    role="engineer",
                )
                db.add(user)
                db.flush()
                credentials[role] = (username, password)
                if role == "viewer":
                    db.add(ProjectMember(
                        project_id=self.last_project_id,
                        user_id=user.id,
                        role="viewer",
                        created_by=self.user_id,
                    ))
            db.commit()
        finally:
            db.close()
        viewer = client.post(
            f"/api/platform/apis/publish/deployment/{deployment_id}",
            headers=login(*credentials["viewer"]),
        )
        outsider = client.post(
            f"/api/platform/apis/publish/deployment/{deployment_id}",
            headers=login(*credentials["outsider"]),
        )
        self.assertEqual(viewer.status_code, 403)
        self.assertEqual(outsider.status_code, 404)


if __name__ == "__main__":
    unittest.main()
