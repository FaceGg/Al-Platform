"""LLM 阶段调用瞬时故障重试测试。

合同：网络类瞬时错误（含 ReadError/Errno 104 连接重置——非流式长生成
被中间设备掐断的典型形态）与空回复都自动重试（退避 5s/15s）；非网络
类错误立即返回不重试；契约失败发生在调用成功之后，不属于重试层。
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from app.services.agent import llm_client  # noqa: E402


class _FakeHttpxError(Exception):
    """以 httpx 异常类名伪装，命中 _TRANSIENT_NETWORK_ERRORS 名单。"""


def _patch_sleep():
    return mock.patch("time.sleep", lambda *_: None)


class TestChatCompletionWithRetry(unittest.TestCase):
    def _call(self, side_effects):
        calls = {"n": 0}

        def fake_chat_completion(db, **kwargs):
            calls["n"] += 1
            outcome = side_effects[min(calls["n"], len(side_effects)) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome, {"total_tokens": 10}

        with mock.patch.object(llm_client, "chat_completion", fake_chat_completion), _patch_sleep():
            reply, usage, error = llm_client.chat_completion_with_retry(
                db=None,
                config=mock.Mock(),
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2,
                max_tokens=100,
                purpose="test",
            )
        return reply, usage, error, calls["n"]

    def test_read_error_retried_until_success(self):
        # Errno 104 连接重置形态：第 1 次被掐，第 2 次成功
        error = _FakeHttpxError("[Errno 104] Connection reset by peer")
        error.__class__.__name__ = "ReadError"
        reply, _usage, err, calls = self._call([error, "ok"])
        self.assertEqual(err, None)
        self.assertEqual(reply, "ok")
        self.assertEqual(calls, 2)

    def test_empty_completion_retried_then_success(self):
        # 上游负载空回复：暂态，重试可救
        reply, _usage, err, calls = self._call([None, "fine"])
        self.assertEqual(err, None)
        self.assertEqual(reply, "fine")
        self.assertEqual(calls, 2)

    def test_transient_exhausted_reports_attempts(self):
        error = _FakeHttpxError("reset")
        error.__class__.__name__ = "ReadError"
        reply, _usage, err, calls = self._call([error, error, error])
        self.assertIsNone(reply)
        self.assertIn("ReadError", err)
        self.assertIn("3 attempts incl. backoff", err)
        self.assertEqual(calls, 3)

    def test_empty_exhausted_reports_empty(self):
        reply, _usage, err, _calls = self._call([None, None, None])
        self.assertIsNone(reply)
        self.assertIn("llm_empty_completion", err)
        self.assertIn("3 attempts", err)

    def test_non_transient_fails_immediately(self):
        error = _FakeHttpxError("bad request")
        error.__class__.__name__ = "HTTPStatusError"
        reply, _usage, err, calls = self._call([error, "ok"])
        self.assertIsNone(reply)
        self.assertIn("HTTPStatusError", err)
        self.assertEqual(calls, 1)  # 非暂态不重试

    def test_run_s2_uses_retry_path(self):
        # S2 此前完全没有重试；接入后网络错误应重试而非直接失败
        error = _FakeHttpxError("reset")
        error.__class__.__name__ = "ReadError"
        responses = iter([error, '{"script": "return df", "description": "demo"}'])

        def fake_chat_completion(db, **kwargs):
            outcome = next(responses)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome, {}

        with mock.patch.object(llm_client, "chat_completion", fake_chat_completion), _patch_sleep():
            script, err, _usage = llm_client.run_s2(
                db=None, config=mock.Mock(), brief="b", columns=[{"name": "c", "dtype": "float64"}],
                leakage_suspects=[], error_history=[], meta_hint=False, guidance=None,
            )
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
