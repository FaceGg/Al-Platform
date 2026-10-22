"""LLM gateway service tests (AutoML Agent plan, Task A1.3).

Contract under test: profile resolution (explicit id → default → env
fallback), gateway completion with egress audit (metadata only, never
content), and removal of request-level endpoint overrides across the three
consumer surfaces (chat / knowledge / orchestration).
"""

import os
import unittest
from unittest import mock
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from cryptography.fernet import Fernet  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.knowledge import KnowledgeBase  # noqa: E402
from app.models.llm_profile import LLMProfile  # noqa: E402
from app.models.platform_audit import PlatformAuditEvent  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.llm_gateway import (  # noqa: E402
    GatewayLLMConfig,
    LLMProfileNotFoundError,
    chat_completion,
    resolve_profile,
)
from app.services.llm_profile_crypto import encrypt_llm_api_key  # noqa: E402
from tests.auth_test_support import ensure_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(__import__("app.main", fromlist=["app"]).app)

_ADMIN_USER = "gateway-admin-" + uuid4().hex[:8]
_ADMIN_PASSWORD = uuid4().hex + uuid4().hex[:4]
_GATEWAY_URL = "https://api.gateway-test-llm.com/v1/chat/completions"
_ENV_URL = "https://api.env-fallback-llm.com/v1/chat/completions"


def _fake_config(**extra) -> GatewayLLMConfig:
    base = {
        "api_url": _GATEWAY_URL,
        "api_key": "sk-" + uuid4().hex,
        "model_id": "glm-4.6",
        "temperature": None,
        "timeout_seconds": 60,
        "profile_id": str(uuid4()),
        "profile_name": "gateway-test",
    }
    base.update(extra)
    return GatewayLLMConfig(**base)


class TestLLMGateway(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin(_ADMIN_USER, _ADMIN_PASSWORD)
        cls.token = client.post(
            "/api/auth/login",
            data={"username": _ADMIN_USER, "password": _ADMIN_PASSWORD},
        ).json()["access_token"]
        cls.h = {"Authorization": "Bearer " + cls.token}
        with SessionLocal() as db:
            settings.llm_master_key = SecretStr(
                Fernet.generate_key().decode("ascii")
            )

    def _make_profile(self, name="gateway-default", is_default=True, url=_GATEWAY_URL):
        with SessionLocal() as db:
            profile = LLMProfile(
                name=name + "-" + uuid4().hex[:6],
                api_url=url,
                api_key_encrypted=encrypt_llm_api_key(
                    "sk-" + uuid4().hex, settings.llm_master_key
                ),
                model_id="glm-4.6",
                is_default=is_default,
            )
            if is_default:
                db.query(LLMProfile).update({LLMProfile.is_default: False})
            db.add(profile)
            db.commit()
            return str(profile.id)

    def test_resolve_explicit_then_default_then_env_fallback(self):
        profile_id = self._make_profile()
        with SessionLocal() as db:
            explicit = resolve_profile(db, profile_id=profile_id, purpose="test")
            default = resolve_profile(db, purpose="test")
        self.assertEqual(explicit.profile_id, profile_id)
        self.assertEqual(explicit.api_url, _GATEWAY_URL)
        self.assertTrue(explicit.api_key)
        self.assertEqual(default.profile_id, profile_id)
        with SessionLocal() as db:
            db.query(LLMProfile).delete()
            db.commit()
            with mock.patch.object(settings, "llm_api_url", _ENV_URL), \
                 mock.patch.object(settings, "llm_api_key", "env-fallback-key"):
                fallback = resolve_profile(db, purpose="test")
        self.assertIsNone(fallback.profile_id)
        self.assertEqual(fallback.api_url, _ENV_URL)

    def test_resolve_unknown_profile_raises(self):
        with SessionLocal() as db:
            with self.assertRaises(LLMProfileNotFoundError):
                resolve_profile(db, profile_id=str(uuid4()), purpose="test")

    def test_chat_completion_posts_and_audits_egress_without_content(self):
        profile_id = self._make_profile(name="egress")
        config = _fake_config(profile_id=profile_id)
        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs["json"]
            response = mock.Mock()
            response.status_code = 200
            response.json.return_value = {
                "choices": [{"message": {"content": "pong"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            }
            return response

        with SessionLocal() as db, mock.patch(
            "app.services.llm_gateway.httpx.post", side_effect=fake_post
        ):
            user = db.query(User).filter(User.username == _ADMIN_USER).first()
            reply, usage = chat_completion(
                db,
                config=config,
                messages=[{"role": "user", "content": "SECRET-CONTENT-XYZ"}],
                purpose="test",
                actor=user,
            )
            db.commit()  # gateway flushes audit; caller owns the transaction
        self.assertEqual(reply, "pong")
        self.assertEqual(captured["url"], _GATEWAY_URL)
        self.assertEqual(captured["json"]["model"], "glm-4.6")
        with SessionLocal() as db:
            events = (
                db.query(PlatformAuditEvent)
                .filter(
                    PlatformAuditEvent.action == "llm_gateway.egress",
                    PlatformAuditEvent.resource_id == profile_id,
                )
                .all()
            )
            self.assertEqual(len(events), 1)
            serialized = repr(events[0].changes)
            self.assertNotIn("SECRET-CONTENT-XYZ", serialized)
            self.assertIn("test", serialized)

    def test_chat_rejects_request_level_overrides(self):
        response = client.post(
            "/api/chat",
            json={"message": "hi", "model": "glm-4.6"},
            headers=self.h,
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"]["code"], "LLM_REQUEST_OVERRIDE_REMOVED"
        )
        response = client.post(
            "/api/chat",
            json={"message": "hi", "api_key": "sk-x"},
            headers=self.h,
        )
        self.assertEqual(response.status_code, 422)

    def test_knowledge_rag_rejects_request_level_url_override(self):
        with SessionLocal() as db:
            user = db.query(User).filter(User.username == _ADMIN_USER).first()
            kb = KnowledgeBase(
                name="gateway-kb-" + uuid4().hex[:6],
                description="",
                owner_id=user.id,
            )
            db.add(kb)
            db.commit()
            kb_id = str(kb.id)
        response = client.post(
            f"/api/knowledge/bases/{kb_id}/rag",
            json={"query": "q", "llm_api_url": "https://evil.example.com/v1"},
            headers=self.h,
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"]["code"], "LLM_REQUEST_OVERRIDE_REMOVED"
        )

    def test_orchestration_uses_gateway_resolution(self):
        from app.api import orchestration as orch

        with mock.patch.object(orch, "_orchestrator", None):
            profile_id = self._make_profile(name="orch-profile")
            created = []
            real_orchestrator = orch.Orchestrator

            def capture(db, api_url, api_key):
                created.append(api_url)
                return mock.Mock()

            with mock.patch.object(orch, "Orchestrator", side_effect=capture):
                orch.get_orchestrator()
        self.assertEqual(created, [_GATEWAY_URL])
