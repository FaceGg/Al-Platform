"""Workflow Runs API integration tests."""
import sys, os, unittest, time, uuid, io
from datetime import datetime, timedelta, timezone
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine
from app.database import SessionLocal
from app.models.run import WorkflowRun
from app.api.runs import get_task_dispatcher
from tests.auth_test_support import ensure_admin

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestRunsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        ensure_admin()
        cls.h = login()
        # Create project
        r = client.post("/api/projects", json={"name": "RunTestProject"}, headers=cls.h)
        cls.project_id = r.json()["id"]

        # Upload test CSV
        csv = io.BytesIO(b"col1,col2\n1,2\n3,4\n5,6\n")
        r = client.post(
            f"/api/projects/{cls.project_id}/datasets/upload",
            files={"file": ("run_test.csv", csv, "text/csv")},
            headers=cls.h,
        )
        cls.dataset_artifact_id = r.json()["artifact_id"]
        assert "storage_path" not in r.json()

        # Create workflow
        r = client.post(f"/api/projects/{cls.project_id}/workflows", json={
            "name": "TestRunWorkflow", "nodes": [], "edges": [],
        }, headers=cls.h)
        cls.workflow_id = r.json()["id"]

        # Save workflow with a stable Artifact reference.
        r = client.put(f"/api/projects/{cls.project_id}/workflows/{cls.workflow_id}", json={
            "nodes": [
                {"id": "n1", "operator_id": "csv_import", "label": "Import",
                 "position": {"x": 100, "y": 100}, "params": {
                     "source": "artifact",
                     "dataset_artifact_id": cls.dataset_artifact_id,
                 }},
                {"id": "n2", "operator_id": "scaler", "label": "Scale",
                 "position": {"x": 300, "y": 100}, "params": {"method": "standard"}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "source_port": "data", "target": "n2", "target_port": "data"},
            ],
        }, headers=cls.h)

    def test_01_start_run(self):
        r = client.post(f"/api/workflows/{self.workflow_id}/run", headers=self.h)
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertIn("run_id", data)
        self.__class__.run_id = data["run_id"]

    def test_02_get_run(self):
        time.sleep(2)
        r = client.get(f"/api/runs/{self.run_id}", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("status", data)
        self.assertEqual(data["status"], "completed", data)
        self.assertTrue(data["node_runs"])
        self.assertTrue(all(node["status"] == "completed" for node in data["node_runs"]))

    def test_03_start_run_invalid_workflow(self):
        r = client.post(f"/api/workflows/{uuid.uuid4()}/run", headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_04_rejects_missing_required_parameters_before_creating_or_queueing_run(self):
        save = client.put(f"/api/projects/{self.project_id}/workflows/{self.workflow_id}", json={
            "nodes": [
                {"id": "n1", "operator_id": "csv_import", "label": "Import",
                 "position": {"x": 100, "y": 100}, "params": {"source": "local"}},
            ],
            "edges": [],
        }, headers=self.h)
        self.assertEqual(save.status_code, 200)

        calls = []
        dispatcher = type("Dispatcher", (), {
            "enqueue_workflow": lambda self, run_id: calls.append(run_id),
        })()
        app.dependency_overrides[get_task_dispatcher] = lambda: dispatcher
        try:
            with SessionLocal() as db:
                before = db.query(WorkflowRun).filter(
                    WorkflowRun.workflow_id == uuid.UUID(self.workflow_id),
                ).count()
            response = client.post(f"/api/workflows/{self.workflow_id}/run", headers=self.h)
        finally:
            app.dependency_overrides.pop(get_task_dispatcher, None)

        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "WORKFLOW_INVALID")
        self.assertTrue(any("OPERATOR_PARAM_REQUIRED" in error for error in detail["errors"]))
        self.assertEqual(calls, [])
        with SessionLocal() as db:
            after = db.query(WorkflowRun).filter(
                WorkflowRun.workflow_id == uuid.UUID(self.workflow_id),
            ).count()
        self.assertEqual(after, before)


class TestRunEmptyWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        ensure_admin()
        cls.h = login()
        r = client.post("/api/projects", json={"name": "EmptyRunProject"}, headers=cls.h)
        cls.project_id = r.json()["id"]
        r = client.post(f"/api/projects/{cls.project_id}/workflows", json={
            "name": "EmptyWorkflow", "nodes": [], "edges": [],
        }, headers=cls.h)
        cls.workflow_id = r.json()["id"]

    def test_start_run_empty(self):
        r = client.post(f"/api/workflows/{self.workflow_id}/run", headers=self.h)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"]["code"], "WORKFLOW_EMPTY")


class TestRunCancellation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin(username="cancel_admin")
        login_response = client.post(
            "/api/auth/login", data={"username": "cancel_admin", "password": "admin123"},
        )
        cls.headers = {"Authorization": "Bearer " + login_response.json()["access_token"]}
        project = client.post("/api/projects", json={"name": "Cancel Project"}, headers=cls.headers)
        workflow = client.post(
            f"/api/projects/{project.json()['id']}/workflows",
            json={"name": "Cancel Workflow", "nodes": [], "edges": []},
            headers=cls.headers,
        )
        cls.workflow_id = workflow.json()["id"]
        with SessionLocal() as db:
            run = WorkflowRun(workflow_id=uuid.UUID(cls.workflow_id), status="pending")
            db.add(run)
            db.commit()
            db.refresh(run)
            cls.run_id = str(run.id)

    def test_cancel_is_idempotent(self):
        from unittest.mock import patch
        from app.config import settings

        calls = []
        dispatcher = type("Dispatcher", (), {
            "cancel": lambda self, task_id, terminate=False: calls.append(
                (task_id, terminate),
            ),
        })()
        with SessionLocal() as db:
            run = db.query(WorkflowRun).filter(
                WorkflowRun.id == uuid.UUID(self.run_id),
            ).one()
            run.task_id = "celery-task-1"
            db.commit()
        app.dependency_overrides[get_task_dispatcher] = lambda: dispatcher
        try:
            # Local-mode cancellation is cooperative: repeated cancels keep the
            # run in cancel_requested. (Under the celery backend the first
            # cancel finalizes to 'cancelled' — covered by
            # TestCancelFinalizesUnderCelery.)
            with patch.object(settings, "task_backend", "local"):
                first = client.post(f"/api/runs/{self.run_id}/cancel", headers=self.headers)
                second = client.post(f"/api/runs/{self.run_id}/cancel", headers=self.headers)
        finally:
            app.dependency_overrides.pop(get_task_dispatcher, None)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], "cancel_requested")
        self.assertEqual(calls, [("celery-task-1", True), ("celery-task-1", True)])


