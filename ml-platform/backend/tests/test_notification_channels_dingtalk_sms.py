"""通知通道补齐（补齐路线第一批 P5，B1-11/D9）测试。

覆盖（技术方案 §11.1 test_notification_channels_dingtalk_sms.py 行）：
- 钉钉加签向量：sign = base64(hmac_sha256(secret, "{timestamp_ms}\\n{secret}"))，
  timestamp/sign 进 query；固定输入锁回归向量；
- 网关适配器请求构造：钉钉 text 消息体 + 幂等头；短信网关逐号码渲染
  body_template、自定义请求头白名单、全成才 sent、任一失败即 retry/failed；
- kind 枚举四处一致：模型常量 == DB CHECK == 契约 Literal == 路由分发；
- 配置归一化校验（dingtalk/sms_gateway）；
- 平台就绪载荷带通道形态清单。

注：测试用密钥/加签口令一律运行时拼接或派生（非真实凭据）。
"""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import unittest
from typing import get_args
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import Base
from app.events.domain import DomainEvent
from app.models.notifications import NOTIFICATION_ENDPOINT_KINDS, NotificationEndpoint
from app.models.project import Project
from app.models.user import User
from app.schemas.notifications import NotificationEndpointKind, normalize_endpoint_config
from app.services.notification_channels import (
    DingTalkNotificationAdapter,
    NotificationChannelRouter,
    SmsGatewayNotificationAdapter,
)
from app.services.notification_crypto import encrypt_config

MASTER_KEY = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
NEW_KINDS = ("dingtalk", "sms_gateway")
ALL_KINDS = ("in_app", "wecom", "email", "webhook", "dingtalk", "sms_gateway")

# 加签向量输入（运行时拼接；仅作回归向量，无凭据意义）
VECTOR_SECRET = "-".join(("SEC", "vector", "0001"))
VECTOR_TIMESTAMP_MS = "1700000000000"


