"""Week 16 reservation/quota contract tests: no-oversell under concurrency,
four idempotent release paths, quota CRUD with revision and audit."""

import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.access import AuditEvent  # noqa: E402
from app.models.resource_governance import ResourceReservation  # noqa: E402
from app.services import resource_governance  # noqa: E402
from app.services.cluster_scheduler import release_reservation, reserve  # noqa: E402
from app.services.kubernetes_executor import KubeJobError  # noqa: E402
from tests.utils_week14 import ensure_active_cluster, ensure_project, ensure_user  # noqa: E402
from tests.utils_week16 import cleanup_week16_rows, ensure_operation, ensure_quota_policy  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(app)


class TestReservations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = ensure_user("w16rq-admin", "admin")
        cls.project = ensure_project("w16rq-project", cls.admin.id)
        cls.cluster = ensure_active_cluster("w16rq-cluster", cls.project.id, cls.admin.id)
        cleanup_week16_rows()

    def _reservation_count(self, state=None):
        db = SessionLocal()
        try:
            query = db.query(ResourceReservation).filter(
                ResourceReservation.project_id == self.project.id
            )
            if state:
                query = query.filter(ResourceReservation.state == state)
            return query.count()
        finally:
            db.close()

    def test_04_reserve_creates_one_active_row_per_operation(self):
        op_id = uuid.uuid4()
        ensure_operation(op_id, self.project.id)
        reserved = reserve(
            SessionLocal(),
            project_id=self.project.id,
            cluster_id=self.cluster.id,
            operation_id=op_id,
            reserved_json={"cpu_cores": 1, "memory_mb": 1024, "gpu_count": 0},
        )
        self.assertEqual("active", reserved.state)
        self.assertEqual(1, self._reservation_count("active"))
        release_reservation(SessionLocal(), op_id, "terminal")
        self.assertEqual(0, self._reservation_count("active"))
        self.assertEqual(1, self._reservation_count("released"))

    def test_05_quota_exceeded_rejects_and_leaves_no_row(self):
        ensure_quota_policy("project", self.project.id, {"cpu_cores": 2, "memory_mb": 4096, "max_concurrent_jobs": 8})
        first_op = uuid.uuid4()
        ensure_operation(first_op, self.project.id)
        try:
            reserve(
                SessionLocal(),
                project_id=self.project.id,
                cluster_id=self.cluster.id,
                operation_id=first_op,
                reserved_json={"cpu_cores": 1, "memory_mb": 1024, "gpu_count": 0},
            )
            second_op = uuid.uuid4()
            ensure_operation(second_op, self.project.id)
            with self.assertRaises(KubeJobError) as raised:
                reserve(
                    SessionLocal(),
                    project_id=self.project.id,
                    cluster_id=self.cluster.id,
                    operation_id=second_op,
                    reserved_json={"cpu_cores": 2, "memory_mb": 1024, "gpu_count": 0},
                )
            self.assertEqual("QUOTA_EXCEEDED", raised.exception.code)
            self.assertEqual(1, self._reservation_count("active"))
        finally:
            for row in SessionLocal().query(ResourceReservation).all():
                pass
            db = SessionLocal()
            try:
                db.query(ResourceReservation).delete(synchronize_session=False)
                db.commit()
            finally:
                db.close()

    def test_06_concurrent_reservations_never_oversell(self):
        # quota: 4 cpu -> exactly 4 of 8 concurrent 1-cpu requests may win.
        ensure_quota_policy("project", self.project.id, {"cpu_cores": 4, "memory_mb": 8192, "max_concurrent_jobs": 16})
        db = SessionLocal()
        try:
            db.query(ResourceReservation).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

        def attempt(index: int) -> bool:
            op_id = uuid.uuid4()
            ensure_operation(op_id, self.project.id)
            try:
                reserve(
                    SessionLocal(),
                    project_id=self.project.id,
                    cluster_id=self.cluster.id,
                    operation_id=op_id,
                    reserved_json={"cpu_cores": 1, "memory_mb": 512, "gpu_count": 0},
                )
                return True
            except KubeJobError:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(4, sum(1 for ok in results if ok))
        self.assertEqual(4, self._reservation_count("active"))
        self.assertEqual(4, sum(1 for ok in results if not ok))

    def test_07_release_is_idempotent_across_four_paths(self):
        op = uuid.uuid4()
        ensure_operation(op, self.project.id)
        cleanup = SessionLocal()
        try:
            cleanup.query(ResourceReservation).delete(synchronize_session=False)
            cleanup.commit()
        finally:
            cleanup.close()
        reserve(
            SessionLocal(),
            project_id=self.project.id,
            cluster_id=self.cluster.id,
            operation_id=op,
            reserved_json={"cpu_cores": 1, "memory_mb": 512, "gpu_count": 0},
        )
        for reason in ("terminal", "orphaned", "expired", "manual"):
            release_reservation(SessionLocal(), op, reason)
        db = SessionLocal()
        try:
            rows = db.query(ResourceReservation).filter(ResourceReservation.operation_id == op).all()
            self.assertEqual(1, len(rows))
            self.assertEqual("released", rows[0].state)
            self.assertEqual("terminal", rows[0].release_reason)
            self.assertIsNotNone(rows[0].released_at)
        finally:
            db.close()

    def test_08_expired_sweep_releases_reservations_of_terminal_operations(self):
        op = uuid.uuid4()
        ensure_operation(op, self.project.id, state="running")
        reserve(
            SessionLocal(),
            project_id=self.project.id,
            cluster_id=self.cluster.id,
            operation_id=op,
            reserved_json={"cpu_cores": 1, "memory_mb": 512, "gpu_count": 0},
        )
        # No durable operation with this id in a terminal state -> stays active.
        swept = resource_governance.release_expired_reservations(SessionLocal())
        self.assertNotIn(str(op), swept)
        # Simulate the operation having completed before the sweep ran.
        from app.models.operation import DurableOperation

        db = SessionLocal()
        try:
            operation = db.get(DurableOperation, op)
            operation.state = "completed"
            operation.stage = "completed"
            db.commit()
        finally:
            db.close()
        swept = resource_governance.release_expired_reservations(SessionLocal())
        self.assertIn(str(op), swept)
        db = SessionLocal()
        try:
            row = db.query(ResourceReservation).filter(ResourceReservation.operation_id == op).first()
            self.assertEqual("expired", row.state)
            self.assertEqual("expired", row.release_reason)
            db.query(DurableOperation).filter(DurableOperation.id == op).delete(synchronize_session=False)
            db.query(ResourceReservation).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

    def test_09_duplicate_operation_reservation_is_rejected(self):
        op = uuid.uuid4()
        ensure_operation(op, self.project.id)
        cleanup = SessionLocal()
        try:
            cleanup.query(ResourceReservation).delete(synchronize_session=False)
            cleanup.commit()
        finally:
            cleanup.close()
        reserve(
            SessionLocal(),
            project_id=self.project.id,
            cluster_id=self.cluster.id,
            operation_id=op,
            reserved_json={"cpu_cores": 1, "memory_mb": 512, "gpu_count": 0},
        )
        db = SessionLocal()
        try:
            with self.assertRaises(Exception):
                reserve(db, project_id=self.project.id, cluster_id=self.cluster.id,
                        operation_id=op, reserved_json={"cpu_cores": 1, "memory_mb": 512, "gpu_count": 0})
            db.rollback()
            db.query(ResourceReservation).filter(ResourceReservation.operation_id == op).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


class TestQuotaPolicyAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = ensure_user("w16quota-admin", "admin")
        cls.project = ensure_project("w16quota-project", cls.admin.id)
        cls.h = cls._login("w16quota-admin")

    @staticmethod
    def _login(username: str):
        r = client.post("/api/auth/login", data={"username": username, "password": "w14password"})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    def test_10_quota_crud_with_revision_and_audit(self):
        created = client.post(
            "/api/cluster-governance/quota-policies",
            json={"scope": "project", "scope_id": str(self.project.id), "quota_json": {"cpu_cores": 8, "memory_mb": 16384}},
            headers=self.h,
        )
        self.assertEqual(201, created.status_code, created.text)
        quota_id = created.json()["id"]
        self.assertEqual(1, created.json()["revision"])
        patched = client.patch(
            f"/api/cluster-governance/quota-policies/{quota_id}",
            json={"quota_json": {"cpu_cores": 16, "memory_mb": 32768}},
            headers=self.h,
        )
        self.assertEqual(200, patched.status_code)
        self.assertEqual(2, patched.json()["revision"])
        self.assertEqual(16, patched.json()["quota_json"]["cpu_cores"])
        db = SessionLocal()
        try:
            event = (
                db.query(AuditEvent)
                .filter(AuditEvent.action == "governance.quota.update", AuditEvent.result == "success")
                .order_by(AuditEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(event)
        finally:
            db.close()

    def test_11_quota_rejects_unknown_and_negative_keys(self):
        for bad in ({"gpu_tpu": 1}, {"cpu_cores": -2}, {"cpu_cores": "many"}):
            r = client.post(
                "/api/cluster-governance/quota-policies",
                json={"scope": "project", "scope_id": str(self.project.id), "quota_json": bad},
                headers=self.h,
            )
            self.assertEqual(422, r.status_code, bad)


if __name__ == "__main__":
    unittest.main()
