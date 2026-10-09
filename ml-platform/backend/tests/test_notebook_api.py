"""Week 15 notebook API contract tests: schema/migration guards, idempotent
start, catalog-bound images, project/user isolation, idle sweep, access token
semantics and the cluster-credential-free response guarantee."""

import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, ".")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import create_engine, inspect  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.access import AuditEvent  # noqa: E402
from app.schemas.developer_resources import NotebookResponse  # noqa: E402
from app.services import kubernetes_cluster as cluster_service  # noqa: E402
from app.services.kubernetes_client import FakeKubernetesClient  # noqa: E402
from tests.utils_week14 import (  # noqa: E402
    apply_job_settings,
    ensure_active_cluster,
    ensure_project,
    ensure_user,
    restore_job_settings,
)
from tests.utils_week15 import (  # noqa: E402
    cleanup_week15_rows,
    ensure_image,
    image_ref,
    notebook_payload,
)

Base.metadata.create_all(bind=engine)
client = TestClient(app)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMP_ROOT = PROJECT_ROOT / "temp_test"
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

WEEK15_TABLES = {"notebook_sessions", "container_images", "image_builds", "gpu_resource_classes"}


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


class TestDeveloperResourceSchema(unittest.TestCase):
    def test_01_session_status_is_a_closed_enum(self):
        base = {
            "id": uuid.uuid4(),
            "project_id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "cluster_id": uuid.uuid4(),
            "namespace": "w15",
            "job_name": "lr-notebook-aaaaaaaa-1",
            "image_ref": "registry.local/w15/notebook-base@sha256:" + "b" * 64,
            "resource_json": {},
            "status": "starting",
            "idle_timeout_seconds": 3600,
        }
        NotebookResponse.model_validate(base)
        with self.assertRaises(ValidationError):
            NotebookResponse.model_validate({**base, "status": "teleported"})

    def test_02_upgrade_head_creates_week15_tables_and_check_passes(self):
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
                self.assertTrue(WEEK15_TABLES.issubset(set(inspector.get_table_names())))
                session_uniques = {u["name"] for u in inspector.get_unique_constraints("notebook_sessions")}
                self.assertIn("uq_notebook_sessions_operation", session_uniques)
                image_uniques = {u["name"] for u in inspector.get_unique_constraints("container_images")}
                self.assertIn("uq_container_images_digest", image_uniques)
                gpu_uniques = {u["name"] for u in inspector.get_unique_constraints("gpu_resource_classes")}
                self.assertIn("uq_gpu_resource_classes_cluster_name", gpu_uniques)
            finally:
                db_engine.dispose()

    def test_03_downgrade_drops_week15_tables_and_keeps_unrelated(self):
        with _TemporaryDatabase() as database_url:
            config = Config(str(ALEMBIC_INI))
            original_url = settings.database_url
            settings.database_url = database_url
            try:
                command.upgrade(config, "head")
                command.downgrade(config, "20261006_65")
            finally:
                settings.database_url = original_url
            db_engine = create_engine(database_url)
            try:
                tables = set(inspect(db_engine).get_table_names())
                self.assertFalse(WEEK15_TABLES & tables)
                self.assertIn("kubernetes_job_runs", tables)
                self.assertIn("projects", tables)
            finally:
                db_engine.dispose()
            settings.database_url = database_url
            try:
                command.upgrade(config, "head")
                command.check(config)
            finally:
                settings.database_url = original_url


class TestNotebookAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._previous_settings = apply_job_settings()
        cls.admin = ensure_user("w15nb-admin", "admin")
        cls.other = ensure_user("w15nb-outsider", "engineer")
        cls.project = ensure_project("w15nb-project", cls.admin.id)
        cls.other_project = ensure_project("w15nb-other-project", cls.other.id)
        cleanup_week15_rows()
        cls.image = ensure_image(cls.project.id, cls.admin.id)
        cls.bad_image = ensure_image(cls.project.id, cls.admin.id, repository="w15/scan-failed", scan_status="failed")
        cls.cluster = ensure_active_cluster("w15nb-cluster", cls.project.id, cls.admin.id, namespace="w15-notebooks")
        cls.other_cluster = ensure_active_cluster(
            "w15nb-other-cluster", cls.other_project.id, cls.other.id, namespace="w15-notebooks"
        )
        cls.fake = FakeKubernetesClient()
        cluster_service.client_factory = lambda cluster, ref: cls.fake
        cls.h = cls._login("w15nb-admin")
        cls.other_h = cls._login("w15nb-outsider")

    @classmethod
    def tearDownClass(cls):
        cluster_service.client_factory = None
        restore_job_settings(cls._previous_settings)

    @staticmethod
    def _login(username: str):
        r = client.post("/api/auth/login", data={"username": username, "password": "w14password"})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    def tearDown(self):
        """Stop this user's active sessions so the concurrency cap never
        leaks between tests."""
        listed = client.get("/api/notebooks", headers=self.h).json()
        for item in listed.get("items", []):
            if item["status"] not in ("stopped", "failed", "terminated"):
                client.post(f"/api/notebooks/{item['id']}/stop", headers=self.h)

    def _start(self, headers=None, **overrides):
        key = overrides.pop("_key", f"w15-nb-{uuid.uuid4()}")
        payload = notebook_payload(self.cluster.id, self.image, **overrides)
        r = client.post(
            "/api/notebooks",
            json=payload,
            headers={**(headers or self.h), "Idempotency-Key": key},
        )
        self.assertIn(r.status_code, (200, 201, 429), r.text)
        return r

    def _start_raw(self, headers=None, **overrides):
        """No status assertion: for tests that expect rejection."""
        key = overrides.pop("_key", f"w15-nb-{uuid.uuid4()}")
        payload = notebook_payload(self.cluster.id, self.image, **overrides)
        return client.post(
            "/api/notebooks",
            json=payload,
            headers={**(headers or self.h), "Idempotency-Key": key},
        )

    def _latest_session(self):
        from app.models.developer_resources import NotebookSession

        db = SessionLocal()
        try:
            return db.query(NotebookSession).order_by(NotebookSession.created_at.desc()).first()
        finally:
            db.close()

    def test_04_start_session_creates_running_notebook_job(self):
        r = self._start()
        self.assertEqual(201, r.status_code, r.text)
        data = r.json()
        self.assertIn(data["status"], ("starting", "running"))
        self.assertNotIn(data["image_ref"], (None, ""))
        created = client.get(f"/api/notebooks/{data['id']}", headers=self.h)
        self.assertEqual(200, created.status_code)
        # The cluster-side Job carries the notebook role label.
        job_names = list(self.fake.jobs)
        self.assertTrue(job_names)
        labels = self.fake.jobs[job_names[0]]["labels"]
        self.assertEqual("notebook", labels.get("linkraft.io/role"))

    def test_05_replay_returns_same_session(self):
        key = "w15-nb-replay"
        first = self._start(_key=key)
        self.assertEqual(201, first.status_code)
        second = self._start(_key=key)
        self.assertEqual(200, second.status_code)
        self.assertEqual(first.json()["id"], second.json()["id"])

    def test_06_unknown_image_rejected(self):
        payload = notebook_payload(
            self.cluster.id, self.image, image_ref="registry.local/w15/ghost@sha256:" + "c" * 64
        )
        r = client.post(
            "/api/notebooks", json=payload, headers={**self.h, "Idempotency-Key": f"w15-nb-{uuid.uuid4()}"}
        )
        self.assertEqual(422, r.status_code)
        self.assertEqual("NOTEBOOK_IMAGE_NOT_IN_CATALOG", r.json()["detail"]["code"])

    def test_07_failed_scan_image_rejected(self):
        r = self._start_raw(image_ref=image_ref(self.bad_image))
        self.assertEqual(422, r.status_code)
        self.assertEqual("NOTEBOOK_IMAGE_SCAN_FAILED", r.json()["detail"]["code"])

    def test_08_cross_project_is_hidden_404(self):
        started = self._start()
        session_id = started.json()["id"]
        foreign = client.get(f"/api/notebooks/{session_id}", headers=self.other_h)
        self.assertEqual(404, foreign.status_code)
        listed = client.get("/api/notebooks", headers=self.other_h)
        self.assertEqual(200, listed.status_code)
        self.assertEqual(0, listed.json()["total"])

    def test_09_access_token_flow(self):
        started = self._start()
        session_id = started.json()["id"]
        client.post(f"/api/notebooks/{session_id}/reconcile", headers=self.h)
        access = client.post(f"/api/notebooks/{session_id}/access", headers=self.h)
        self.assertEqual(200, access.status_code, access.text)
        body = access.json()
        self.assertIn("token", body)
        self.assertIn("url", body)
        self.assertNotIn("LINKRAFT_W14_TOKEN", body["url"])
        self.assertNotIn("test-token-material", str(body))
        # Expired token -> 401
        from app.services import notebook_service

        expired = notebook_service.mint_access_token(settings, session_id, self.admin.id, ttl_seconds=-1)
        probe = client.get(f"/api/notebooks/{session_id}/proxy/api?token={expired}")
        self.assertIn(probe.status_code, (401, 404))

    def test_10_stop_is_idempotent_and_terminal_once(self):
        started = self._start()
        session_id = started.json()["id"]
        job_name = started.json()["job_name"]
        first = client.post(f"/api/notebooks/{session_id}/stop?reason=w15 test", headers=self.h)
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual("stopped", first.json()["status"])
        self.assertTrue(self.fake.jobs[job_name]["deleted"])
        self.assertTrue(self.fake.services.get(job_name) is None)
        second = client.post(f"/api/notebooks/{session_id}/stop?reason=again", headers=self.h)
        self.assertEqual(200, second.status_code)
        self.assertEqual("stopped", second.json()["status"])

    def test_11_delete_is_idempotent(self):
        started = self._start()
        session_id = started.json()["id"]
        first = client.delete(f"/api/notebooks/{session_id}", headers=self.h)
        self.assertIn(first.status_code, (200, 204))
        second = client.delete(f"/api/notebooks/{session_id}", headers=self.h)
        self.assertIn(second.status_code, (200, 204, 404))

    def test_12_idle_sweep_recovers_only_expired_running_sessions(self):
        from app.models.developer_resources import NotebookSession
        from app.services import notebook_service

        fresh = self._start().json()
        stale = self._start().json()
        db = SessionLocal()
        try:
            row = db.get(NotebookSession, uuid.UUID(stale["id"]))
            row.last_activity_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
                seconds=row.idle_timeout_seconds + 60
            )
            db.commit()
        finally:
            db.close()
        swept = notebook_service.sweep_idle_sessions(SessionLocal(), None, settings, now=None)
        self.assertIn(stale["id"], swept)
        self.assertNotIn(fresh["id"], swept)
        stopped = client.get(f"/api/notebooks/{stale['id']}", headers=self.h).json()
        self.assertEqual("stopped", stopped["status"])
        db = SessionLocal()
        try:
            event = (
                db.query(AuditEvent)
                .filter(AuditEvent.action == "notebook.idle_timeout", AuditEvent.result == "success")
                .order_by(AuditEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(event)
        finally:
            db.close()

    def test_13_concurrency_cap_returns_429(self):
        # A dedicated user so active sessions from earlier tests don't count.
        from tests.utils_week14 import ensure_member

        capped = ensure_user("w15nb-capped", "engineer")
        ensure_member(self.project.id, capped.id, "operator")
        capped_h = self._login("w15nb-capped")
        previous = settings.notebook_max_per_user
        settings.notebook_max_per_user = 1
        try:
            payload = notebook_payload(self.cluster.id, self.image)
            first = client.post(
                "/api/notebooks", json=payload, headers={**capped_h, "Idempotency-Key": f"w15-cap-{uuid.uuid4()}"}
            )
            self.assertEqual(201, first.status_code, first.text)
            second = client.post(
                "/api/notebooks", json=payload, headers={**capped_h, "Idempotency-Key": f"w15-cap-{uuid.uuid4()}"}
            )
            self.assertEqual(429, second.status_code)
            self.assertEqual("NOTEBOOK_CONCURRENCY_LIMIT", second.json()["detail"]["code"])
        finally:
            settings.notebook_max_per_user = previous


if __name__ == "__main__":
    unittest.main()
