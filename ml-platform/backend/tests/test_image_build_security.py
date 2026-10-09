"""Week 15 image build decision-gate security tests: 501 without approval,
hardened builder manifest, credential references only, redacted logs."""

import sys
import unittest
import uuid

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import kubernetes_cluster as cluster_service  # noqa: E402
from app.services.image_build_service import build_builder_manifest, redact_build_log  # noqa: E402
from app.services.kubernetes_client import FakeKubernetesClient  # noqa: E402
from tests.utils_week14 import ensure_project, ensure_user  # noqa: E402
from tests.utils_week15 import cleanup_week15_rows  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(app)


class TestImageBuildSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = ensure_user("w15build-admin", "admin")
        cls.project = ensure_project("w15build-project", cls.admin.id)
        cleanup_week15_rows()
        cls.fake = FakeKubernetesClient()
        cluster_service.client_factory = lambda cluster, ref: cls.fake
        cls.h = cls._login("w15build-admin")
        cls._previous_approved = settings.image_build_approved
        cls._previous_builder = settings.image_build_builder_image

    @classmethod
    def tearDownClass(cls):
        cluster_service.client_factory = None
        settings.image_build_approved = cls._previous_approved
        settings.image_build_builder_image = cls._previous_builder

    @staticmethod
    def _login(username: str):
        r = client.post("/api/auth/login", data={"username": username, "password": "w14password"})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    def _build_payload(self):
        return {
            "project_id": str(self.project.id),
            "source_artifact_id": str(uuid.uuid4()),
            "builder_image": "registry.local/w15/kaniko@sha256:" + "d" * 64,
            "destination": "registry.local/w15/built@sha256:" + "e" * 64,
            "registry_credential_ref": "env:W15_REGISTRY_TOKEN",
        }

    def test_04_build_endpoint_returns_501_without_approval(self):
        settings.image_build_approved = False
        r = client.post("/api/images/builds", json=self._build_payload(), headers=self.h)
        self.assertEqual(501, r.status_code)
        self.assertEqual("IMAGE_BUILD_NOT_APPROVED", r.json()["detail"]["code"])

    def test_05_builder_manifest_is_security_hardened(self):
        manifest = build_builder_manifest(
            build_id=uuid.uuid4(),
            builder_image="registry.local/w15/kaniko@sha256:" + "d" * 64,
            destination="registry.local/w15/built@sha256:" + "e" * 64,
            registry_credential_ref="env:W15_REGISTRY_TOKEN",
            namespace="w15-notebooks",
            labels={"app.kubernetes.io/managed-by": "linkraft"},
        )
        pod_spec = manifest["spec"]["template"]["spec"]
        container = pod_spec["containers"][0]
        self.assertNotIn("hostNetwork", pod_spec)
        self.assertNotIn("hostPID", pod_spec)
        self.assertNotIn("hostIPC", pod_spec)
        self.assertNotIn("volumes", pod_spec)
        self.assertNotIn("securityContext", container)
        self.assertNotIn("ports", container)
        self.assertFalse(pod_spec["automountServiceAccountToken"])
        args = " ".join(container.get("args", []))
        self.assertNotIn("--docker", args)
        # Credential travels as a env reference name only, never material.
        self.assertIn("env:W15_REGISTRY_TOKEN", str(container.get("env", [])))
        self.assertNotIn("bearer", args.lower())

    def test_06_build_log_is_redacted(self):
        log = "pushing registry.local/w15/built Bearer supersecrettokenvalue12345 done"
        redacted = redact_build_log(log)
        self.assertNotIn("supersecrettokenvalue12345", redacted)
        self.assertIn("[redacted]", redacted)

    def test_07_approved_path_records_build_and_output_image(self):
        settings.image_build_approved = True
        settings.image_build_builder_image = "registry.local/w15/kaniko@sha256:" + "d" * 64
        payload = self._build_payload()
        r = client.post("/api/images/builds", json=payload, headers=self.h)
        self.assertEqual(201, r.status_code, r.text)
        body = r.json()
        self.assertIn(body["status"], ("queued", "running", "succeeded"))
        # The output digest is recorded as an immutable catalog entry.
        db = SessionLocal()
        try:
            from app.models.developer_resources import ContainerImage, ImageBuild

            build = db.get(ImageBuild, uuid.UUID(body["id"]))
            self.assertIsNotNone(build)
            self.assertIsNotNone(build.output_image_id)
            output = db.get(ContainerImage, build.output_image_id)
            self.assertIsNotNone(output)
            self.assertEqual(payload["destination"].split("@")[1], output.digest)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
