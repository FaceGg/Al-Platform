"""Week 15 image catalog API contract tests: digest immutability, uniqueness,
scan-status coupling and visibility isolation."""

import sys
import unittest
import uuid

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import kubernetes_cluster as cluster_service  # noqa: E402
from app.services.kubernetes_client import FakeKubernetesClient  # noqa: E402
from tests.utils_week14 import ensure_project, ensure_user  # noqa: E402
from tests.utils_week15 import cleanup_week15_rows, ensure_image  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(app)

DIGEST_A = "sha256:" + "1" * 64
DIGEST_B = "sha256:" + "2" * 64


class TestImageCatalogAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = ensure_user("w15img-admin", "admin")
        cls.other = ensure_user("w15img-outsider", "engineer")
        cls.project = ensure_project("w15img-project", cls.admin.id)
        cls.other_project = ensure_project("w15img-other-project", cls.other.id)
        cleanup_week15_rows()
        cls.fake = FakeKubernetesClient()
        cluster_service.client_factory = lambda cluster, ref: cls.fake
        cls.h = cls._login("w15img-admin")
        cls.other_h = cls._login("w15img-outsider")

    @classmethod
    def tearDownClass(cls):
        cluster_service.client_factory = None

    @staticmethod
    def _login(username: str):
        r = client.post("/api/auth/login", data={"username": username, "password": "w14password"})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    def _register(self, digest=DIGEST_A, repository="w15/catalog", headers=None, visibility="project", scan_status="passed"):
        return client.post(
            "/api/images",
            json={
                "registry": "registry.local",
                "repository": repository,
                "digest": digest,
                "visibility": visibility,
                "scan_status": scan_status,
            },
            headers=headers or self.h,
        )

    def test_04_register_and_unique_digest(self):
        first = self._register()
        self.assertEqual(201, first.status_code, first.text)
        body = first.json()
        self.assertEqual("registry.local", body["registry"])
        self.assertEqual(DIGEST_A, body["digest"])
        self.assertEqual("passed", body["scan_status"])
        duplicate = self._register()
        self.assertEqual(409, duplicate.status_code)
        self.assertEqual("IMAGE_DIGEST_EXISTS", duplicate.json()["detail"]["code"])

    def test_05_digest_is_immutable_on_patch(self):
        created = self._register(repository="w15/immutable")
        image_id = created.json()["id"]
        patched = client.patch(
            f"/api/images/{image_id}",
            json={"digest": DIGEST_B},
            headers=self.h,
        )
        self.assertEqual(422, patched.status_code)
        self.assertEqual("IMAGE_DIGEST_IMMUTABLE", patched.json()["detail"]["code"])
        # scan_status updates are allowed.
        scan = client.patch(f"/api/images/{image_id}", json={"scan_status": "passed"}, headers=self.h)
        self.assertEqual(200, scan.status_code)
        self.assertEqual("passed", scan.json()["scan_status"])

    def test_06_invalid_digest_rejected(self):
        r = self._register(digest="sha256:" + "z" * 64, repository="w15/bad-digest")
        self.assertEqual(422, r.status_code)
        self.assertEqual("IMAGE_DIGEST_INVALID", r.json()["detail"]["code"])

    def test_07_visibility_isolation(self):
        created = self._register(repository="w15/private", visibility="project")
        image_id = created.json()["id"]
        foreign_get = client.get(f"/api/images/{image_id}", headers=self.other_h)
        self.assertEqual(404, foreign_get.status_code)
        foreign_list = client.get("/api/images", headers=self.other_h)
        ids = [item["id"] for item in foreign_list.json()["items"]]
        self.assertNotIn(image_id, ids)
        # Platform-visible images are readable cross-project.
        platform = self._register(repository="w15/platform", visibility="platform")
        platform_list = client.get("/api/images", headers=self.other_h)
        platform_ids = [item["id"] for item in platform_list.json()["items"]]
        self.assertIn(platform.json()["id"], platform_ids)

    def test_08_failed_scan_image_blocks_session_reference(self):
        failed = self._register(repository="w15/blocked", scan_status="failed")
        body = failed.json()
        image_ref_str = f"{body['registry']}/{body['repository']}@{body['digest']}"
        from tests.utils_week14 import ensure_active_cluster
        from tests.utils_week15 import notebook_payload

        cluster = ensure_active_cluster("w15img-cluster", self.project.id, self.admin.id, namespace="w15-notebooks")
        r = client.post(
            "/api/notebooks",
            json=notebook_payload(cluster.id, None, image_ref=image_ref_str),
            headers={**self.h, "Idempotency-Key": f"w15-img-{uuid.uuid4()}"},
        )
        self.assertEqual(422, r.status_code)
        self.assertEqual("NOTEBOOK_IMAGE_SCAN_FAILED", r.json()["detail"]["code"])


if __name__ == "__main__":
    unittest.main()
