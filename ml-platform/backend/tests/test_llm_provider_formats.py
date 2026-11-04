"""LLM 网关三种 API 格式（Chat Completions / Responses / Anthropic）合同测试。

- 构造器：URL/headers/body 按格式分派（Anthropic 用 x-api-key+system 提取+
  max_tokens 必填；Responses 用 input+max_output_tokens）
- 流解析：三种 SSE 增量/usage 形态各自解出
- list_upstream_models：端点推导（/chat/completions→/models、/responses→
  /models、/v1/messages→/v1/models）+ SSRF（http/私网拒绝）
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

from app.services.llm_gateway import (  # noqa: E402
    GatewayLLMConfig,
    LLMApiUrlError,
    _build_llm_request,
    _parse_llm_stream_event,
    list_upstream_models,
)

MESSAGES = [
    {"role": "system", "content": "你是助手"},
    {"role": "user", "content": "你好"},
]


def _config(provider: str) -> GatewayLLMConfig:
    return GatewayLLMConfig(
        api_url="https://api.example.com/v1/x",
        api_key="sk-test",
        model_id="m1",
        temperature=None,
        timeout_seconds=60,
        profile_id=None,
        profile_name="t",
        provider=provider,
    )


class TestBuildRequestByFormat(unittest.TestCase):
    def test_chat_completions_shape(self):
        url, headers, body = _build_llm_request(_config("openai_compatible"), MESSAGES, 0.7, 1000)
        self.assertEqual(headers, {"Authorization": "Bearer sk-test"})
        self.assertEqual(body["messages"], MESSAGES)
        self.assertEqual(body["max_tokens"], 1000)
        self.assertTrue(body["stream"])

    def test_responses_shape(self):
        _url, headers, body = _build_llm_request(_config("responses"), MESSAGES, 0.7, 1000)
        self.assertEqual(headers, {"Authorization": "Bearer sk-test"})
        self.assertEqual(body["input"][0]["role"], "system")
        self.assertEqual(body["max_output_tokens"], 1000)
        self.assertNotIn("messages", body)

    def test_anthropic_shape(self):
        _url, headers, body = _build_llm_request(_config("anthropic"), MESSAGES, 0.7, 1000)
        self.assertEqual(headers["x-api-key"], "sk-test")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        # system 单独提出，messages 只剩对话
        self.assertEqual(body["system"], "你是助手")
        self.assertEqual(len(body["messages"]), 1)
        self.assertGreaterEqual(body["max_tokens"], 1)  # Anthropic 必填


class TestStreamParsingByFormat(unittest.TestCase):
    def test_chat_completions_delta(self):
        delta, usage = _parse_llm_stream_event(
            "openai_compatible",
            {"choices": [{"delta": {"content": "hi"}}]},
        )
        self.assertEqual(delta, "hi")
        self.assertIsNone(usage)

    def test_responses_delta_and_usage(self):
        delta, _ = _parse_llm_stream_event(
            "responses", {"type": "response.output_text.delta", "delta": "yo"}
        )
        self.assertEqual(delta, "yo")
        _d, usage = _parse_llm_stream_event(
            "responses",
            {"type": "response.completed", "response": {"usage": {"input_tokens": 3, "output_tokens": 5}}},
        )
        self.assertEqual(usage, {"prompt_tokens": 3, "completion_tokens": 5})

    def test_anthropic_delta_and_usage(self):
        delta, _ = _parse_llm_stream_event(
            "anthropic",
            {"type": "content_block_delta", "delta": {"text": "ok"}},
        )
        self.assertEqual(delta, "ok")
        _d, usage = _parse_llm_stream_event(
            "anthropic",
            {"type": "message_delta", "usage": {"input_tokens": 2, "output_tokens": 4}},
        )
        self.assertEqual(usage, {"prompt_tokens": 2, "completion_tokens": 4})


class TestListUpstreamModels(unittest.TestCase):
    def test_endpoint_derivation(self):
        cases = [
            ("https://api.example.com/v1/chat/completions", "openai_compatible", "https://api.example.com/v1/models"),
            ("https://api.example.com/v1/responses", "responses", "https://api.example.com/v1/models"),
            ("https://api.anthropic.com/v1/messages", "anthropic", "https://api.anthropic.com/v1/models"),
        ]
        for api_url, provider, expected in cases:
            with mock.patch("app.services.llm_gateway._HTTP_CLIENT") as client:
                client.get.return_value.json.return_value = {"data": [{"id": "m-1"}]}
                models = list_upstream_models(api_url, "sk", provider)
                client.get.assert_called_once()
                self.assertEqual(client.get.call_args[0][0], expected)
                self.assertEqual(models, ["m-1"])

    def test_anthropic_headers(self):
        with mock.patch("app.services.llm_gateway._HTTP_CLIENT") as client:
            client.get.return_value.json.return_value = {"data": [{"id": "claude-1"}]}
            list_upstream_models("https://api.anthropic.com/v1/messages", "sk", "anthropic")
            headers = client.get.call_args[1]["headers"]
            self.assertEqual(headers["x-api-key"], "sk")

    def test_ssrf_rejected(self):
        # 仅 http/https 且拒私网/环回（validate_llm_api_url 合同）
        with self.assertRaises(LLMApiUrlError):
            list_upstream_models("http://api.example.com/v1/chat/completions", "sk", "openai_compatible")
        with self.assertRaises(LLMApiUrlError):
            list_upstream_models("https://127.0.0.1/v1/chat/completions", "sk", "openai_compatible")
        with self.assertRaises(LLMApiUrlError):
            list_upstream_models("https://10.0.0.5/v1/chat/completions", "sk", "openai_compatible")


if __name__ == "__main__":
    unittest.main()