def _expected_sign(secret: str, timestamp_ms: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp_ms}\n{secret}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def public_resolution(_host, _port):
    return ["8.8.8.8"]


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class RecordingHttpClient:
    """按调用次序返回预置响应的桩（post/get 都记录）。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self):
        return self.responses.pop(0) if self.responses else FakeResponse(200)

    def post(self, url, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self._next()

    def get(self, url, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self._next()


class TestDingTalkAdapter(unittest.TestCase):
    def _adapter(self, client):
        return DingTalkNotificationAdapter(
            {"url": "https://oapi.dingtalk.com/robot/send", "secret": VECTOR_SECRET},
            http_client=client,
            timeout_seconds=5,
            max_payload_bytes=65536,
            resolve=public_resolution,
            allowlist=(),
        )

    def test_signing_vector_matches_reference(self):
        adapter = self._adapter(RecordingHttpClient([]))
        with patch("app.services.notification_channels.time.time", return_value=1700000000.0):
            signed = adapter._signed_url("https://oapi.dingtalk.com/robot/send", VECTOR_SECRET)
        query = parse_qs(urlsplit(signed).query)
        self.assertEqual(query["timestamp"], [VECTOR_TIMESTAMP_MS])
        self.assertEqual(query["sign"], [_expected_sign(VECTOR_SECRET, VECTOR_TIMESTAMP_MS)])
        # 既有 query 的 URL 用 & 续接
        joined = adapter._signed_url("https://oapi.dingtalk.com/robot/send?access_token=t", VECTOR_SECRET)
        self.assertIn("&timestamp=", joined)

    def test_request_is_text_message_with_idempotency_header(self):
        client = RecordingHttpClient([FakeResponse(200)])
        adapter = self._adapter(client)
        result = adapter.send(
            endpoint=self._endpoint(),
            event=self._event(),
            delivery_key="delivery-dingtalk",
        )
        self.assertEqual(result.status, "sent")
        call = client.calls[0]
        self.assertEqual(call["headers"]["Idempotency-Key"], "delivery-dingtalk")
        payload = json.loads(call["content"].decode("utf-8"))
        self.assertEqual(payload["msgtype"], "text")
        self.assertIn("rollout.completed", payload["text"]["content"])
        # 安全信封：事件 payload 的非白名单键不出现在消息体
        self.assertNotIn("must-not-send", payload["text"]["content"])
        # 加签口令不进请求体与请求头
        self.assertNotIn(VECTOR_SECRET, call["content"].decode("utf-8"))
        self.assertNotIn(VECTOR_SECRET, json.dumps(call["headers"]))

    def test_unsigned_webhook_omits_sign(self):
        client = RecordingHttpClient([FakeResponse(200)])
        adapter = DingTalkNotificationAdapter(
            {"url": "https://oapi.dingtalk.com/robot/send"},
            http_client=client,
            timeout_seconds=5,
            max_payload_bytes=65536,
            resolve=public_resolution,
            allowlist=(),
        )
        result = adapter.send(endpoint=self._endpoint(), event=self._event(), delivery_key="k")
        self.assertEqual(result.status, "sent")
        self.assertNotIn("sign=", client.calls[0]["url"])

    def test_provider_errors_map_to_retry_or_failed(self):
        retry = self._adapter(RecordingHttpClient([FakeResponse(500)])).send(
            endpoint=self._endpoint(), event=self._event(), delivery_key="k",
        )
        self.assertEqual(retry.status, "retry")
        rejected = self._adapter(RecordingHttpClient([FakeResponse(400)])).send(
            endpoint=self._endpoint(), event=self._event(), delivery_key="k",
        )
        self.assertEqual(rejected.status, "failed")

    def _endpoint(self):
        return NotificationEndpoint(
            id=uuid4(), project_id=None, kind="dingtalk", name="ding",
            destination_hint="hint", encrypted_config="x",
        )

    def _event(self):
        return DomainEvent(
            event_id=uuid4(), idempotency_key="e1", event_type="rollout.completed",
            severity="warning", occurred_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
            project_id=None, actor_id=None, resource_type="deployment",
            resource_id="deployment-1", payload={"revision_id": "revision-1"},
        )


class TestSmsGatewayAdapter(unittest.TestCase):
    def _adapter(self, client, **config):
        base = {
            "url": "https://sms-gateway.example.invalid/send",
            "method": "POST",
            "headers": {"X-Tenant": "plant-a"},
            "body_template": "phone={phone}&text={content}",
            "to": ["13800000001", "13800000002"],
        }
        base.update(config)
        return SmsGatewayNotificationAdapter(
            base,
            http_client=client,
            timeout_seconds=5,
            max_payload_bytes=65536,
            resolve=public_resolution,
            allowlist=(),
        )

    def _event(self):
        return DomainEvent(
            event_id=uuid4(), idempotency_key="e1", event_type="rollout.failed",
            severity="critical", occurred_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
            project_id=None, actor_id=None, resource_type="deployment",
            resource_id="deployment-1", payload={"error_code": "X"},
        )

    def _endpoint(self):
        return NotificationEndpoint(
            id=uuid4(), project_id=None, kind="sms_gateway", name="sms",
            destination_hint="hint", encrypted_config="x",
        )

    def test_renders_template_per_recipient(self):
        client = RecordingHttpClient([FakeResponse(200), FakeResponse(200)])
        result = self._adapter(client).send(
            endpoint=self._endpoint(), event=self._event(), delivery_key="delivery-sms",
        )
        self.assertEqual(result.status, "sent")
        self.assertEqual(len(client.calls), 2)
        first, second = (call["content"].decode("utf-8") for call in client.calls)
        self.assertTrue(first.startswith("phone=13800000001&text="))
        self.assertTrue(second.startswith("phone=13800000002&text="))
        # 内容来自安全事件信封（不含非白名单 payload 键）
        self.assertIn("rollout.failed", first)
        self.assertNotIn("error_code", first)
        self.assertEqual(client.calls[0]["headers"]["X-Tenant"], "plant-a")

    def test_get_method_sends_params(self):
        client = RecordingHttpClient([FakeResponse(200), FakeResponse(200)])
        self._adapter(client, method="GET").send(
            endpoint=self._endpoint(), event=self._event(), delivery_key="k",
        )
        self.assertEqual(client.calls[0]["method"], "GET")
        self.assertEqual(client.calls[0]["params"]["phone"], "13800000001")

    def test_partial_failure_is_not_sent(self):
        client = RecordingHttpClient([FakeResponse(200), FakeResponse(503)])
        result = self._adapter(client).send(
            endpoint=self._endpoint(), event=self._event(), delivery_key="k",
        )
        self.assertEqual(result.status, "retry")
        # 首个失败即停，不继续投后续号码
        self.assertEqual(len(client.calls), 2)
        rejected = self._adapter(RecordingHttpClient([FakeResponse(400)])).send(
            endpoint=self._endpoint(), event=self._event(), delivery_key="k",
        )
        self.assertEqual(rejected.status, "failed")

    def test_forbidden_header_rejected_before_request(self):
        client = RecordingHttpClient([])
        result = self._adapter(client, headers={"Host": "evil.example.invalid"}).send(
            endpoint=self._endpoint(), event=self._event(), delivery_key="k",
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "NOTIFICATION_ENDPOINT_FORBIDDEN")
        self.assertEqual(client.calls, [])


class TestKindEnumConsistency(unittest.TestCase):
    """kind 枚举四处一致：模型常量 / DB CHECK / 契约 Literal / 路由分发。"""

    def test_model_tuple_matches_contract_literal(self):
        self.assertEqual(set(NOTIFICATION_ENDPOINT_KINDS), set(ALL_KINDS))
        self.assertEqual(
            set(get_args(NotificationEndpointKind)), set(NOTIFICATION_ENDPOINT_KINDS),
        )

    def test_db_check_constraint_covers_all_kinds(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        checks = {
            constraint["sqltext"]
            for constraint in inspect(engine).get_check_constraints("notification_endpoints")
            if constraint["name"] == "ck_notification_endpoint_kind"
        }
        engine.dispose()
        self.assertEqual(len(checks), 1)
        listed = {
            item.strip().strip("'")
            for item in next(iter(checks)).split("IN (")[1].rstrip(")").split(",")
        }
        self.assertEqual(listed, set(ALL_KINDS))

    def test_router_dispatches_new_kinds(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine, expire_on_commit=False)()
        try:
            user = User(username=f"sms-ding-{uuid4().hex[:6]}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="New channel kinds", owner_id=user.id)
            db.add(project)
            db.flush()
            master_key = SecretStr(MASTER_KEY)
            settings = Settings(_env_file=None, notification_master_key=MASTER_KEY)
            event_obj = DomainEvent(
                event_id=uuid4(), idempotency_key="e1", event_type="rollout.completed",
                severity="warning", occurred_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
                project_id=None, actor_id=None, resource_type="deployment",
                resource_id="d", payload={},
            )
            configs = {
                "dingtalk": {"url": "https://oapi.dingtalk.com/robot/send"},
                "sms_gateway": {
                    "url": "https://sms-gateway.example.invalid/send",
                    "body_template": "{phone}:{content}", "to": ["13800000000"],
                },
            }
            for kind in NEW_KINDS:
                with self.subTest(kind=kind):
                    endpoint = NotificationEndpoint(
                        project_id=project.id, kind=kind, name=f"{kind}-{uuid4().hex[:6]}",
                        destination_hint="hint",
                        encrypted_config=encrypt_config(configs[kind], master_key),
                    )
                    db.add(endpoint)
                    db.commit()
                    client = RecordingHttpClient([FakeResponse(200)])
                    result = NotificationChannelRouter(
                        db, settings, http_client=client, resolve=public_resolution,
                    ).send(endpoint=endpoint, event=event_obj, delivery_key=f"k-{kind}")
                    self.assertEqual(result.status, "sent", result.error_code)
                    self.assertEqual(len(client.calls), 1)
        finally:
            db.close()
            engine.dispose()


class TestConfigNormalization(unittest.TestCase):
    def test_dingtalk_normalizes_and_rejects(self):
        self.assertEqual(
            normalize_endpoint_config("dingtalk", {"url": "https://oapi.dingtalk.com/robot/send"}),
            {"url": "https://oapi.dingtalk.com/robot/send"},
        )
        self.assertEqual(
            normalize_endpoint_config(
                "dingtalk", {"url": "https://oapi.dingtalk.com/robot/send", "secret": VECTOR_SECRET},
            )["secret"],
            VECTOR_SECRET,
        )
        for bad in ({"url": "https://x", "extra": 1}, {"secret": "x"}, {"url": "https://x", "secret": ""}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_endpoint_config("dingtalk", bad)

    def test_sms_gateway_normalizes_and_rejects(self):
        normalized = normalize_endpoint_config("sms_gateway", {
            "url": "https://sms-gateway.example.invalid/send",
            "body_template": "{phone}:{content}",
            "to": [" 13800000000 "],
        })
        self.assertEqual(normalized["method"], "POST")
        self.assertEqual(normalized["to"], ["13800000000"])
        invalid = (
            {"url": "https://x", "body_template": "no placeholders", "to": ["1"]},
            {"url": "https://x", "body_template": "{phone}{content}", "to": []},
            {"url": "https://x", "body_template": "{phone}{content}", "to": ["1"], "method": "PUT"},
            {"url": "https://x", "body_template": "{phone}{content}", "to": ["1"], "headers": {"A": 1}},
            {"url": "https://x", "body_template": "{phone}{content}", "to": ["1"], "password": "z"},
        )
        for bad in invalid:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_endpoint_config("sms_gateway", bad)


class TestReadinessChannelKinds(unittest.TestCase):
    def test_payload_lists_channel_kinds(self):
        from app.services.readiness_service import ReadinessService

        settings = Settings(_env_file=None)
        service = ReadinessService(
            engine=None, settings=settings, redis_client=None, celery_app=None,
            storage=None, http_client=None, probe_timeout_seconds=0.01,
        )
        with patch.object(service, "_run_probes_concurrently", return_value={
            "database": {"ready": True, "code": "OK"},
            "redis": {"ready": True, "code": "OK"},
            "celery": {"ready": True, "code": "OK"},
            "storage": {"ready": True, "code": "OK"},
            "mlflow": {"ready": True, "code": "OK"},
            "tensorboard": {"ready": True, "code": "OK"},
            "inference_runtime": {"ready": True, "code": "OK"},
            "notification_worker_registered": True,
            "migration_head": "x",
        }):
            payload = service.check_all()
        self.assertEqual(payload["notification_channel_kinds"], list(ALL_KINDS))


if __name__ == "__main__":
    unittest.main()
