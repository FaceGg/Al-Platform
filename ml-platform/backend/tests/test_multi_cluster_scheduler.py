"""Week 16 multi-cluster router contract tests: deterministic, fail-closed,
single-cluster degradation and per-cluster exclusion reasons."""

import sys
import unittest
import uuid
from datetime import timedelta

sys.path.insert(0, ".")

from sqlalchemy import create_engine, inspect  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.services.cluster_scheduler import route  # noqa: E402
from app.services.kubernetes_executor import KubeJobError  # noqa: E402
from tests.utils_week14 import ensure_active_cluster, ensure_project, ensure_user  # noqa: E402
from tests.utils_week16 import ensure_routing_policy, now_utc  # noqa: E402

Base.metadata.create_all(bind=engine)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMP_ROOT = PROJECT_ROOT / "temp_test"
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

WEEK16_TABLES = {
    "cluster_routing_policies",
    "storage_bindings",
    "resource_quota_policies",
    "resource_reservations",
    "resource_usage_snapshots",
}


class TestResourceGovernanceSchema(unittest.TestCase):
    def test_01_upgrade_head_creates_week16_tables_and_check_passes(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            database_url = f"sqlite:///{Path(tmp).as_posix()}/database.db"
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
                self.assertTrue(WEEK16_TABLES.issubset(set(inspector.get_table_names())))
                policy_uniques = {u["name"] for u in inspector.get_unique_constraints("cluster_routing_policies")}
                self.assertIn("uq_cluster_routing_policies_project_priority", policy_uniques)
                reservation_uniques = {u["name"] for u in inspector.get_unique_constraints("resource_reservations")}
                self.assertIn("uq_resource_reservations_operation", reservation_uniques)
                quota_uniques = {u["name"] for u in inspector.get_unique_constraints("resource_quota_policies")}
                self.assertIn("uq_resource_quota_policies_scope", quota_uniques)
            finally:
                db_engine.dispose()

    def test_02_downgrade_drops_week16_tables_and_keeps_unrelated(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as tmp:
            database_url = f"sqlite:///{Path(tmp).as_posix()}/database.db"
            config = Config(str(ALEMBIC_INI))
            original_url = settings.database_url
            settings.database_url = database_url
            try:
                command.upgrade(config, "head")
                command.downgrade(config, "20261008_66")
            finally:
                settings.database_url = original_url
            db_engine = create_engine(database_url)
            try:
                tables = set(inspect(db_engine).get_table_names())
                self.assertFalse(WEEK16_TABLES & tables)
                self.assertIn("notebook_sessions", tables)
            finally:
                db_engine.dispose()
            settings.database_url = database_url
            try:
                command.upgrade(config, "head")
                command.check(config)
            finally:
                settings.database_url = original_url


class TestMultiClusterRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = ensure_user("w16rt-admin", "admin")
        cls.project = ensure_project("w16rt-project", cls.admin.id)
        cls.cluster_a = ensure_active_cluster("w16rt-a", cls.project.id, cls.admin.id)
        cls.cluster_b = ensure_active_cluster("w16rt-b", cls.project.id, cls.admin.id)
        # Distinct cluster capability/region profiles via capabilities JSON.
        from app.models.cloud_resources import KubernetesCluster

        db = SessionLocal()
        try:
            a = db.get(KubernetesCluster, cls.cluster_a.id)
            a.capabilities = {"gpu": 0, "region": "cn-north", "storage_class": "standard"}
            b = db.get(KubernetesCluster, cls.cluster_b.id)
            b.capabilities = {"gpu": 4, "region": "cn-east", "storage_class": "fast"}
            db.commit()
        finally:
            db.close()

    def _fresh_clusters(self, **overrides):
        from app.models.cloud_resources import KubernetesCluster

        db = SessionLocal()
        try:
            for name, overrides_one in (("w16rt-a", overrides.get("a", {})), ("w16rt-b", overrides.get("b", {}))):
                row = db.query(KubernetesCluster).filter(KubernetesCluster.name == name).first()
                for key, value in overrides_one.items():
                    setattr(row, key, value)
                if "last_checked_at" not in overrides_one:
                    row.last_checked_at = now_utc()
                if "status" not in overrides_one:
                    row.status = "active"
            db.commit()
        finally:
            db.close()

    def test_03_no_policy_multi_cluster_is_fail_closed_deterministic(self):
        # Two eligible clusters, no policy: deterministic pick (lowest id) with
        # an explicit reason — never an arbitrary choice.
        self._fresh_clusters()
        first = route(SessionLocal(), self.project.id, cpu_cores=1)
        second = route(SessionLocal(), self.project.id, cpu_cores=1)
        self.assertEqual(first.selected_cluster_id, second.selected_cluster_id)
        self.assertIn(first.reason, ("cost_min", "capability_match", "region_match"))

    def test_04_single_cluster_degrades_with_default_reason(self):
        from app.models.cloud_resources import KubernetesCluster

        self._fresh_clusters(b={"status": "disabled"})
        try:
            decision = route(SessionLocal(), self.project.id, cpu_cores=1)
            self.assertEqual(str(self.cluster_a.id), str(decision.selected_cluster_id))
            self.assertEqual("default_single_cluster", decision.reason)
        finally:
            db = SessionLocal()
            try:
                row = db.get(KubernetesCluster, self.cluster_b.id)
                row.status = "active"
                db.commit()
            finally:
                db.close()

    def test_05_stale_and_unhealthy_clusters_are_excluded_with_reason(self):
        self._fresh_clusters(a={"last_checked_at": now_utc() - timedelta(seconds=settings.kubernetes_stale_after_seconds + 300)})
        try:
            decision = route(SessionLocal(), self.project.id, cpu_cores=1)
            a = next(c for c in decision.candidates if c["name"] == "w16rt-a")
            self.assertTrue(a["excluded"])
            self.assertEqual("stale_check", a["reason"])
            self.assertEqual(str(self.cluster_b.id), str(decision.selected_cluster_id))
        finally:
            self._fresh_clusters()

    def test_06_gpu_requirement_excludes_cluster_without_capacity(self):
        self._fresh_clusters()
        decision = route(SessionLocal(), self.project.id, cpu_cores=1, gpu_count=2)
        excluded = {c["name"]: c for c in decision.candidates if c["excluded"]}
        self.assertIn("w16rt-a", excluded)
        self.assertEqual("no_gpu_capacity", excluded["w16rt-a"]["reason"])
        self.assertEqual(str(self.cluster_b.id), str(decision.selected_cluster_id))

    def test_07_region_policy_selects_matching_cluster(self):
        self._fresh_clusters()
        policy = ensure_routing_policy(self.project.id, priority=1, policy_json={"region": "cn-east"})
        try:
            decision = route(SessionLocal(), self.project.id, cpu_cores=1)
            self.assertEqual(str(self.cluster_b.id), str(decision.selected_cluster_id))
            self.assertEqual("region_match", decision.reason)
            self.assertEqual(policy.revision, decision.policy_revision)
        finally:
            db = SessionLocal()
            try:
                db.query(type(policy)).filter(type(policy).id == policy.id).delete(synchronize_session=False)
                db.commit()
            finally:
                db.close()

    def test_08_connectivity_failed_cluster_excluded(self):
        self._fresh_clusters(a={"status": "connectivity_failed"})
        try:
            decision = route(SessionLocal(), self.project.id, cpu_cores=1)
            excluded = {c["name"]: c for c in decision.candidates if c["excluded"]}
            self.assertEqual("cluster_not_active", excluded["w16rt-a"]["reason"])
        finally:
            self._fresh_clusters()

    def test_09_no_eligible_cluster_raises_with_reasons(self):
        self._fresh_clusters(a={"status": "disabled"}, b={"status": "disabled"})
        try:
            with self.assertRaises(KubeJobError) as raised:
                route(SessionLocal(), self.project.id, cpu_cores=1)
            self.assertEqual("NO_ELIGIBLE_CLUSTER", raised.exception.code)
        finally:
            self._fresh_clusters(a={"status": "active"}, b={"status": "active"})

    def test_10_preview_does_not_create_reservations(self):
        from app.models.resource_governance import ResourceReservation

        self._fresh_clusters()
        db = SessionLocal()
        try:
            before = db.query(ResourceReservation).filter(ResourceReservation.state == "active").count()
        finally:
            db.close()
        route(SessionLocal(), self.project.id, cpu_cores=1, preview=True)
        db = SessionLocal()
        try:
            after = db.query(ResourceReservation).filter(ResourceReservation.state == "active").count()
            self.assertEqual(before, after)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
