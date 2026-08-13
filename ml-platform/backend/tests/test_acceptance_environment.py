import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.main  # noqa: F401 (register the complete production metadata)
from app.database import Base
from app.models.notifications import NotificationEndpoint
from app.models.project import Project
from app.models.user import User
from app.services.notification_crypto import decrypt_config
from tools.acceptance_environment import (
    cleanup_web_security_context,
    collect_environment,
    collect_runtime_image_provenance,
    create_web_security_context,
)


class AcceptanceWebContextTests(unittest.TestCase):
    def test_context_uses_real_project_members_and_removes_all_seeded_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = create_engine(f"sqlite:///{(root / 'acceptance.db').as_posix()}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            key = SecretStr(Fernet.generate_key().decode("ascii"))
            context_path = root / "web-context.json"

            try:
                context = create_web_security_context(
                    context_path,
                    session_factory=sessions,
                    notification_master_key=key,
                    token_factory=lambda claims: f"token-{claims['sub']}",
                )

                self.assertEqual(context["schema_version"], 1)
                self.assertEqual(set(context["tokens"]), {"owner", "editor", "operator", "viewer", "outsider"})
                self.assertEqual(json.loads(context_path.read_text(encoding="utf-8")), context)

                with sessions() as db:
                    project = db.get(Project, UUID(context["project_id"]))
                    self.assertIsNotNone(project)
                    endpoint = db.get(NotificationEndpoint, UUID(context["endpoint_id"]))
                    self.assertIsNotNone(endpoint)
                    self.assertEqual(
                        decrypt_config(endpoint.encrypted_config, key),
                        {"recipient_user_ids": [context["user_ids"]["owner"]]},
                    )

                cleanup_web_security_context(context_path, session_factory=sessions)

                with sessions() as db:
                    self.assertIsNone(db.get(Project, UUID(context["project_id"])))
                    self.assertEqual(db.query(User).count(), 0)
                self.assertFalse(context_path.exists())
            finally:
                engine.dispose()


class RuntimeImageProvenanceTests(unittest.TestCase):
    _COMMIT = "a" * 40

    def _service_images(self) -> dict[str, dict[str, str]]:
        images = {
            "backend": {
                "reference": "ml-platform-backend:test",
                "image_id": "sha256:" + "1" * 64,
                "revision": self._COMMIT,
            },
            "worker": {
                "reference": "ml-platform-worker:test",
                "image_id": "sha256:" + "2" * 64,
                "revision": self._COMMIT,
            },
            "inference": {
                "reference": "ml-platform-inference:test",
                "image_id": "sha256:" + "3" * 64,
                "revision": self._COMMIT,
            },
            "tensorboard": {
                "reference": "ml-platform-tensorboard:test",
                "image_id": "sha256:" + "4" * 64,
                "revision": self._COMMIT,
            },
        }
        return {
            "migrate": images["backend"],
            "backend": images["backend"],
            "worker": images["worker"],
            "scheduler": images["worker"],
            "inference-runtime": images["inference"],
            "tensorboard-gateway": images["tensorboard"],
        }

    def test_collect_runtime_image_provenance_binds_all_required_services(self):
        service_images = self._service_images()

        provenance = collect_runtime_image_provenance(
            self._COMMIT,
            inspect_service=service_images.__getitem__,
        )

        self.assertEqual(provenance["schema_version"], 1)
        self.assertEqual(provenance["source_commit"], self._COMMIT)
        self.assertEqual(
            provenance["components"],
            [
                {
                    "component": "backend",
                    "services": ["migrate", "backend"],
                    **service_images["backend"],
                },
                {
                    "component": "worker",
                    "services": ["worker", "scheduler"],
                    **service_images["worker"],
                },
                {
                    "component": "inference",
                    "services": ["inference-runtime"],
                    **service_images["inference-runtime"],
                },
                {
                    "component": "tensorboard",
                    "services": ["tensorboard-gateway"],
                    **service_images["tensorboard-gateway"],
                },
            ],
        )

    def test_collect_runtime_image_provenance_rejects_service_image_drift(self):
        service_images = self._service_images()
        service_images["scheduler"] = {
            **service_images["scheduler"],
            "image_id": "sha256:" + "f" * 64,
        }

        with self.assertRaisesRegex(ValueError, "runtime image service metadata mismatch"):
            collect_runtime_image_provenance(
                self._COMMIT,
                inspect_service=service_images.__getitem__,
            )

    @patch("tools.acceptance_environment._command_output", return_value="unavailable")
    def test_collect_environment_uses_explicit_source_commit_inside_runtime_container(self, _output):
        environment = collect_environment(
            {"ACCEPTANCE_SOURCE_COMMIT": self._COMMIT},
        )

        self.assertEqual(environment["git"], {"commit": self._COMMIT})


if __name__ == "__main__":
    unittest.main()
