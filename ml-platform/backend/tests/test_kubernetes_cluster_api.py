"""Week 13 Kubernetes cluster API contract tests (project isolation, state machine, audit)."""

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.access import AuditEvent
from app.models.cloud_resources import (
    KubernetesCluster,
    KubernetesCredentialRef,
    KubernetesNamespace,
    KubernetesResourceGroup,
)
from app.models.project import Project
from app.models.user import User
from app.api.auth import pwd_context
from app.services import kubernetes_cluster as cluster_service
from app.services.kubernetes_client import FakeKubernetesClient

Base.metadata.create_all(bind=engine)
client = TestClient(app)

CLUSTER_URL = "https://127.0.0.1:6443"
SECRET_REF = "env:W13_TEST_TOKEN"


def _ensure_user(username: str, role: str) -> User:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(username=username, password_hash=pwd_context.hash("w13password"), role=role)
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    finally:
        db.close()


def _ensure_project(name: str, owner_id) -> Project:
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.name == name).first()
        if project is None:
            project = Project(name=name, description="week13 test", owner_id=owner_id)
            db.add(project)
            db.commit()
            db.refresh(project)
        return project
    finally:
        db.close()


def _login(username: str, password: str):
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestKubernetesClusterAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_allowlist = settings.kubernetes_endpoint_allowlist
        cls._old_insecure = settings.kubernetes_allow_insecure_endpoints
        settings.kubernetes_endpoint_allowlist = ["127.0.0.1", "*.internal.example.com"]
        settings.kubernetes_allow_insecure_endpoints = True
        os_token = __import__("os").environ
        os_token.setdefault("W13_TEST_TOKEN", "test-token-material")
        cls.admin = _ensure_user("w13admin", "admin")
        cls.other = _ensure_user("w13outsider", "engineer")
        cls.project_a = _ensure_project("w13-project-a", cls.admin.id)
        cls.project_b = _ensure_project("w13-project-b", cls.other.id)
        # Make reruns idempotent: clear rows created by earlier runs of this module.
        db = SessionLocal()
        try:
            project_ids = [cls.project_a.id, cls.project_b.id]
            cluster_ids = [
                row.id
                for row in db.query(KubernetesCluster.id)
                .filter(KubernetesCluster.project_id.in_(project_ids))
                .all()
            ]
            if cluster_ids:
                db.query(KubernetesResourceGroup).filter(KubernetesResourceGroup.cluster_id.in_(cluster_ids)).delete(synchronize_session=False)
                db.query(KubernetesNamespace).filter(KubernetesNamespace.cluster_id.in_(cluster_ids)).delete(synchronize_session=False)
                db.query(KubernetesCredentialRef).filter(KubernetesCredentialRef.cluster_id.in_(cluster_ids)).delete(synchronize_session=False)
                db.query(KubernetesCluster).filter(KubernetesCluster.id.in_(cluster_ids)).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
        cls.h = _login("w13admin", "w13password")
        cls.other_h = _login("w13outsider", "w13password")
        cls.fake = FakeKubernetesClient(kubernetes_version="v1.30.0")
        cluster_service.client_factory = lambda cluster, ref: cls.fake
        cls.cluster_id = None
        cls.other_cluster_id = None

    @classmethod
    def tearDownClass(cls):
        settings.kubernetes_endpoint_allowlist = cls._old_allowlist
        settings.kubernetes_allow_insecure_endpoints = cls._old_insecure
        cluster_service.client_factory = None

    def _create_cluster(self, name: str, project_id, headers=None):
        return client.post(
            "/api/kubernetes/clusters",
            json={
                "project_id": str(project_id),
                "name": name,
                "display_name": f"cluster {name}",
                "api_server_url": CLUSTER_URL,
                "secret_ref": SECRET_REF,
                "provider": "kind",
            },
            headers=headers or self.h,
        )

    def test_01_create_cluster_registers_credential_reference_only(self):
        r = self._create_cluster("w13-primary", self.project_a.id)
        self.assertEqual(201, r.status_code, r.text)
        data = r.json()
        self.assertEqual("pending", data["status"])
        self.assertEqual(CLUSTER_URL, data["api_server_url"])
        self.assertEqual(SECRET_REF, data["secret_ref"])
        self.assertIsNotNone(data["stale"])
        type(self).cluster_id = uuid.UUID(data["id"])
        db = SessionLocal()
        try:
            ref = (
                db.query(KubernetesCredentialRef)
                .filter(KubernetesCredentialRef.cluster_id == uuid.UUID(data["id"]))
                .first()
            )
            self.assertIsNotNone(ref)
            self.assertEqual(SECRET_REF, ref.secret_ref)
        finally:
            db.close()

    def test_02_duplicate_name_conflicts(self):
        r = self._create_cluster("w13-primary", self.project_a.id)
        self.assertEqual(409, r.status_code)
        self.assertEqual("CLUSTER_NAME_EXISTS", r.json()["detail"]["code"])

    def test_03_http_endpoint_requires_double_switch(self):
        settings.kubernetes_allow_insecure_endpoints = False
        try:
            r = client.post(
                "/api/kubernetes/clusters",
                json={
                    "project_id": str(self.project_a.id),
                    "name": "w13-http",
                    "api_server_url": "http://127.0.0.1:6443",
                    "secret_ref": SECRET_REF,
                },
                headers=self.h,
            )
            self.assertEqual(422, r.status_code)
            self.assertEqual("KUBERNETES_ENDPOINT_INVALID", r.json()["detail"]["code"])
        finally:
            settings.kubernetes_allow_insecure_endpoints = True

    def test_04_host_outside_allowlist_denied(self):
        r = client.post(
            "/api/kubernetes/clusters",
            json={
                "project_id": str(self.project_a.id),
                "name": "w13-elsewhere",
                "api_server_url": "https://10.99.99.99:6443",
                "secret_ref": SECRET_REF,
            },
            headers=self.h,
        )
        self.assertEqual(422, r.status_code)
        self.assertEqual("KUBERNETES_ENDPOINT_FORBIDDEN", r.json()["detail"]["code"])

    def test_05_raw_token_secret_ref_rejected(self):
        r = client.post(
            "/api/kubernetes/clusters",
            json={
                "project_id": str(self.project_a.id),
                "name": "w13-rawtoken",
                "api_server_url": CLUSTER_URL,
                "secret_ref": "Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6InJlZCJ9",
            },
            headers=self.h,
        )
        self.assertEqual(422, r.status_code)
        self.assertEqual("KUBERNETES_CREDENTIAL_INVALID", r.json()["detail"]["code"])

    def test_06_list_is_project_scoped(self):
        r = client.get("/api/kubernetes/clusters", headers=self.h)
        self.assertEqual(200, r.status_code)
        names = [item["name"] for item in r.json()["items"]]
        self.assertIn("w13-primary", names)
        outsider_create = self._create_cluster("w13-outsider-cluster", self.project_b.id, headers=self.other_h)
        self.assertEqual(201, outsider_create.status_code)
        type(self).other_cluster_id = uuid.UUID(outsider_create.json()["id"])
        r = client.get("/api/kubernetes/clusters", headers=self.h)
        names = [item["name"] for item in r.json()["items"]]
        self.assertNotIn("w13-outsider-cluster", names)

    def test_07_cross_project_access_is_hidden_404(self):
        r = client.get(f"/api/kubernetes/clusters/{self.other_cluster_id}", headers=self.h)
        self.assertEqual(404, r.status_code)
        r = client.post(f"/api/kubernetes/clusters/{self.other_cluster_id}/connectivity-check", headers=self.h)
        self.assertEqual(404, r.status_code)

    def test_08_connectivity_check_success_activates(self):
        r = client.post(f"/api/kubernetes/clusters/{self.cluster_id}/connectivity-check", headers=self.h)
        self.assertEqual(200, r.status_code, r.text)
        data = r.json()
        self.assertEqual("ok", data["check_status"])
        self.assertEqual("v1.30.0", data["kubernetes_version"])
        db = SessionLocal()
        try:
            cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == self.cluster_id).first()
            self.assertEqual("active", cluster.status)
            self.assertEqual("v1.30.0", cluster.kubernetes_version)
            event = (
                db.query(AuditEvent)
                .filter(
                    AuditEvent.action == "kubernetes.cluster.create",
                    AuditEvent.result == "success",
                )
                .order_by(AuditEvent.id.desc())
                .first()
            )
            self.assertIsNotNone(event)
        finally:
            db.close()

    def test_09_connectivity_check_failure_never_touches_registration(self):
        self.fake.fail_code = "KUBERNETES_TIMEOUT"
        try:
            r = client.post(f"/api/kubernetes/clusters/{self.cluster_id}/connectivity-check", headers=self.h)
            self.assertEqual(200, r.status_code)
            data = r.json()
            self.assertEqual("failed", data["check_status"])
            self.assertEqual("KUBERNETES_TIMEOUT", data["error_code"])
            db = SessionLocal()
            try:
                cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == self.cluster_id).first()
                self.assertEqual("connectivity_failed", cluster.status)
                ref = (
                    db.query(KubernetesCredentialRef)
                    .filter(KubernetesCredentialRef.cluster_id == cluster.id)
                    .first()
                )
                self.assertEqual(SECRET_REF, ref.secret_ref)
                self.assertEqual(CLUSTER_URL, cluster.api_server_url)
            finally:
                db.close()
        finally:
            self.fake.fail_code = None

    def test_10_stale_marker_after_threshold(self):
        db = SessionLocal()
        try:
            cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == self.cluster_id).first()
            cluster.last_checked_at = datetime.now(timezone.utc) - timedelta(
                seconds=settings.kubernetes_stale_after_seconds + 60
            )
            db.commit()
        finally:
            db.close()
        r = client.get(f"/api/kubernetes/clusters/{self.cluster_id}", headers=self.h)
        self.assertTrue(r.json()["stale"])

    def test_11_ensure_namespace_idempotent_with_quota_validation(self):
        r = client.put(
            f"/api/kubernetes/clusters/{self.cluster_id}/namespaces/w13-demo",
            json={"quota_json": {"cpu_cores": 2, "memory_mb": 4096}},
            headers=self.h,
        )
        self.assertEqual(200, r.status_code, r.text)
        first = r.json()
        r = client.put(
            f"/api/kubernetes/clusters/{self.cluster_id}/namespaces/w13-demo",
            json={"quota_json": {"cpu_cores": 2, "memory_mb": 4096}},
            headers=self.h,
        )
        self.assertEqual(200, r.status_code)
        self.assertEqual(first["id"], r.json()["id"])
        db = SessionLocal()
        try:
            rows = (
                db.query(KubernetesNamespace)
                .filter(KubernetesNamespace.cluster_id == self.cluster_id, KubernetesNamespace.name == "w13-demo")
                .all()
            )
            self.assertEqual(1, len(rows))
        finally:
            db.close()
        bad_name = client.put(
            f"/api/kubernetes/clusters/{self.cluster_id}/namespaces/Bad_Name",
            json={},
            headers=self.h,
        )
        self.assertEqual(422, bad_name.status_code)
        self.assertEqual("KUBERNETES_NAMESPACE_INVALID", bad_name.json()["detail"]["code"])
        bad_quota = client.put(
            f"/api/kubernetes/clusters/{self.cluster_id}/namespaces/w13-demo",
            json={"quota_json": {"hostpath_gb": 5}},
            headers=self.h,
        )
        self.assertEqual(422, bad_quota.status_code)
        self.assertEqual("KUBERNETES_QUOTA_INVALID", bad_quota.json()["detail"]["code"])

    def test_12_nodes_and_namespaces_listing(self):
        nodes = client.get(f"/api/kubernetes/clusters/{self.cluster_id}/nodes", headers=self.h)
        self.assertEqual(200, nodes.status_code)
        self.assertEqual("kind-control-plane", nodes.json()["items"][0]["hostname"])
        namespaces = client.get(f"/api/kubernetes/clusters/{self.cluster_id}/namespaces", headers=self.h)
        self.assertEqual(200, namespaces.status_code)
        self.assertIn("default", namespaces.json()["items"])

    def test_13_request_id_echoed(self):
        r = client.get(
            f"/api/kubernetes/clusters/{self.cluster_id}",
            headers={**self.h, "X-Request-ID": "w13-req-echo"},
        )
        self.assertTrue(r.headers.get("X-Request-ID"))

    def test_14_soft_delete_hides_cluster(self):
        created = self._create_cluster("w13-doomed", self.project_a.id)
        cluster_id = uuid.UUID(created.json()["id"])
        r = client.delete(f"/api/kubernetes/clusters/{cluster_id}", headers=self.h)
        self.assertEqual(204, r.status_code)
        r = client.get(f"/api/kubernetes/clusters/{cluster_id}", headers=self.h)
        self.assertEqual(404, r.status_code)
        db = SessionLocal()
        try:
            cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == cluster_id).first()
            self.assertIsNotNone(cluster)
            self.assertEqual("disabled", cluster.status)
            self.assertIsNotNone(cluster.archived_at)
        finally:
            db.close()

    def test_15_resource_groups_validated_and_unique(self):
        r = client.post(
            "/api/kubernetes/resource-groups",
            json={
                "cluster_id": str(self.cluster_id),
                "name": "w13-rg",
                "quota_json": {"cpu_cores": 4},
            },
            headers=self.h,
        )
        self.assertEqual(201, r.status_code, r.text)
        self.assertEqual("default", r.json()["scheduling_policy_json"]["policy_type"])
        r = client.post(
            "/api/kubernetes/resource-groups",
            json={"cluster_id": str(self.cluster_id), "name": "w13-rg"},
            headers=self.h,
        )
        self.assertEqual(409, r.status_code)
        r = client.post(
            "/api/kubernetes/resource-groups",
            json={
                "cluster_id": str(self.cluster_id),
                "name": "w13-rg-bad",
                "scheduling_policy_json": {"policy_type": "gpu-exotic"},
            },
            headers=self.h,
        )
        self.assertEqual(422, r.status_code)


if __name__ == "__main__":
    unittest.main()
