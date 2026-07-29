import json
import tempfile
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
