"""Platform API integration tests."""
import sys, os, unittest, uuid
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.api.auth import pwd_context
from app.database import Base, SessionLocal, engine
from app.models.user import User
from app.models.access import ProjectMember
from app.models.api_model import PlatformAPI
from app.models.artifact import Artifact
from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
from app.models.project import Project
from app.models.workflow import Workflow, WorkflowNode
from app.models.workflow_version import WorkflowVersion

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
        password = f"Reader-{marker[:8]}"
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


class TestOrchestrationShowcase(unittest.TestCase):
    """实时大屏仅面向通用闭环模板原样结构的编排 API。"""

    TEMPLATE_OPERATORS = (
        "api_input", "load_model_artifact", "apply_model", "condition",
        "append_error_dataset", "notify_admins", "retrain_threshold",
    )

    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()
        marker = uuid.uuid4().hex[:8]
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.username == "admin").one()
            project = Project(name=f"showcase-{marker}", owner_id=owner.id)
            db.add(project)
            db.flush()
            workflow = Workflow(project_id=project.id, name=f"wf-{marker}", created_by=owner.id)
            db.add(workflow)
            db.flush()

            def snapshot(operators):
                return [
                    {"id": f"n{i}", "operator_id": op, "label": op, "params": {"threshold_rows": 3}}
                    for i, op in enumerate(operators)
                ]

            good_version = WorkflowVersion(
                workflow_id=workflow.id, version=1, name="v1",
                nodes_snapshot=snapshot(cls.TEMPLATE_OPERATORS), edges_snapshot=[],
                published_by=owner.id,
            )
            bad_version = WorkflowVersion(
                workflow_id=workflow.id, version=2, name="v2",
                nodes_snapshot=snapshot(cls.TEMPLATE_OPERATORS + ("python_script",)),
                edges_snapshot=[], published_by=owner.id,
            )
            db.add_all([good_version, bad_version])
            db.flush()
            cls.project_id = str(project.id)
            cls.good_version_id = str(good_version.id)
            cls.bad_version_id = str(bad_version.id)
            cls.workflow_id = str(workflow.id)
            db.add(PlatformAPI(
                name=f"闭环编排-{marker}", api_type="orchestration",
                endpoint=f"/api/orchestration-{marker}", version="v1",
                status="published", source_kind="orchestration",
                source_id=good_version.id, workflow_id=workflow.id,
                total_calls=12, success_calls=12, error_calls=2, alert_calls=2,
                showcase_state={"events": [
                    {"id": "e1", "event_type": "row_predicted", "message": "正常预测", "created_at": "2026-10-15T00:00:00"},
                    {"id": "e2", "event_type": "error_row", "message": "报错行命中回流", "created_at": "2026-10-15T00:00:01"},
                ], "last_retrain_job_id": None},
                owner_id=owner.id,
            ))
            db.add(PlatformAPI(
                name=f"编排改造-{marker}", api_type="orchestration",
                endpoint=f"/api/orchestration-mod-{marker}", version="v1",
                status="published", source_kind="orchestration",
                source_id=bad_version.id, workflow_id=workflow.id,
                owner_id=owner.id,
            ))
            db.commit()
        finally:
            db.close()

    def test_01_list_marks_showcase_eligibility(self):
        listing = client.get("/api/platform/apis?status=published&api_type=orchestration", headers=self.h)
        self.assertEqual(listing.status_code, 200)
        by_name = {item["name"]: item for item in listing.json()["items"]}
        good = [v for k, v in by_name.items() if k.startswith("闭环编排-")][0]
        bad = [v for k, v in by_name.items() if k.startswith("编排改造-")][0]
        self.assertTrue(good["showcase_eligible"])
        self.assertFalse(bad["showcase_eligible"])

    def test_02_showcase_status_returns_loop_shaped_payload(self):
        r = client.get(
            f"/api/platform/apis/orchestration/{self.good_version_id}/showcase-status",
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["total_count"], 12)
        self.assertEqual(data["error_count"], 2)
        self.assertEqual(data["alert_count"], 2)
        self.assertEqual(data["retrain_status"], "idle")
        self.assertEqual(data["retrain_threshold_rows"], 3)
        self.assertEqual(len(data["events"]), 2)
        self.assertIn("model_score", data)

    def test_03_modified_template_is_rejected(self):
        r = client.get(
            f"/api/platform/apis/orchestration/{self.bad_version_id}/showcase-status",
            headers=self.h,
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["code"], "SHOWCASE_NOT_ELIGIBLE")


if __name__ == "__main__":
    unittest.main()
