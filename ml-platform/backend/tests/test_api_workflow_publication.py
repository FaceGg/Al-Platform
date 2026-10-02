"""Orchestration API publication and invoke tests (Plan B serving path)."""
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, ".")

import joblib
import pandas as pd
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression

from app.database import Base, SessionLocal, engine
from app.main import app
from app.api.auth import pwd_context
from app.models.api_model import PlatformAPI
from app.models.artifact import Artifact
from app.models.run import WorkflowRun  # noqa: F401 — _seed(with_run=True) keeps legacy seeding
from app.models.user import User
from app.models.workflow import Workflow
from app.models.workflow_version import WorkflowVersion
from app.models.project import Project
from app.services.artifact_service import build_artifact_service

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


def _serving_nodes(model_artifact_id: str):
    """api_input → apply_model ← load_model_artifact → condition."""
    return (
        [
            {"id": "n-input", "operator_id": "api_input", "label": "输入", "params": {}},
            {"id": "n-model", "operator_id": "load_model_artifact", "label": "模型",
             "params": {"model_artifact_id": model_artifact_id}},
            {"id": "n-apply", "operator_id": "apply_model", "label": "推理", "params": {}},
            {"id": "n-cond", "operator_id": "condition", "label": "判断",
             "params": {"column": "prediction", "operator": "==", "value": "1"}},
        ],
        [
            {"source": "n-input", "target": "n-apply", "source_port": "data", "target_port": "data"},
            {"source": "n-model", "target": "n-apply", "source_port": "model", "target_port": "model"},
            {"source": "n-apply", "target": "n-cond", "source_port": "data", "target_port": "data"},
        ],
    )


class OrchestrationAPIFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()
        db = SessionLocal()
        try:
            cls.admin_id = db.query(User).filter(User.username == "admin").one().id
            cls.project = Project(name=f"planb-{uuid.uuid4().hex[:8]}", owner_id=cls.admin_id)
            db.add(cls.project)
            db.flush()
            service = build_artifact_service(db)
            frame = pd.DataFrame({
                "f1": [0.0, 0.2, 0.1, 0.3, 0.15, 5.0, 5.4, 4.8, 5.2, 5.1],
                "f2": [1.0, 1.2, 0.9, 1.1, 1.05, -1.0, -1.2, -0.9, -1.1, -1.0],
            })
            model = LogisticRegression().fit(frame, [0, 0, 0, 0, 0, 1, 1, 1, 1, 1])
            with tempfile.TemporaryDirectory() as tmp:
                model_path = Path(tmp) / "serving_model.joblib"
                joblib.dump(model, model_path)
                artifact = service.create_from_file(
                    cls.project.id, model_path, f"serving-{uuid.uuid4().hex[:6]}", "model")
            cls.model_artifact_id = str(artifact.id)
            db.commit()
            cls.project_id = str(cls.project.id)
        finally:
            db.close()

    def _seed(self, *, with_run: bool, extra_nodes=None, snapshot_nodes=None, snapshot_edges=None):
        db = SessionLocal()
        try:
            workflow = Workflow(
                project_id=self.project.id, name=f"serving-wf-{uuid.uuid4().hex[:6]}",
                created_by=self.admin_id,
            )
            db.add(workflow)
            db.flush()
            nodes, edges = _serving_nodes(self.model_artifact_id)
            if extra_nodes:
                nodes = nodes + extra_nodes
            if snapshot_nodes is not None:
                nodes, edges = snapshot_nodes, snapshot_edges
            version = WorkflowVersion(
                workflow_id=workflow.id, version=1, name="v1",
                nodes_snapshot=nodes, edges_snapshot=edges,
                published_by=self.admin_id,
            )
            db.add(version)
            if with_run:
                db.add(WorkflowRun(
                    workflow_id=workflow.id, status="completed",
                    workflow_version=1, triggered_by=self.admin_id,
                ))
            db.commit()
            return str(workflow.id), 1
        finally:
            db.close()

    def test_01_publish_requires_serving_shape(self):
        # Publication only accepts serving graphs: a graph without the
        # api_input node has no way to receive invoke rows.
        nodes = [
            {"id": "n-model", "operator_id": "load_model_artifact", "label": "模型",
             "params": {"model_artifact_id": self.model_artifact_id}},
            {"id": "n-apply", "operator_id": "apply_model", "label": "推理", "params": {}},
        ]
        edges = [{"source": "n-model", "target": "n-apply",
                  "source_port": "model", "target_port": "model"}]
        workflow_id, version = self._seed(with_run=False, snapshot_nodes=nodes, snapshot_edges=edges)
        r = client.post(f"/api/platform/apis/publish/workflow/{workflow_id}/{version}", headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["code"], "SERVING_GRAPH_INVALID")

    def test_02_publish_rejects_training_operators(self):
        workflow_id, version = self._seed(
            with_run=True,
            extra_nodes=[{"id": "n-train", "operator_id": "xgboost_train",
                          "label": "训练", "params": {}}],
        )
        r = client.post(f"/api/platform/apis/publish/workflow/{workflow_id}/{version}", headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["code"], "SERVING_GRAPH_HAS_TRAINING")

    def test_03_publish_invoke_branch_and_offline(self):
        workflow_id, version = self._seed(with_run=False)

        r = client.post(f"/api/platform/apis/publish/workflow/{workflow_id}/{version}", headers=self.h)
        self.assertEqual(r.status_code, 201, r.text)
        api = r.json()
        self.assertEqual(api["source_kind"], "orchestration")
        self.assertEqual(api["status"], "published")
        r2 = client.post(f"/api/platform/apis/publish/workflow/{workflow_id}/{version}", headers=self.h)
        self.assertEqual(r2.status_code, 201, r2.text)
        self.assertEqual(r2.json()["id"], api["id"])

        invoke_url = f"/api/platform/apis/orchestration/{api['source_id']}/invoke"

        # Error-class row → prediction 1 → condition true branch.
        r = client.post(invoke_url, json={"record": {"f1": 5.1, "f2": -1.0}}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["branch"], "true", body)
        self.assertEqual(len(body["records"]), 1)
        self.assertEqual(float(body["records"][0].get("prediction")), 1.0)

        # Ok-class row → prediction 0 → false branch.
        r = client.post(invoke_url, json={"record": {"f1": 0.1, "f2": 1.0}}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["branch"], "false", r.text)

        # Counters reflect the successful invokes.
        items = client.get("/api/platform/apis", headers=self.h).json()["items"]
        mine = next(item for item in items if item["id"] == api["id"])
        self.assertGreaterEqual(mine["total_calls"], 2)
        self.assertGreaterEqual(mine["success_calls"], 2)

        # Offline → invoke refused.
        r = client.post(f"/api/platform/apis/publish/workflow/{workflow_id}/{version}/offline", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "offline")
        r = client.post(invoke_url, json={"record": {"f1": 0.1, "f2": 1.0}}, headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["code"], "ORCHESTRATION_API_OFFLINE")

    def test_04_workflow_delete_takes_api_offline(self):
        workflow_id, version = self._seed(with_run=True)
        r = client.post(f"/api/platform/apis/publish/workflow/{workflow_id}/{version}", headers=self.h)
        self.assertEqual(r.status_code, 201, r.text)
        api_id = r.json()["id"]
        r = client.delete(f"/api/workflows/{workflow_id}", headers=self.h)
        self.assertEqual(r.status_code, 204, r.text)
        items = client.get("/api/platform/apis", headers=self.h).json()["items"]
        mine = next(item for item in items if item["id"] == api_id)
        self.assertEqual(mine["status"], "offline")

    def test_05_delete_orchestration_api_allowed_model_forbidden(self):
        workflow_id, version = self._seed(with_run=False)
        r = client.post(f"/api/platform/apis/publish/workflow/{workflow_id}/{version}", headers=self.h)
        self.assertEqual(r.status_code, 201, r.text)
        orchestration_id = r.json()["id"]

        # A model-bound catalog row follows the deployment lifecycle instead.
        db = SessionLocal()
        try:
            model_api = PlatformAPI(
                name="deployment-bound", api_type="model", source_kind="model",
                source_id=uuid.uuid4(), version="v1", owner_id=self.admin_id,
            )
            db.add(model_api)
            db.commit()
            model_api_id = str(model_api.id)
        finally:
            db.close()

        r = client.delete(f"/api/platform/apis/{model_api_id}", headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)

        r = client.delete(f"/api/platform/apis/{orchestration_id}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        items = client.get("/api/platform/apis", headers=self.h).json()["items"]
        self.assertFalse(any(item["id"] == orchestration_id for item in items))


if __name__ == "__main__":
    unittest.main()
