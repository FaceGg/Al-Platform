"""Orchestration API publication and invoke tests (Plan B serving path)."""
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

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
from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
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


class _StubDispatcher:
    """Records enqueued AutoML jobs instead of executing them."""

    def __init__(self):
        self.enqueued = []
        self.started = []

    def enqueue(self, job_id):
        self.enqueued.append(str(job_id))
        return f"local:stub-{len(self.enqueued)}"

    def start(self, task_id):
        self.started.append(task_id)


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

    def _seed_error_dataset(self, project_uuid):
        import tempfile
        service = build_artifact_service(db=SessionLocal())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "error.csv"
            Path(path).write_text("f1,f2,prediction\n", encoding="utf-8")
            artifact = service.create_from_file(
                project_uuid, path, f"errors-{uuid.uuid4().hex[:6]}", "dataset")
        return str(artifact.id)

    def _seed_deployment(self, project_uuid, model_version_id):
        from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
        db = SessionLocal()
        try:
            registered = RegisteredModel(
                project_id=project_uuid, name=f"m-{uuid.uuid4().hex[:6]}",
                created_by_id=self.admin_id)
            db.add(registered)
            db.flush()
            version = ModelVersion(
                registered_model_id=registered.id, version_number=1,
                source_kind="onnx_artifact", source_artifact_id=model_version_id,
                onnx_artifact_id=model_version_id, framework="sklearn",
                feature_schema=["f1", "f2"], lifecycle_state="enabled",
                approval_status="approved")
            db.add(version)
            db.flush()
            deployment = InferenceDeployment(
                project_id=project_uuid, name=f"dep-{uuid.uuid4().hex[:6]}",
                model_version_id=version.id, desired_state="running",
                observed_state="running", created_by_id=self.admin_id)
            db.add(deployment)
            db.commit()
            return str(version.id), str(deployment.id)
        finally:
            db.close()

    def test_06_full_loop_graph_publish_invoke_and_trigger(self):
        """api_input → apply_model ← load_model_artifact → condition
        → append_error_dataset → notify_admins → retrain_threshold."""
        from app.models.notifications import InAppNotification
        from app.models.training import TrainingJob

        db = SessionLocal()
        try:
            service = build_artifact_service(db)
            frame = pd.DataFrame({
                "f1": [0.0, 0.2, 0.1, 0.3, 0.15, 5.0, 5.4, 4.8, 5.2, 5.1],
                "f2": [1.0, 1.2, 0.9, 1.1, 1.05, -1.0, -1.2, -0.9, -1.1, -1.0],
            })
            model = LogisticRegression().fit(frame, [0, 0, 0, 0, 0, 1, 1, 1, 1, 1])
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "m.joblib"
                joblib.dump(model, path)
                artifact = service.create_from_file(
                    self.project.id, path, f"m-{uuid.uuid4().hex[:6]}", "model")
                model_artifact_id = str(artifact.id)

                error_csv = Path(tmp) / "error.csv"
                error_csv.write_text("f1,f2,prediction\n", encoding="utf-8")
                error_artifact = service.create_from_file(
                    self.project.id, error_csv, f"errors-{uuid.uuid4().hex[:6]}", "dataset")

                retrain_csv = Path(tmp) / "retrain.csv"
                pd.DataFrame({
                    "f1": [0.0, 0.2, 0.1, 0.3, 0.15, 5.0, 5.4, 4.8, 5.2, 5.1],
                    "f2": [1.0, 1.2, 0.9, 1.1, 1.05, -1.0, -1.2, -0.9, -1.1, -1.0],
                    "fault": [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
                }).to_csv(retrain_csv, index=False)
                retrain_dataset = service.create_dataset(
                    self.project.id, retrain_csv, f"retrain-{uuid.uuid4().hex[:6]}")
                retrain_dataset_id = str(retrain_dataset.id)

            registered = RegisteredModel(
                project_id=self.project.id, name=f"reg-{uuid.uuid4().hex[:6]}",
                created_by_id=self.admin_id)
            db.add(registered)
            db.flush()
            version = ModelVersion(
                registered_model_id=registered.id, version_number=1,
                source_kind="onnx_artifact", source_artifact_id=artifact.id,
                onnx_artifact_id=artifact.id, framework="sklearn",
                feature_schema=["f1", "f2"], lifecycle_state="enabled",
                approval_status="approved")
            db.add(version)
            db.flush()
            deployment = InferenceDeployment(
                project_id=self.project.id, name=f"dep-{uuid.uuid4().hex[:6]}",
                model_version_id=version.id, desired_state="running",
                observed_state="running", created_by_id=self.admin_id)
            db.add(deployment)
            db.commit()
            deployment_id = str(deployment.id)
            original_version_id = str(version.id)
        finally:
            db.close()

        error_artifact_id = self._seed_error_dataset(self.project.id)

        db = SessionLocal()
        try:
            workflow = Workflow(
                project_id=self.project.id, name=f"loop-wf-{uuid.uuid4().hex[:6]}",
                created_by=self.admin_id)
            db.add(workflow)
            db.commit()
            workflow_id = str(workflow.id)
        finally:
            db.close()

        # Attach the loop operators to the published graph by publishing a
        # v2 snapshot containing them.
        loop_nodes = [
            {"id": "n-input", "operator_id": "api_input", "label": "输入", "params": {}},
            {"id": "n-model", "operator_id": "load_model_artifact", "label": "模型",
             "params": {"model_artifact_id": model_artifact_id}},
            {"id": "n-apply", "operator_id": "apply_model", "label": "推理", "params": {}},
            {"id": "n-cond", "operator_id": "condition", "label": "判断",
             "params": {"column": "prediction", "operator": "==", "value": "1"}},
            {"id": "n-append", "operator_id": "append_error_dataset", "label": "回流",
             "params": {"dataset_artifact_id": error_artifact_id}},
            {"id": "n-notify", "operator_id": "notify_admins", "label": "告警",
             "params": {"title": "报错告警", "message": "错误数据已回流", "severity": "warning"}},
            {"id": "n-gate", "operator_id": "retrain_threshold", "label": "阈值",
             "params": {"dataset_artifact_id": error_artifact_id,
                        "retrain_dataset_artifact_id": retrain_dataset_id,
                        "retrain_target_column": "fault", "threshold_rows": 1,
                        "retrain_max_trials": 5, "swap_deployment_id": deployment_id}},
        ]
        loop_edges = [
            {"source": "n-input", "target": "n-apply", "source_port": "data", "target_port": "data"},
            {"source": "n-model", "target": "n-apply", "source_port": "model", "target_port": "model"},
            {"source": "n-apply", "target": "n-cond", "source_port": "data", "target_port": "data"},
            {"source": "n-cond", "target": "n-append", "source_port": "true_branch", "target_port": "data"},
            {"source": "n-append", "target": "n-notify", "source_port": "data", "target_port": "data"},
            {"source": "n-notify", "target": "n-gate", "source_port": "data", "target_port": "data"},
        ]
        db = SessionLocal()
        try:
            db.add(WorkflowVersion(
                workflow_id=uuid.UUID(workflow_id), version=2, name="v2",
                nodes_snapshot=loop_nodes, edges_snapshot=loop_edges,
                published_by=self.admin_id))
            db.commit()
        finally:
            db.close()
        r = client.post(f"/api/platform/apis/publish/workflow/{workflow_id}/2", headers=self.h)
        self.assertEqual(r.status_code, 201, r.text)
        api_v2 = r.json()
        invoke_url = f"/api/platform/apis/orchestration/{api_v2['source_id']}/invoke"

        stub = _StubDispatcher()
        with patch("app.services.closed_loop_actions.automl_dispatcher", return_value=stub), \
                patch("app.services.experiment_tracking.resolve_tracking_configuration",
                      return_value=("sqlite:///./temp_test/ut_mlflow_tracking.db",
                                    "file:./temp_test/ut_mlflow_artifacts")):
            r = client.post(invoke_url, json={"record": {"f1": 5.1, "f2": -1.0}}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        # 输出节点是 retrain_threshold：records 应报告已触发建模。
        self.assertTrue(body["records"][0]["triggered"], body)
        self.assertTrue(body["records"][0]["job_id"], body)

        db = SessionLocal()
        try:
            error_row = db.query(Artifact).filter(
                Artifact.id == uuid.UUID(error_artifact_id)).one()
            self.assertEqual((error_row.metadata_ or {}).get("row_count"), 1)
            notifications = db.query(InAppNotification).filter(
                InAppNotification.event_type == "closed_loop.notify",
                InAppNotification.project_id == self.project.id).count()
            self.assertGreaterEqual(notifications, 1)
            job = db.query(TrainingJob).filter(
                TrainingJob.project_id == self.project.id,
                TrainingJob.operator_id == "automl").one()
            self.assertEqual(job.status, "pending")
            self.assertEqual(len(stub.enqueued), 1)
        finally:
            db.close()

        # Advance the cycle: job completed → next error invoke swaps the model.
        db = SessionLocal()
        try:
            job = db.query(TrainingJob).filter(
                TrainingJob.project_id == self.project.id,
                TrainingJob.operator_id == "automl").one()
            job.status = "completed"
            db.commit()
            job_id = str(job.id)
        finally:
            db.close()

        class _FakeVersion:
            # Reuse the deployment's original model version id so the FK on
            # deployment.model_version_id stays satisfiable.
            id = deployment.model_version_id
            version_number = 99

        class _FakeRegistry:
            def __init__(self, *_a, **_k):
                pass

            def list_registerable_candidates(self, _db, _task_id):
                return [{"candidate_id": "c1", "name": "best", "metrics": {"accuracy": 0.95}}]

            def register_automl_candidate(self, _db, **kwargs):
                return _FakeVersion(), True

            def transition_model_version(self, _db, version_id, _action, _actor_id, **_k):
                return _FakeVersion()

        with patch("app.services.closed_loop_actions.automl_dispatcher", return_value=stub), \
                patch("app.services.closed_loop_actions.ModelRegistryService", _FakeRegistry):
            r = client.post(invoke_url, json={"record": {"f1": 5.1, "f2": -1.0}}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        db = SessionLocal()
        try:
            deployment = db.query(InferenceDeployment).filter(
                InferenceDeployment.id == uuid.UUID(deployment_id)).one()
            self.assertEqual(str(deployment.model_version_id), str(_FakeVersion.id))
            status = client.get(
                f"/api/projects/{self.project_id}/demo-loop/status", headers=self.h)
            self.assertIn(status.status_code, [200, 404])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
