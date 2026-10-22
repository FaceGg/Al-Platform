"""LLMProfile gateway registry tests (AutoML Agent plan, Task A1.2).

Contract under test (technical spec v0.9 ch.14/17): system-admin-only CRUD,
write-only API keys (masked reads), SSRF-hardened ``api_url`` validation,
single-default guarantee, platform audit records, env bootstrap of the
built-in default profile, and the migration three-state (upgrade/downgrade).

All credential material (master key, admin/engineer passwords, profile keys)
is generated per run — nothing sensitive lives in source.
"""

import os
import unittest
from unittest import mock
from uuid import uuid4

# The Fernet master key must exist before app config is imported. Randomized
# per run so no credential material ever lives in source.
os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import sqlalchemy as sa  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.llm_profile import LLMProfile  # noqa: E402
from app.models.platform_audit import PlatformAuditEvent  # noqa: E402
from app.models.user import User  # noqa: E402
from tests.auth_test_support import ensure_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(__import__("app.main", fromlist=["app"]).app)

_ADMIN_USER = "agent-admin-" + uuid4().hex[:8]
_ADMIN_PASSWORD = uuid4().hex + uuid4().hex[:4]
_ENGINEER_USER = "agent-engineer-" + uuid4().hex[:8]
_ENGINEER_PASSWORD = uuid4().hex + uuid4().hex[:4]
_LLM_URL = "https://api.example-llm.com/v1/chat/completions"


def _fake_key(suffix: str) -> str:
    return f"sk-test-{suffix}-{uuid4().hex[:12]}"


class TestLLMProfilesAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin(_ADMIN_USER, _ADMIN_PASSWORD)
        # ensure_admin always grants role="admin"; the engineer account needs a
        # non-admin role to exercise the admin gate.
        from app.api.auth import pwd_context

        with SessionLocal() as db:
            if db.query(User).filter(User.username == _ENGINEER_USER).first() is None:
                db.add(
                    User(
                        username=_ENGINEER_USER,
                        password_hash=pwd_context.hash(_ENGINEER_PASSWORD),
                        role="engineer",
                    )
                )
                db.commit()
        cls.h = {"Authorization": "Bearer " + client.post(
            "/api/auth/login",
            data={"username": _ADMIN_USER, "password": _ADMIN_PASSWORD},
        ).json()["access_token"]}
        cls.h_user = {"Authorization": "Bearer " + client.post(
            "/api/auth/login",
            data={"username": _ENGINEER_USER, "password": _ENGINEER_PASSWORD},
        ).json()["access_token"]}
        with SessionLocal() as db:
            settings.llm_master_key = SecretStr(Fernet.generate_key().decode("ascii"))

    def _create(self, name="p1", url=_LLM_URL, api_key=None, headers=None, **extra):
        payload = {
            "name": name,
            "api_url": url,
            "model_id": "glm-4.6",
            "api_key": api_key or _fake_key("create"),
            **extra,
        }
        return client.post(
            "/api/llm-profiles", json=payload, headers=headers or self.h
        )

    def test_create_requires_admin(self):
        response = self._create(name="nope-user", headers=self.h_user)
        self.assertEqual(response.status_code, 403)
        anon = client.post("/api/llm-profiles", json={"name": "x"})
        self.assertIn(anon.status_code, (401, 403))

    def test_create_masks_api_key_and_read_never_returns_plaintext(self):
        secret = _fake_key("mask")
        response = self._create(name="mask-profile", api_key=secret)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["api_key_masked"].startswith("***"))
        self.assertTrue(secret.endswith(body["api_key_masked"][-4:]))
        self.assertNotIn("api_key", body)
        self.assertNotIn(secret, response.text)
        fetched = client.get(f"/api/llm-profiles/{body['id']}", headers=self.h)
        self.assertNotIn(secret, fetched.text)

    def test_api_url_validation_rejects_non_https_and_private_targets(self):
        bad_urls = [
            "http://api.example-llm.com/v1/chat/completions",
            "https://localhost/v1",
            "https://127.0.0.1/v1",
            "https://10.1.2.3/v1",
            "https://192.168.1.1/v1",
            "https://169.254.169.254/latest/meta-data",
            "https://[::1]/v1",
            "https://172.16.0.9/v1",
            "https://192.168.1.1:8123/v1",
        ]
        for index, url in enumerate(bad_urls):
            response = self._create(name=f"bad-url-{index}", url=url)
            self.assertEqual(response.status_code, 422, url)
        ok = self._create(name="ok-url", url="https://llm.internal.example.com/v1")
        self.assertEqual(ok.status_code, 201)

    def test_default_profile_unique(self):
        first = self._create(name="default-a")
        self.assertEqual(first.status_code, 201)
        second = self._create(name="default-b", is_default=True)
        self.assertEqual(second.status_code, 201)
        listing = client.get("/api/llm-profiles", headers=self.h).json()
        defaults = [item for item in listing if item["is_default"]]
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0]["name"], "default-b")

    def test_config_changes_are_audited(self):
        created = self._create(name="audit-profile")
        profile_id = created.json()["id"]
        updated = client.patch(
            f"/api/llm-profiles/{profile_id}",
            json={"model_id": "glm-5"},
            headers=self.h,
        )
        self.assertEqual(updated.status_code, 200)
        with SessionLocal() as db:
            actions = [
                row.action
                for row in db.query(PlatformAuditEvent)
                .filter(
                    PlatformAuditEvent.resource_type == "llm_profile",
                    PlatformAuditEvent.resource_id == profile_id,
                )
                .all()
            ]
        self.assertIn("llm_profile.create", actions)
        self.assertIn("llm_profile.update", actions)

    def test_update_rotates_key_without_returning_it(self):
        rotated_secret = _fake_key("rotate")
        created = self._create(name="rotate-profile")
        profile_id = created.json()["id"]
        rotated = client.patch(
            f"/api/llm-profiles/{profile_id}",
            json={"api_key": rotated_secret},
            headers=self.h,
        )
        self.assertEqual(rotated.status_code, 200)
        self.assertTrue(rotated.json()["api_key_masked"].endswith(rotated_secret[-4:]))
        self.assertNotIn(rotated_secret, rotated.text)

    def test_deployment_accepts_only_cloud_or_private(self):
        response = self._create(name="bad-deploy", deployment="hybrid")
        self.assertEqual(response.status_code, 422)
        ok = self._create(name="private-deploy", deployment="private")
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.json()["deployment"], "private")

    def test_connectivity_probe_rejects_non_admin(self):
        created = self._create(name="probe-profile")
        profile_id = created.json()["id"]
        self.assertEqual(
            client.post(
                f"/api/llm-profiles/{profile_id}/test", headers=self.h_user
            ).status_code,
            403,
        )

    def test_env_bootstrap_creates_single_default_profile(self):
        from app.services.llm_gateway import bootstrap_default_llm_profile

        env_secret = _fake_key("env")
        with SessionLocal() as db:
            db.query(LLMProfile).delete()
            db.commit()
        with mock.patch.object(settings, "llm_api_url", _LLM_URL), mock.patch.object(
            settings, "llm_api_key", env_secret
        ), mock.patch.object(settings, "llm_model", "glm-4.6"):
            self.assertTrue(bootstrap_default_llm_profile(SessionLocal))
            self.assertFalse(bootstrap_default_llm_profile(SessionLocal))
        with SessionLocal() as db:
            profiles = db.query(LLMProfile).all()
            self.assertEqual(len(profiles), 1)
            profile = profiles[0]
            self.assertTrue(profile.is_default)
            self.assertEqual(profile.api_url, _LLM_URL)
            self.assertIsNotNone(profile.api_key_encrypted)
            self.assertNotIn(env_secret, profile.api_key_encrypted)


class TestLLMProfilesMigrations(unittest.TestCase):
    def test_upgrade_downgrade_roundtrip(self):
        original_url = settings.database_url
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "llm_profiles_migration.db").replace("\\", "/")
            settings.database_url = f"sqlite:///{db_path}"
            try:
                cfg = Config("alembic.ini")
                command.upgrade(cfg, "head")
                engine2 = sa.create_engine(f"sqlite:///{db_path}")
                inspector = sa.inspect(engine2)
                self.assertIn("llm_profiles", inspector.get_table_names())
                engine2.dispose()
                command.downgrade(cfg, "20261020_74")
                engine3 = sa.create_engine(f"sqlite:///{db_path}")
                inspector = sa.inspect(engine3)
                self.assertNotIn("llm_profiles", inspector.get_table_names())
                engine3.dispose()
                command.upgrade(cfg, "head")
            finally:
                settings.database_url = original_url
