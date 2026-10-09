"""Week 15 GPU scheduling contract tests: class resolution, capacity
re-verification, controlled selector/tolerations, per-session cap and the
no-GPU skipped semantics."""

import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.services import gpu_scheduler  # noqa: E402
from app.services.kubernetes_executor import KubeJobError  # noqa: E402
from app.services.kubernetes_client import FakeKubernetesClient  # noqa: E402
from tests.utils_week14 import ensure_active_cluster, ensure_project, ensure_user  # noqa: E402
from tests.utils_week15 import ensure_gpu_class  # noqa: E402

Base.metadata.create_all(bind=engine)


class TestGpuScheduling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = ensure_user("w15gpu-admin", "admin")
        cls.project = ensure_project("w15gpu-project", cls.admin.id)
        cls.cluster = ensure_active_cluster("w15gpu-cluster", cls.project.id, cls.admin.id)

    def setUp(self):
        self.fake = FakeKubernetesClient(
            nodes=[
                {
                    "hostname": "gpu-node-1",
                    "arch": "amd64",
                    "cpu_cores": "16",
                    "memory": "64Gi",
                    "gpu": "4",
                    "labels": {"linkraft.io/gpu-pool": "w15-gpu"},
                }
            ]
        )

    def _recent_class(self, **overrides):
        return ensure_gpu_class(self.cluster.id, **overrides)

    def test_04_missing_class_is_explicit_error(self):
        with self.assertRaises(KubeJobError) as raised:
            gpu_scheduler.resolve_class(SessionLocal(), self.cluster.id, "no-such-class")
        self.assertEqual("GPU_CLASS_UNAVAILABLE", raised.exception.code)

    def test_05_inactive_class_is_unavailable(self):
        gpu_class = self._recent_class(name="w15-inactive", status="disabled")
        with self.assertRaises(KubeJobError) as raised:
            gpu_scheduler.resolve_class(SessionLocal(), self.cluster.id, gpu_class.name)
        self.assertEqual("GPU_CLASS_UNAVAILABLE", raised.exception.code)

    def test_06_stale_snapshot_is_refreshed_before_capacity_check(self):
        gpu_class = self._recent_class()
        db = SessionLocal()
        try:
            stale_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
                seconds=settings.gpu_snapshot_stale_seconds + 120
            )
            gpu_class.snapshotted_at = stale_at
            db.commit()
            resolved = gpu_scheduler.resolve_class(db, self.cluster.id, gpu_class.name)
            refreshed_allocatable = gpu_scheduler.verify_capacity(db, self.fake, resolved, requested=2)
            self.assertEqual(4, refreshed_allocatable)
            self.assertIsNotNone(resolved.snapshotted_at)
            self.assertGreater(resolved.snapshotted_at, stale_at)
        finally:
            db.close()

    def test_07_zero_allocatable_raises_capacity_exceeded(self):
        self.fake.nodes[0]["gpu"] = "0"
        gpu_class = self._recent_class()
        db = SessionLocal()
        try:
            resolved = gpu_scheduler.resolve_class(db, self.cluster.id, gpu_class.name)
            with self.assertRaises(KubeJobError) as raised:
                gpu_scheduler.verify_capacity(db, self.fake, resolved, requested=1)
            self.assertEqual("GPU_CAPACITY_EXCEEDED", raised.exception.code)
        finally:
            db.close()

    def test_08_request_above_allocatable_raises(self):
        gpu_class = self._recent_class(name="w15-uncapped", max_per_session=8)
        db = SessionLocal()
        try:
            resolved = gpu_scheduler.resolve_class(db, self.cluster.id, gpu_class.name)
            with self.assertRaises(KubeJobError) as raised:
                gpu_scheduler.verify_capacity(db, self.fake, resolved, requested=8)
            self.assertEqual("GPU_CAPACITY_EXCEEDED", raised.exception.code)
        finally:
            db.close()

    def test_09_per_session_cap_enforced(self):
        gpu_class = self._recent_class(name="w15-capped", max_per_session=1)
        db = SessionLocal()
        try:
            resolved = gpu_scheduler.resolve_class(db, self.cluster.id, gpu_class.name)
            with self.assertRaises(KubeJobError) as raised:
                gpu_scheduler.verify_capacity(db, self.fake, resolved, requested=2)
            self.assertEqual("GPU_PER_SESSION_LIMIT", raised.exception.code)
        finally:
            db.close()

    def test_10_selector_only_accepts_controlled_keys(self):
        with self.assertRaises(KubeJobError):
            gpu_scheduler.validate_selector({"free-form-key": "value"})
        ok = gpu_scheduler.validate_selector({"linkraft.io/gpu-pool": "w15-gpu"})
        self.assertEqual({"linkraft.io/gpu-pool": "w15-gpu"}, ok)

    def test_11_tolerations_only_accept_controlled_values(self):
        with self.assertRaises(KubeJobError):
            gpu_scheduler.validate_tolerations(
                [{"key": "nvidia.com/gpu", "operator": "Exists", "effect": "Midnight"}]
            )
        ok = gpu_scheduler.validate_tolerations(
            [{"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"}]
        )
        self.assertEqual(1, len(ok))

    def test_12_apply_injects_gpu_resources_and_constraints(self):
        gpu_class = self._recent_class()
        db = SessionLocal()
        try:
            resolved = gpu_scheduler.resolve_class(db, self.cluster.id, gpu_class.name)
            gpu_scheduler.verify_capacity(db, self.fake, resolved, requested=1)
            injection = gpu_scheduler.build_injection(resolved, requested=1)
        finally:
            db.close()
        self.assertEqual({"nvidia.com/gpu": 1}, injection["resources"]["limits"])
        self.assertEqual({"nvidia.com/gpu": 1}, injection["resources"]["requests"])
        self.assertEqual({"linkraft.io/gpu-pool": "w15-gpu"}, injection["node_selector"])
        self.assertEqual(1, len(injection["tolerations"]))

    def test_13_probe_reports_skipped_semantics_without_gpu(self):
        self.fake.nodes[0]["gpu"] = "0"
        probe = gpu_scheduler.probe_gpu_nodes(self.fake)
        self.assertFalse(probe["available"])
        self.assertEqual("skipped", probe["semantics"])
        self.assertTrue(probe["reason"])


if __name__ == "__main__":
    unittest.main()
