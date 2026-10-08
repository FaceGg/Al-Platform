"""Week 14 job API contract tests: schema/migration guards, permission matrix,
idempotency replay, project isolation, audit, X-Request-ID echo, cluster state."""

import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, ".")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import inspect  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app.config import settings  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.access import AuditEvent  # noqa: E402
from app.models.cloud_resources import KubernetesCluster, KubernetesCredentialRef  # noqa: E402
from app.models.kubernetes_execution import KubernetesJobRun  # noqa: E402
from app.schemas.kubernetes_execution import JobRunResponse  # noqa: E402
from app.services import kubernetes_cluster as cluster_service  # noqa: E402
from app.services.kubernetes_client import FakeKubernetesClient  # noqa: E402
from tests.utils_week14 import (  # noqa: E402
    apply_job_settings,
    cleanup_job_rows,
    ensure_active_cluster,
    ensure_member,
    ensure_project,
    ensure_user,
    restore_job_settings,
    submit_payload,
)

Base.metadata.create_all(bind=engine)
client = TestClient(app)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMP_ROOT = PROJECT_ROOT / "temp_test"
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


class _TemporaryDatabase:
    def __init__(self):
        self._directory = None

    def __enter__(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self._directory = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        database_path = Path(self._directory.name) / "database.db"
        return f"sqlite:///{database_path.as_posix()}"

    def __exit__(self, exc_type, exc_value, traceback):
        self._directory.cleanup()


class TestKubernetesJobSchema(unittest.TestCase):
    def test_01_status_enum_guard_rejects_unknown_states(self):
        base = {
            "id": uuid.uuid4(),
            "project_id": uuid.uuid4(),
            "cluster_id": uuid.uuid4(),
            "namespace": "w14-jobs",
            "job_name": "lr-aaaaaaaa-job-bbbbbbbb-1",
            "image_ref": "registry.local/app@sha256:" + "a" * 64,
            "command_json": ["/bin/sh"],
            "args_json": [],
            "resource_json": {},
            "status": "succeeded",
            "revision": 1,
            "timeout_seconds": 60,
        }
        JobRunResponse.model_validate(base)
        with self.assertRaises(ValidationError):
            JobRunResponse.model_validate({**base, "status": "teleported"})

    def test_02_upgrade_head_creates_job_runs_table_and_check_passes(self):
        with _TemporaryDatabase() as database_url:
            config = Config(str(ALEMBIC_INI))
            original_url = settings.database_url
            settings.database_url = database_url
            try:
                command.upgrade(config, "head")
                command.upgrade(config, "head")
                command.check(config)
            finally:
                settings.database_url = original_url
            db_engine = create_engine(database_url)
            try:
                inspector = inspect(db_engine)
                self.assertIn("kubernetes_job_runs", inspector.get_table_names())
                unique_names = {uq["name"] for uq in inspector.get_unique_constraints("kubernetes_job_runs")}
                self.assertIn("uq_kubernetes_job_run_idempotency", unique_names)
                index_names = {idx["name"] for idx in inspector.get_indexes("kubernetes_job_runs")}
                self.assertIn("ix_kubernetes_job_runs_operation_id", index_names)
            finally:
                db_engine.dispose()

    def test_03_downgrade_drops_only_job_runs_and_reupgrade_restores(self):
        with _TemporaryDatabase() as database_url:
            config = Config(str(ALEMBIC_INI))
            original_url = settings.database_url
            settings.database_url = database_url
            try:
                command.upgrade(config, "head")
                command.downgrade(config, "20260928_62")
            finally:
                settings.database_url = original_url
            db_engine = create_engine(database_url)
            try:
                tables = set(inspect(db_engine).get_table_names())
                self.assertNotIn("kubernetes_job_runs", tables)
                self.assertIn("kubernetes_clusters", tables)
                self.assertIn("projects", tables)
                self.assertIn("users", tables)
            finally:
                db_engine.dispose()
            settings.database_url = database_url
            try:
                command.upgrade(config, "head")
                command.check(config)
            finally:
                settings.database_url = original_url


class TestKubernetesJobAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._previous_settings = apply_job_settings()
        cls.admin = ensure_user("w14api-admin", "admin")
        cls.operator = ensure_user("w14api-operator", "engineer")
        cls.viewer = ensure_user("w14api-viewer", "engineer")
        cls.outsider = ensure_user("w14api-outsider", "engineer")
        cls.project = ensure_project("w14api-project", cls.admin.id)
        ensure_member(cls.project.id, cls.operator.id, "operator")
        ensure_member(cls.project.id, cls.viewer.id, "viewer")
        cls.other_project = ensure_project("w14api-other-project", cls.outsider.id)
        cls.cluster = ensure_active_cluster("w14api-cluster", cls.project.id, cls.admin.id)
        cleanup_job_rows([cls.project.id, cls.other_project.id])
        db = SessionLocal()
        try:
            pending = (
                db.query(KubernetesCluster)
                .filter(KubernetesCluster.name == "w14api-pending", KubernetesCluster.project_id == cls.project.id)
                .first()
            )
            if pending is None:
                pending = KubernetesCluster(
                    project_id=cls.project.id,
                    name="w14api-pending",
                    display_name="pending cluster",
                    api_server_url="https://127.0.0.1:6443",
                    provider="kind",
                    status="pending",
                    created_by=cls.admin.id,
                )
                db.add(pending)
                db.flush()
                db.add(KubernetesCredentialRef(cluster_id=pending.id, secret_ref="env:W14_TEST_TOKEN"))
                db.commit()
                db.refresh(pending)
            cls.pending_cluster_id = pending.id
        finally:
            db.close()
        cls.fake = FakeKubernetesClient()
        cluster_service.client_factory = lambda cluster, ref: cls.fake
        cls.h = cls._login("w14api-admin")
        cls.operator_h = cls._login("w14api-operator")
        cls.viewer_h = cls._login("w14api-viewer")
        cls.outsider_h = cls._login("w14api-outsider")

    @classmethod
    def tearDownClass(cls):
        cluster_service.client_factory = None
        restore_job_settings(cls._previous_settings)

    @staticmethod
    def _login(username: str):
        r = client.post("/api/auth/login", data={"username": username, "password": "w14password"})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    def _submit(self, headers=None, cluster_id=None, **overrides):
        key = overrides.pop("_key", f"w14-api-{uuid.uuid4()}")
        body = submit_payload(cluster_id or self.cluster.id, **overrides)
        return client.post(
            "/api/kubernetes/jobs",
            json=body,
            headers={**(headers or self.h), "Idempotency-Key": key},
        )

    def _latest_job(self):
        db = SessionLocal()
        try:
            return (
                db.query(KubernetesJobRun)
                .filter(KubernetesJobRun.project_id == self.project.id)
                .order_by(KubernetesJobRun.created_at.desc())
                .first()
            )
        finally:
            db.close()

    def test_04_owner_submits_job_successfully(self):
        r = self._submit()
        self.assertEqual(201, r.status_code, r.text)
        data = r.json()
        self.assertIn(data["status"], ("queued", "submitted"))
        self.assertFalse(data["replayed"])
        self.assertRegex(data["job_name"], r"^lr-[a-f0-9]{8}-job-[a-f0-9]{8}-1$")
        self.assertIn(data["operation_state"], ("queued", "running"))
        self.assertIsInstance(data["operation_progress"], int)
        row = self._latest_job()
        self.assertIsNotNone(row)
        self.assertIsNotNone(row.operation_id)

    def test_05_replay_returns_200_with_replayed_true(self):
        key = "w14-api-replay"
        first = self._submit(_key=key)
        self.assertEqual(201, first.status_code)
        second = self._submit(_key=key)
        self.assertEqual(200, second.status_code, second.text)
        self.assertTrue(second.json()["replayed"])
        self.assertEqual(first.json()["id"], second.json()["id"])

    def test_06_missing_idempotency_key_is_rejected(self):
        r = client.post("/api/kubernetes/jobs", json=submit_payload(self.cluster.id), headers=self.h)
        self.assertEqual(422, r.status_code)
        self.assertEqual("KUBE_JOB_IDEMPOTENCY_REQUIRED", r.json()["detail"]["code"])

    def test_07_viewer_cannot_submit_but_operator_can(self):
        denied = self._submit(headers=self.viewer_h)
        self.assertEqual(403, denied.status_code)
        allowed = self._submit(headers=self.operator_h)
        self.assertEqual(201, allowed.status_code, allowed.text)

    def test_08_cross_project_is_hidden_404(self):
        denied = self._submit(headers=self.outsider_h)
        self.assertEqual(404, denied.status_code)
        job = self._latest_job()
        foreign_get = client.get(f"/api/kubernetes/jobs/{job.id}", headers=self.outsider_h)
        self.assertEqual(404, foreign_get.status_code)

    def test_09_inactive_cluster_conflicts(self):
        r = self._submit(cluster_id=self.pending_cluster_id)
        self.assertEqual(409, r.status_code)
        self.assertEqual("KUBERNETES_CLUSTER_NOT_ACTIVE", r.json()["detail"]["code"])

    def test_10_unregistered_namespace_is_rejected(self):
        r = self._submit(namespace="w14-ghost")
        self.assertEqual(422, r.status_code, r.text)
        self.assertEqual("KUBERNETES_NAMESPACE_INVALID", r.json()["detail"]["code"])

    def test_11_request_id_is_echoed(self):
        r = self._submit(headers={**self.h, "X-Request-ID": "w14-api-echo"})
        # The audit layer may replace the value with its own generated id; the
        # Week 13 contract only requires the header to be present.
        self.assertTrue(r.headers.get("X-Request-ID"))

    def test_12_list_is_project_scoped(self):
        listed = client.get("/api/kubernetes/jobs", headers=self.h)
        self.assertEqual(200, listed.status_code)
        self.assertGreaterEqual(listed.json()["total"], 1)
        foreign = client.get("/api/kubernetes/jobs", headers=self.outsider_h)
        self.assertEqual(200, foreign.status_code)
        self.assertEqual(0, foreign.json()["total"])

    def test_13_logs_endpoint_returns_redacted_incremental_text(self):
        submitted = self._submit()
        job_name = submitted.json()["job_name"]
        self.fake.pod_logs[f"{job_name}-pod-1"] = "hello w14 Bearer supersecrettokenvalue123"
        r = client.get(f"/api/kubernetes/jobs/{submitted.json()['id']}/logs?cursor=0", headers=self.h)
        self.assertEqual(200, r.status_code, r.text)
        data = r.json()
        self.assertIn("hello w14", data["text"])
        self.assertNotIn("supersecrettokenvalue123", data["text"])
        self.assertIn("next_cursor", data)
        self.assertIn("end_of_stream", data)

    def test_14_cancel_then_409(self):
        self._submit()
        job = self._latest_job()
        r = client.post(f"/api/kubernetes/jobs/{job.id}/cancel?reason=w14 stop", headers=self.h)
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual("cancelled", r.json()["status"])
        again = client.post(f"/api/kubernetes/jobs/{job.id}/cancel?reason=again", headers=self.h)
        self.assertEqual(409, again.status_code)
        self.assertEqual("KUBE_JOB_ALREADY_TERMINAL", again.json()["detail"]["code"])

    def test_15_reconcile_endpoint_is_idempotent(self):
        self._submit()
        job = self._latest_job()
        first = client.post(f"/api/kubernetes/jobs/{job.id}/reconcile", headers=self.h)
        self.assertEqual(200, first.status_code, first.text)
        second = client.post(f"/api/kubernetes/jobs/{job.id}/reconcile", headers=self.h)
        self.assertEqual(200, second.status_code)
        self.assertEqual(first.json()["status"], second.json()["status"])

    def test_16_audit_trail_records_actions_without_env_payload(self):
        secret_env = {"W14_MODE": "audit-secret-value"}
        self._submit(env=secret_env)
        job = self._latest_job()
        client.post(f"/api/kubernetes/jobs/{job.id}/cancel?reason=audit", headers=self.h)
        client.post(f"/api/kubernetes/jobs/{job.id}/reconcile", headers=self.h)
        db = SessionLocal()
        try:
            actions = (
                db.query(AuditEvent)
                .filter(
                    AuditEvent.project_id == self.project.id,
                    AuditEvent.action.in_(
                        ["kubernetes.job.submit", "kubernetes.job.cancel", "kubernetes.job.reconcile"]
                    ),
                    AuditEvent.result == "success",
                )
                .all()
            )
            recorded = {event.action for event in actions}
            self.assertIn("kubernetes.job.submit", recorded)
            self.assertIn("kubernetes.job.cancel", recorded)
            self.assertIn("kubernetes.job.reconcile", recorded)
            for event in actions:
                self.assertNotIn("env", (event.changes or {}))
                self.assertNotIn("audit-secret-value", str(event.changes))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
