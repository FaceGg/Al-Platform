"""LLM 阶段调用断线重连测试。

合同（2026-11-08 定稿）：网络类断连（含 ReadError/Errno 104 连接重置——
长生成被中间设备掐断的典型形态）与空回复自动重连——最多 5 次、每次间隔
60s，全部失败才返回错误；非网络类错误立即返回不重连；契约失败发生在
调用成功之后，不属于重连层。
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
    def _call(self, side_effects, **kwargs):
        calls = {"n": 0}

        def fake_chat_completion(db, **_kwargs):
            calls["n"] += 1
            outcome = side_effects[min(calls["n"], len(side_effects)) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome, {"total_tokens": 10}, None

        with mock.patch.object(llm_client, "chat_completion", fake_chat_completion), _patch_sleep():
            reply, usage, error = llm_client.chat_completion_with_retry(
                db=None,
                config=mock.Mock(),
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2,
                max_tokens=100,
                purpose="test",
                **kwargs,
            )
        return reply, usage, error, calls["n"]

    def test_read_error_reconnected_until_success(self):
        # Errno 104 连接重置形态：第 1 次被掐，第 2 次重连成功
        error = _FakeHttpxError("[Errno 104] Connection reset by peer")
        error.__class__.__name__ = "ReadError"
        reply, _usage, err, calls = self._call([error, "ok"])
        self.assertEqual(err, None)
        self.assertEqual(reply, "ok")
        self.assertEqual(calls, 2)

    def test_empty_completion_reconnected_then_success(self):
        # 上游负载空回复：暂态，重连可救
        reply, _usage, err, calls = self._call([None, "fine"])
        self.assertEqual(err, None)
        self.assertEqual(reply, "fine")
        self.assertEqual(calls, 2)

    def test_transient_exhausted_after_five_reconnects(self):
        # 定稿策略：最多 5 次重连全部失败才放弃（间隔 60s）
        error = _FakeHttpxError("reset")
        error.__class__.__name__ = "ReadError"
        reply, _usage, err, calls = self._call([error] * 5)
        self.assertIsNone(reply)
        self.assertIn("ReadError", err)
        self.assertIn("5 reconnect attempts, 60s interval", err)
        self.assertEqual(calls, 5)

    def test_reconnect_interval_is_sixty_seconds(self):
        # 每次重连间隔固定 60s（非递增退避）
        sleeps = []
        with mock.patch("time.sleep", lambda s, *_: sleeps.append(s)):
            with mock.patch.object(llm_client, "chat_completion",
                                   side_effect=_conn_reset()):
                llm_client.chat_completion_with_retry(
                    db=None, config=mock.Mock(),
                    messages=[{"role": "user", "content": "hi"}],
                    temperature=0.2, max_tokens=100, purpose="test",
                )
        self.assertEqual(sleeps, [60, 60, 60, 60])

    def test_empty_exhausted_reports_empty(self):
        reply, _usage, err, calls = self._call([None] * 5)
        self.assertIsNone(reply)
        self.assertIn("llm_empty_completion", err)
        self.assertIn("5 reconnect attempts", err)
        self.assertEqual(calls, 5)

    def test_non_transient_fails_immediately(self):
        # 确定性失败（认证/契约类，无暂态特征）不重试立即返回
        error = _FakeHttpxError("401 unauthorized: invalid api key")
        error.__class__.__name__ = "HTTPStatusError"
        reply, _usage, err, calls = self._call([error, "ok"])
        self.assertIsNone(reply)
        self.assertIn("HTTPStatusError", err)
        self.assertEqual(calls, 1)  # 非暂态不重连

    def test_internal_error_5xx_retried(self):
        # 内部错误（上游 5xx）也是暂态——同策略重连（用户定稿）
        error = _FakeHttpxError("Server error '500 Internal Server Error'")
        error.__class__.__name__ = "HTTPStatusError"
        reply, _usage, err, calls = self._call([error, "ok"])
        self.assertEqual(err, None)
        self.assertEqual(reply, "ok")
        self.assertEqual(calls, 2)

    def test_internal_error_429_retried(self):
        error = _FakeHttpxError("429 rate limit exceeded, retry later")
        error.__class__.__name__ = "HTTPStatusError"
        reply, _usage, err, calls = self._call([error, "fine"])
        self.assertEqual(err, None)
        self.assertEqual(calls, 2)

    def test_wall_clock_guard_abandons_after_budget(self):
        # 总进展护栏：累计无进展超预算（1h）即放弃，不再等下一轮
        error = _FakeHttpxError("reset")
        error.__class__.__name__ = "ReadError"
        # 单次失败耗时 950s 的极端场景：3 轮后累计 ~2850s，第 4 轮前
        # elapsed(2850)+60 >= 3600 触发护栏放弃（远早于跑满 5 次）
        timings = iter([950, 950, 950, 950, 950])

        def fake_sleep(seconds):
            pass

        fake_clock = {"now": 0.0}

        def fake_chat_completion(db, **_kwargs):
            fake_clock["now"] += next(timings)
            raise error

        import app.services.agent.llm_client as lc

        with mock.patch.object(lc, "chat_completion", fake_chat_completion), \
                mock.patch("time.sleep", fake_sleep), \
                mock.patch("time.monotonic", lambda: fake_clock["now"]):
            reply, _usage, err = lc.chat_completion_with_retry(
                db=None, config=mock.Mock(),
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2, max_tokens=100, purpose="test",
            )
        self.assertIsNone(reply)
        self.assertIn("no progress", err)
        self.assertIn("budget", err)

    def test_run_s2_uses_reconnect_path(self):
        # S2 网络错误应重连而非直接失败
        error = _FakeHttpxError("reset")
        error.__class__.__name__ = "ReadError"
        responses = iter([error, '{"script": "return df", "description": "demo"}'])

        def fake_chat_completion(db, **kwargs):
            outcome = next(responses)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome, {}, None

        with mock.patch.object(llm_client, "chat_completion", fake_chat_completion), _patch_sleep():
            script, err, _usage = llm_client.run_s2(
                db=None, config=mock.Mock(), brief="b", columns=[{"name": "c", "dtype": "float64"}],
                leakage_suspects=[], error_history=[], meta_hint=False, guidance=None,
            )
        self.assertIsNone(err)


def _conn_reset():
    error = _FakeHttpxError("reset")
    error.__class__.__name__ = "ReadError"
    while True:
        yield error


if __name__ == "__main__":
    unittest.main()
