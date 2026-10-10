"""Week 16 usage-snapshot contract tests: Summary API parsing, cardinality
truncation, stale-on-failure semantics, GPU unavailability and expiry."""

import sys
import unittest
import uuid
from datetime import timedelta

sys.path.insert(0, ".")

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.resource_governance import ResourceUsageSnapshot  # noqa: E402
from app.services.kubernetes_client import KubernetesClientError  # noqa: E402
from app.services import resource_governance  # noqa: E402
from tests.utils_week14 import ensure_active_cluster, ensure_project, ensure_user  # noqa: E402
from tests.utils_week16 import now_utc  # noqa: E402

Base.metadata.create_all(bind=engine)

FAKE_SUMMARY = {
    "node": {
        "nodeName": "kind-control-plane",
        "cpu": {"usageNanoCores": 250_000_000},
        "memory": {"workingSetBytes": 2 * 1024**3},
    },
    "pods": [
        {
            "podRef": {"name": "lr-notebook-a-1", "namespace": "w14-demo"},
            "cpu": {"usageNanoCores": 80_000_000},
            "memory": {"workingSetBytes": 512 * 1024**2},
        },
        {
            "podRef": {"name": "lr-job-b-1", "namespace": "w14-demo"},
            "cpu": {"usageNanoCores": 20_000_000},
            "memory": {"workingSetBytes": 128 * 1024**2},
        },
    ],
}


class FakeSummaryClient:
    def __init__(self, nodes, summary=None, fail=False):
        self.nodes = nodes
        self.summary = summary or FAKE_SUMMARY
        self.fail = fail

    def list_nodes(self):
        if self.fail:
            raise KubernetesClientError("KUBERNETES_CONNECTIVITY_FAILED", "cluster unreachable")
        return self.nodes

    def node_summary(self, node_name: str):
        if self.fail:
            raise KubernetesClientError("KUBERNETES_CONNECTIVITY_FAILED", "cluster unreachable")
        return self.summary


class TestClusterObservability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = ensure_user("w16obs-admin", "admin")
        cls.project = ensure_project("w16obs-project", cls.admin.id)
        cls.cluster = ensure_active_cluster("w16obs-cluster", cls.project.id, cls.admin.id)

    def tearDown(self):
        db = SessionLocal()
        try:
            db.query(ResourceUsageSnapshot).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

    def _nodes(self, gpu="0"):
        return [
            {
                "hostname": "kind-control-plane",
                "arch": "amd64",
                "cpu_cores": "16",
                "memory": "32Gi",
                "gpu": gpu,
                "labels": {},
            }
        ]

    def test_04_summary_parsed_into_node_pod_gpu_scopes(self):
        result = resource_governance.collect_usage(
            SessionLocal(), self.cluster, None, settings, client=FakeSummaryClient(self._nodes(gpu="4"))
        )
        self.assertEqual("collected", result["status"])
        self.assertFalse(result["truncated"])
        db = SessionLocal()
        try:
            scopes = {
                row.scope: row
                for row in db.query(ResourceUsageSnapshot)
                .filter(ResourceUsageSnapshot.cluster_id == self.cluster.id)
                .all()
            }
            self.assertIn("node", scopes)
            self.assertEqual("kind-control-plane", scopes["node"].subject)
            self.assertIn("cpu_cores", scopes["node"].metrics_json)
            self.assertIn("pod", scopes)
            self.assertIn("gpu", scopes)
            self.assertEqual("4", str(scopes["gpu"].metrics_json["allocatable"]))
            self.assertEqual("unavailable", scopes["gpu"].metrics_json.get("utilization"))
        finally:
            db.close()

    def test_05_cardinality_truncated_at_100_per_scope(self):
        huge = {"node": FAKE_SUMMARY["node"], "pods": []}
        for index in range(150):
            huge["pods"].append(
                {
                    "podRef": {"name": f"pod-{index}", "namespace": "w14-demo"},
                    "cpu": {"usageNanoCores": 1_000_000},
                    "memory": {"workingSetBytes": 1024**2},
                }
            )
        result = resource_governance.collect_usage(
            SessionLocal(), self.cluster, None, settings, client=FakeSummaryClient(self._nodes(), huge)
        )
        self.assertTrue(result["truncated"])
        db = SessionLocal()
        try:
            pod_rows = (
                db.query(ResourceUsageSnapshot)
                .filter(ResourceUsageSnapshot.cluster_id == self.cluster.id, ResourceUsageSnapshot.scope == "pod")
                .count()
            )
            self.assertEqual(100, pod_rows)
        finally:
            db.close()

    def test_06_collection_failure_marks_stale_and_does_not_raise(self):
        db = SessionLocal()
        try:
            db.add(
                ResourceUsageSnapshot(
                    cluster_id=self.cluster.id,
                    scope="node",
                    subject="kind-control-plane",
                    metrics_json={"cpu_cores": 1},
                    collected_at=now_utc(),
                )
            )
            db.commit()
        finally:
            db.close()
        result = resource_governance.collect_usage(
            SessionLocal(), self.cluster, None, settings, client=FakeSummaryClient(self._nodes(), fail=True)
        )
        self.assertEqual("stale", result["status"])
        self.assertTrue(
            resource_governance.usage_is_stale(SessionLocal(), self.cluster, settings)
        )

    def test_07_fresh_collection_is_not_stale(self):
        resource_governance.collect_usage(
            SessionLocal(), self.cluster, None, settings, client=FakeSummaryClient(self._nodes())
        )
        self.assertFalse(resource_governance.usage_is_stale(SessionLocal(), self.cluster, settings))

    def test_08_snapshot_expiry_cleanup(self):
        db = SessionLocal()
        try:
            db.add(
                ResourceUsageSnapshot(
                    cluster_id=self.cluster.id,
                    scope="node",
                    subject="old-node",
                    metrics_json={},
                    collected_at=now_utc() - timedelta(seconds=settings.governance_snapshot_retention_seconds + 3600),
                )
            )
            db.add(
                ResourceUsageSnapshot(
                    cluster_id=self.cluster.id,
                    scope="node",
                    subject="new-node",
                    metrics_json={},
                    collected_at=now_utc(),
                )
            )
            db.commit()
        finally:
            db.close()
        pruned = resource_governance.prune_snapshots(SessionLocal())
        self.assertGreaterEqual(pruned, 1)
        db = SessionLocal()
        try:
            remaining = [
                row.subject
                for row in db.query(ResourceUsageSnapshot)
                .filter(ResourceUsageSnapshot.cluster_id == self.cluster.id)
                .all()
            ]
            self.assertNotIn("old-node", remaining)
            self.assertIn("new-node", remaining)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