class TestCancelFinalizesUnderCelery(unittest.TestCase):
    """Celery terminate kills the worker process; the cancel API must persist
    the final 'cancelled' status itself, otherwise runs spin forever."""

    @classmethod
    def setUpClass(cls):
        ensure_admin(username="celery_cancel_admin")
        login_response = client.post(
            "/api/auth/login", data={"username": "celery_cancel_admin", "password": "admin123"},
        )
        cls.headers = {"Authorization": "Bearer " + login_response.json()["access_token"]}
        project = client.post("/api/projects", json={"name": "Celery Cancel Project"}, headers=cls.headers)
        workflow = client.post(
            f"/api/projects/{project.json()['id']}/workflows",
            json={"name": "Celery Cancel Workflow", "nodes": [], "edges": []},
            headers=cls.headers,
        )
        cls.workflow_id = workflow.json()["id"]
        cls._run_seq = 0

    def _make_run(self, status: str, task_id: str) -> str:
        with SessionLocal() as db:
            # Real runs get started_at set by the executor once claimed;
            # mirror that so latest-run ordering is deterministic. Windows
            # clock granularity can make back-to-back datetime.now() calls
            # return the same value, so space runs a second apart.
            started_at = datetime.now(timezone.utc) + timedelta(seconds=self.__class__._run_seq)
            self.__class__._run_seq += 1
            run = WorkflowRun(
                workflow_id=uuid.UUID(self.workflow_id), status=status, task_id=task_id,
                started_at=started_at,
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            return str(run.id)

    def test_cancel_under_celery_finalizes_cancelled(self):
        from unittest.mock import patch
        from app.config import settings

        run_id = self._make_run("running", "celery-task-2")
        calls = []
        dispatcher = type("Dispatcher", (), {
            "cancel": lambda self, task_id, terminate=False: calls.append(task_id),
        })()
        app.dependency_overrides[get_task_dispatcher] = lambda: dispatcher
        try:
            with patch.object(settings, "task_backend", "celery"):
                response = client.post(f"/api/runs/{run_id}/cancel", headers=self.headers)
        finally:
            app.dependency_overrides.pop(get_task_dispatcher, None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(calls, ["celery-task-2"])
        with SessionLocal() as db:
            run = db.query(WorkflowRun).filter(WorkflowRun.id == uuid.UUID(run_id)).one()
            self.assertEqual(run.status, "cancelled")
            self.assertIsNotNone(run.finished_at)

    def test_active_run_endpoint(self):
        # No active run yet for a fresh workflow: null.
        r = client.get(f"/api/workflows/{self.workflow_id}/runs/active", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["run"])

        active_id = self._make_run("running", "celery-task-3")
        r = client.get(f"/api/workflows/{self.workflow_id}/runs/active", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        run = r.json()["run"]
        self.assertIsNotNone(run)
        self.assertEqual(run["id"], active_id)
        self.assertEqual(run["status"], "running")

        # Cancelled runs are terminal and must not be reported as active.
        with SessionLocal() as db:
            db_run = db.query(WorkflowRun).filter(WorkflowRun.id == uuid.UUID(active_id)).one()
            db_run.status = "cancelled"
            db_run.finished_at = datetime.now(timezone.utc)
            db.commit()
        r = client.get(f"/api/workflows/{self.workflow_id}/runs/active", headers=self.headers)
        self.assertIsNone(r.json()["run"])

    def test_latest_run_endpoint(self):
        # Returns the most recent run regardless of state (completed included) —
        # unlike /runs/active which only reports pending/running runs.
        first_id = self._make_run("completed", "celery-task-4")
        second_id = self._make_run("failed", "celery-task-5")
        r = client.get(f"/api/workflows/{self.workflow_id}/runs/latest", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        run = r.json()["run"]
        self.assertIsNotNone(run)
        self.assertEqual(run["id"], second_id)
        self.assertEqual(run["status"], "failed")
        self.assertNotEqual(run["id"], first_id)


if __name__ == "__main__":
    unittest.main()
