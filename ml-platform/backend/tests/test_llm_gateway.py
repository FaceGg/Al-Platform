"""LLM gateway service tests (AutoML Agent plan, Task A1.3).

Contract under test: profile resolution (explicit id → default → env
fallback), gateway completion with egress audit (metadata only, never
content), and removal of request-level endpoint overrides across the three
consumer surfaces (chat / knowledge / orchestration).
"""

import os
import unittest
from contextlib import contextmanager
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
from app.services import llm_gateway  # noqa: E402
from app.services.llm_gateway import (  # noqa: E402
    GatewayLLMConfig,
    LLMProfileNotFoundError,
    LLMStreamStalled,
    _HTTP_CLIENT,
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

        @contextmanager
        def fake_stream(method, url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs["json"]
            response = mock.MagicMock()
            response.status_code = 200
            response.iter_lines.return_value = iter([
                'data: {"choices": [{"delta": {"content": "po"}}]}',
                'data: {"choices": [{"delta": {"content": "ng"}}]}',
                'data: {"choices": [{}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}',
                "data: [DONE]",
            ])
            yield response

        with SessionLocal() as db, mock.patch.object(
            _HTTP_CLIENT, "stream", side_effect=fake_stream
        ):
            user = db.query(User).filter(User.username == _ADMIN_USER).first()
            reply, usage, _reasoning = chat_completion(
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
        self.assertEqual(usage.get("completion_tokens"), 1)
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
            # tokens 随审计落库（使用统计页数据源）：fake stream 的 usage
            # prompt=3 / completion=1
            self.assertEqual(events[0].changes.get("prompt_tokens"), 3)
            self.assertEqual(events[0].changes.get("completion_tokens"), 1)
            self.assertEqual(events[0].changes.get("total_tokens"), 4)

    def test_anthropic_stream_usage_merged_with_total(self):
        """Anthropic 流：输入 token 在 message_start、输出在 message_delta
        （不带 input_tokens）——合并后补 total_tokens。智能体 runner 按
        total_tokens 累计任务用量，曾因缺它（覆盖式取最后一段）恒记 0。"""
        config = _fake_config(provider="anthropic")

        @contextmanager
        def fake_stream(method, url, **kwargs):
            response = mock.MagicMock()
            response.status_code = 200
            response.iter_lines.return_value = iter([
                "event: message_start",
                'data: {"type": "message_start", "message": {"usage": {"input_tokens": 120, "output_tokens": 1}}}',
                'data: {"type": "content_block_delta", "delta": {"text": "ok"}}',
                'data: {"type": "message_delta", "usage": {"output_tokens": 30}}',
            ])
            yield response

        with SessionLocal() as db, mock.patch.object(
            _HTTP_CLIENT, "stream", side_effect=fake_stream
        ):
            reply, usage, _reasoning = chat_completion(
                db,
                config=config,
                messages=[{"role": "user", "content": "hi"}],
                purpose="test",
            )
        self.assertEqual(reply, "ok")
        self.assertEqual(usage.get("prompt_tokens"), 120)
        self.assertEqual(usage.get("completion_tokens"), 30)
        self.assertEqual(usage.get("total_tokens"), 150)

    def _stream_with(self, lines_factory):
        @contextmanager
        def fake_stream(method, url, **kwargs):
            response = mock.MagicMock()
            response.status_code = 200
            response.iter_lines.return_value = lines_factory()
            yield response

        return fake_stream

    def test_stall_after_output_began_fails_fast(self):
        """开始出字后上游静默：看门狗按 STREAM_STALL_SECONDS 判卡死（此前干等
        整段读超时 240s+重连 60s，单次卡死白丢约 5 分钟）。"""
        import threading
        import time

        release = threading.Event()

        def lines():
            yield 'data: {"choices": [{"delta": {"content": "po"}}]}'
            release.wait(5)  # 上游卡住：连接仍在但不再来数据

        config = _fake_config()
        started = time.monotonic()
        try:
            with SessionLocal() as db, mock.patch.object(
                llm_gateway, "STREAM_STALL_SECONDS", 0.3
            ), mock.patch.object(_HTTP_CLIENT, "stream", side_effect=self._stream_with(lines)):
                with self.assertRaises(LLMStreamStalled):
                    chat_completion(db, config=config,
                                    messages=[{"role": "user", "content": "hi"}],
                                    purpose="test")
        finally:
            release.set()
        self.assertLess(time.monotonic() - started, 3.0)

    def test_silence_before_first_delta_is_not_a_stall(self):
        """首字前的静默（推理型隐藏思考/长 prefill）不触发看门狗，由读超时兜底。"""
        import time

        def lines():
            yield 'data: {"choices": [{"delta": {"role": "assistant"}}]}'
            time.sleep(0.6)  # > 看门狗阈值，但尚未出字
            yield 'data: {"choices": [{"delta": {"content": "ok"}}]}'
            yield 'data: {"choices": [{}], "usage": {"prompt_tokens": 2, "completion_tokens": 1}}'
            yield "data: [DONE]"

        config = _fake_config()
        with SessionLocal() as db, mock.patch.object(
            llm_gateway, "STREAM_STALL_SECONDS", 0.3
        ), mock.patch.object(_HTTP_CLIENT, "stream", side_effect=self._stream_with(lines)):
            reply, usage, _reasoning = chat_completion(
                db, config=config, messages=[{"role": "user", "content": "hi"}],
                purpose="test")
        self.assertEqual(reply, "ok")
        self.assertEqual(usage.get("total_tokens"), 3)

    def test_stream_stall_is_retryable(self):
        from app.services.agent.llm_client import _is_retryable_error

        self.assertTrue(_is_retryable_error(LLMStreamStalled("stalled")))
        self.assertTrue(_is_retryable_error(llm_gateway.LLMStreamOverran("overran")))

    def test_trickling_stream_hits_wall_limit(self):
        """涓流形态（不断掉字节但生成极慢）：断流看门狗不触发，总时长上限兜底。"""
        import time

        def lines():
            for _ in range(200):
                yield 'data: {"choices": [{"delta": {"content": "x"}}]}'
                time.sleep(0.05)  # 持续出字（armed），永不结束

        config = _fake_config()
        started = time.monotonic()
        try:
            with SessionLocal() as db, mock.patch.object(
                llm_gateway, "STREAM_STALL_SECONDS", 5
            ), mock.patch.object(
                llm_gateway, "STREAM_ATTEMPT_WALL_SECONDS", 1
            ), mock.patch.object(_HTTP_CLIENT, "stream", side_effect=self._stream_with(lines)):
                with self.assertRaises(llm_gateway.LLMStreamOverran):
                    chat_completion(db, config=config,
                                    messages=[{"role": "user", "content": "hi"}],
                                    purpose="test")
        finally:
            pass
        self.assertLess(time.monotonic() - started, 5.0)

    def test_usage_stats_aggregates_egress_events(self):
        # 管理端点聚合合同：汇总/按天/按模型/按用途，tokens 只计带用量的记录
        import uuid as _uuid
        from datetime import timedelta as _timedelta

        from app.tasks.time_utils import utcnow as _utcnow

        with SessionLocal() as db:
            admin = db.query(User).filter(User.username == _ADMIN_USER).first()
            # 共享测试库可能已有窗口内 egress 事件：记录基线，断言用增量
            since = _utcnow() - _timedelta(days=1)
            baseline = (
                db.query(PlatformAuditEvent)
                .filter(
                    PlatformAuditEvent.action == "llm_gateway.egress",
                    PlatformAuditEvent.created_at >= since,
                )
                .count()
            )
            base = {
                "action": "llm_gateway.egress",
                "resource_type": "llm_profile",
                "actor_id": admin.id,
                "actor_username": admin.username,
                "request_id": _uuid.uuid4(),
            }
            for row in (
                {"result": "success", "changes": {"purpose": "agent_s1", "model": "deepseek-chat", "prompt_tokens": 100, "completion_tokens": 50, "latency_ms": 800.0}},
                {"result": "failed", "changes": {"purpose": "agent_s1", "model": "deepseek-chat", "latency_ms": 200.0}},
                {"result": "success", "changes": {"purpose": "chat", "model": "glm-4.6", "prompt_tokens": 30, "completion_tokens": 20, "latency_ms": 400.0}},
            ):
                db.add(PlatformAuditEvent(created_at=_utcnow(), **{**base, **row}))
            db.commit()
        response = client.get("/api/llm-profiles/usage-stats?days=1", headers=self.h)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # 增量合同：本用例贡献 3 次调用 / 1 失败 / 130+70 tokens
        self.assertEqual(data["summary"]["total_calls"] - baseline, 3)
        self.assertGreaterEqual(data["summary"]["failed_calls"], 1)
        self.assertGreaterEqual(data["summary"]["prompt_tokens"], 130)
        self.assertGreaterEqual(data["summary"]["total_tokens"], 200)
        self.assertIsNotNone(data["summary"]["avg_latency_ms"])
        models = {row["model"]: row for row in data["by_model"]}
        self.assertGreaterEqual(models["deepseek-chat"]["calls"], 2)
        self.assertGreaterEqual(models["deepseek-chat"]["completion_tokens"], 50)
        purposes = {row["purpose"]: row for row in data["by_purpose"]}
        self.assertGreaterEqual(purposes["agent_s1"]["calls"], 2)
        self.assertGreaterEqual(len(data["by_day"]), 1)

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
