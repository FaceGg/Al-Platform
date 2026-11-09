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
    apply_reasoning_mapping,
    llm_base_url,
    list_upstream_models,
    normalize_llm_endpoint,
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

    def test_thinking_level_mapping(self):
        # anthropic → thinking.budget_tokens；responses → reasoning.effort；
        # chat completions 无标准参数不生效（不造假）
        _u, _h, a_body = _build_llm_request(_config("anthropic"), MESSAGES, 0.7, 1000, "high")
        self.assertEqual(a_body["thinking"], {"type": "enabled", "budget_tokens": 16384})
        _u, _h, r_body = _build_llm_request(_config("responses"), MESSAGES, 0.7, 1000, "low")
        self.assertEqual(r_body["reasoning"], {"effort": "low"})
        _u, _h, c_body = _build_llm_request(_config("openai_compatible"), MESSAGES, 0.7, 1000, "high")
        self.assertNotIn("thinking", c_body)
        self.assertNotIn("reasoning", c_body)


MULTIMODAL_MESSAGES = [
    {"role": "system", "content": "你是助手"},
    {"role": "user", "content": [
        {"type": "text", "text": "这张焊接图有什么问题？"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
    ]},
]


class TestMultimodalContentByFormat(unittest.TestCase):
    """附件图片（OpenAI content 数组）按 provider 映射：openai 原样、
    anthropic → image/base64 块、responses → input_image 块。"""

    def test_chat_completions_passthrough(self):
        _u, _h, body = _build_llm_request(_config("openai_compatible"), MULTIMODAL_MESSAGES, 0.7, 1000)
        self.assertEqual(body["messages"][1]["content"], MULTIMODAL_MESSAGES[1]["content"])

    def test_anthropic_maps_to_base64_image_block(self):
        _u, _h, body = _build_llm_request(_config("anthropic"), MULTIMODAL_MESSAGES, 0.7, 1000)
        content = body["messages"][0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "这张焊接图有什么问题？"})
        self.assertEqual(content[1], {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="},
        })

    def test_responses_maps_to_input_image_block(self):
        _u, _h, body = _build_llm_request(_config("responses"), MULTIMODAL_MESSAGES, 0.7, 1000)
        content = body["input"][1]["content"]
        self.assertEqual(content[0], {"type": "input_text", "text": "这张焊接图有什么问题？"})
        self.assertEqual(content[1], {
            "type": "input_image",
            "image_url": "data:image/png;base64,aGVsbG8=",
        })

    def test_anthropic_non_image_url_blocks_skipped(self):
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "hi"},
            {"type": "image_url", "image_url": {"url": "https://example.com/x.png"}},
        ]}]
        _u, _h, body = _build_llm_request(_config("anthropic"), messages, 0.7, 1000)
        self.assertEqual(body["messages"][0]["content"], [{"type": "text", "text": "hi"}])


class TestStreamParsingByFormat(unittest.TestCase):
    def test_chat_completions_delta(self):
        delta, usage, reasoning = _parse_llm_stream_event(
            "openai_compatible",
            {"choices": [{"delta": {"content": "hi"}}]},
        )
        self.assertEqual(delta, "hi")
        self.assertIsNone(usage)
        self.assertIsNone(reasoning)

    def test_chat_completions_reasoning_delta(self):
        delta, _usage, reasoning = _parse_llm_stream_event(
            "openai_compatible",
            {"choices": [{"delta": {"reasoning_content": "先分析数据分布…"}}]},
        )
        self.assertIsNone(delta)
        self.assertEqual(reasoning, "先分析数据分布…")
        delta2, _u2, reasoning2 = _parse_llm_stream_event(
            "openai_compatible",
            {"choices": [{"delta": {"reasoning": "alias"}}]},
        )
        self.assertEqual(reasoning2, "alias")
        self.assertIsNone(delta2)

    def test_anthropic_thinking_delta(self):
        _delta, _usage, reasoning = _parse_llm_stream_event(
            "anthropic",
            {"type": "content_block_delta", "delta": {"thinking": "hmm"}},
        )
        self.assertEqual(reasoning, "hmm")

    def test_responses_reasoning_summary(self):
        _delta, _usage, reasoning = _parse_llm_stream_event(
            "responses",
            {"type": "response.reasoning_summary_text.delta", "delta": "chain"},
        )
        self.assertEqual(reasoning, "chain")

    def test_responses_delta_and_usage(self):
        delta, _d0, _r = _parse_llm_stream_event(
            "responses", {"type": "response.output_text.delta", "delta": "yo"}
        )
        self.assertEqual(delta, "yo")
        _d, usage, _r2 = _parse_llm_stream_event(
            "responses",
            {"type": "response.completed", "response": {"usage": {"input_tokens": 3, "output_tokens": 5}}},
        )
        self.assertEqual(usage, {"prompt_tokens": 3, "completion_tokens": 5})

    def test_anthropic_delta_and_usage(self):
        delta, _d0, _r = _parse_llm_stream_event(
            "anthropic", {"type": "content_block_delta", "delta": {"text": "ok"}},
        )
        self.assertEqual(delta, "ok")
        _d, usage, _r2 = _parse_llm_stream_event(
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

    def test_list_models_falls_back_to_origin_models_on_404(self):
        """真机 DeepSeek：anthropic 兼容端点没有 /v1/models（404），
        原生 https://api.deepseek.com/models 存在——派生路径 404 回退源站根。"""
        response_404 = mock.Mock(status_code=404)
        response_ok = mock.Mock(status_code=200)
        response_ok.json.return_value = {"data": [{"id": "deepseek-chat"}]}
        with mock.patch("app.services.llm_gateway._HTTP_CLIENT") as client:
            client.get.side_effect = [response_404, response_ok]
            models = list_upstream_models(
                "https://api.deepseek.com/anthropic/v1/messages", "sk", "anthropic",
            )
        urls = [call[0][0] for call in client.get.call_args_list]
        self.assertEqual(urls[0], "https://api.deepseek.com/anthropic/v1/models")
        self.assertEqual(urls[1], "https://api.deepseek.com/models")
        self.assertEqual(models, ["deepseek-chat"])


class TestAnthropicProbeHeaders(unittest.TestCase):
    def test_probe_uses_anthropic_headers_for_anthropic_profile(self):
        """探测 anthropic 格式档案必须带 x-api-key + anthropic-version
        （此前 Bearer-only → 真机 DeepSeek anthropic 端点 404/401）。"""
        from app.services import llm_gateway

        profile = mock.Mock()
        profile.api_url = "https://api.deepseek.com/anthropic/v1/messages"
        profile.provider = "anthropic"
        profile.model_id = "deepseek-chat"
        profile.timeout_seconds = 15
        with mock.patch.object(llm_gateway, "profile_api_key", return_value="sk"), \
                mock.patch.object(llm_gateway, "_HTTP_CLIENT") as client:
            client.post.return_value.status_code = 200
            result = llm_gateway.test_connectivity(mock.Mock(), profile)
        headers = client.post.call_args[1]["headers"]
        self.assertEqual(headers["x-api-key"], "sk")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertNotIn("Authorization", headers)
        self.assertTrue(result["ok"])


class TestApplyReasoningMapping(unittest.TestCase):
    """「编辑模型配置」的推理参数映射：等级→请求参数求值（不执行任意代码）。"""

    MAPPING = (
        'reasoningLevel == "disabled"\n'
        '  ? {\n'
        '      "thinking": {\n'
        '        "type": "disabled"\n'
        '      }\n'
        '    }\n'
        '  : reasoningLevel == "low"\n'
        '  ? {\n'
        '      "thinking": {\n'
        '        "type": "enabled",\n'
        '        "budget_tokens": 4096\n'
        '      }\n'
        '    }\n'
        '  : {}'
    )

    def test_matching_level_returns_branch_params(self):
        disabled = apply_reasoning_mapping(self.MAPPING, "disabled")
        self.assertEqual(disabled, {"thinking": {"type": "disabled"}})
        low = apply_reasoning_mapping(self.MAPPING, "low")
        self.assertEqual(low["thinking"]["budget_tokens"], 4096)

    def test_unmatched_level_returns_empty_and_no_match_returns_none(self):
        self.assertEqual(apply_reasoning_mapping(self.MAPPING, "high"), {})
        # 未匹配等级走三元链兜底分支 → 空参数（不造假）；映射/等级缺失 → None
        self.assertEqual(apply_reasoning_mapping(self.MAPPING, "unknown-level"), {})
        self.assertIsNone(apply_reasoning_mapping(None, "low"))
        self.assertIsNone(apply_reasoning_mapping(self.MAPPING, None))

    def test_nested_ternary_inside_object_values(self):
        """供应商文档形态：对象值内嵌三元（kimi-k2.7 / mimo）。"""
        mapping = '{\n  "thinking": {\n    "type": reasoningLevel == "enabled" ? "enabled" : "disabled"\n  }\n}'
        self.assertEqual(
            apply_reasoning_mapping(mapping, "enabled"),
            {"thinking": {"type": "enabled"}},
        )
        self.assertEqual(
            apply_reasoning_mapping(mapping, "disabled"),
            {"thinking": {"type": "disabled"}},
        )

    def test_bare_level_identifier_as_value(self):
        """裸 reasoningLevel 作值（kimi-k3.1 output_config.effort）。"""
        mapping = '{\n  "output_config": {\n    "effort": reasoningLevel\n  }\n}'
        self.assertEqual(
            apply_reasoning_mapping(mapping, "high"),
            {"output_config": {"effort": "high"}},
        )

    def test_plain_json_mapping_without_conditions(self):
        """纯 JSON 映射（硅基流动 enable_thinking）——旧实现返回 {} 的形态。"""
        self.assertEqual(
            apply_reasoning_mapping('{"enable_thinking": true}', "enabled"),
            {"enable_thinking": True},
        )

    def test_zhipu_multi_key_embedded_ternary(self):
        """智谱多键内嵌三元 + 三元返回字符串。"""
        mapping = (
            '{\n'
            '  "thinking": {\n'
            '    "type": reasoningLevel == "disabled" || reasoningLevel == "none" ? "disabled" : "enabled"\n'
            '  },\n'
            '  "enable_thinking": reasoningLevel != "disabled" && reasoningLevel != "none",\n'
            '  "reasoning_effort": reasoningLevel == "disabled" ? "none" : reasoningLevel == "enabled" ? "high" : reasoningLevel\n'
            '}'
        )
        out = apply_reasoning_mapping(mapping, "low")
        self.assertEqual(out["thinking"], {"type": "enabled"})
        self.assertEqual(out["reasoning_effort"], "low")

    def test_unknown_identifier_rejected(self):
        """未知标识符拒绝（不执行任意代码）。"""
        self.assertEqual(apply_reasoning_mapping('{"x": someEvilIdentifier}', "low"), {})

    def test_top_level_ternary_with_else_branch_evaluates(self):
        """顶层三元链整段求值：无匹配分支走 else（火山方舟 none 形态）。"""
        mapping = (
            'reasoningLevel == "none"\n'
            '  ? {\n'
            '      "thinking": {\n'
            '        "type": "disabled"\n'
            '      }\n'
            '    }\n'
            '  : {\n'
            '      "output_config": {\n'
            '        "effort": reasoningLevel\n'
            '      }\n'
            '    }'
        )
        self.assertEqual(
            apply_reasoning_mapping(mapping, "none"),
            {"thinking": {"type": "disabled"}},
        )
        self.assertEqual(
            apply_reasoning_mapping(mapping, "high"),
            {"output_config": {"effort": "high"}},
        )

    def test_build_llm_request_applies_mapping_for_custom_level(self):
        """chat 传自定义等级（如 disabled）：映射分支参数合并进 anthropic 请求体。"""
        config = GatewayLLMConfig(
            api_url="https://api.deepseek.com/anthropic/v1/messages",
            api_key="sk",
            model_id="deepseek-chat",
            temperature=None,
            timeout_seconds=30,
            profile_id=None,
            profile_name="p",
            provider="anthropic",
            model_config={"reasoning_mapping": self.MAPPING},
        )
        url, headers, body = _build_llm_request(
            config,
            [{"role": "user", "content": "ping"}],
            None, 100,
            thinking_level="disabled",
        )
        self.assertEqual(body["thinking"], {"type": "disabled"})


class TestEndpointNormalization(unittest.TestCase):
    def test_llm_base_url_strips_known_suffixes(self):
        """存库/展示用裸 base：完整端点剥后缀，裸 base 与其它路径原样保留。"""
        cases = [
            ("https://api.deepseek.com/anthropic/v1/messages", "https://api.deepseek.com/anthropic"),
            ("https://api.example.com/v1/chat/completions", "https://api.example.com/v1"),
            ("https://api.example.com/v1/responses", "https://api.example.com/v1"),
            ("https://api.deepseek.com/anthropic/", "https://api.deepseek.com/anthropic"),
            ("https://gateway.example.com/custom/path", "https://gateway.example.com/custom/path"),
        ]
        for api_url, expected in cases:
            self.assertEqual(llm_base_url(api_url), expected)
    """裸 base 按格式补全端点（真机：DeepSeek 存 /anthropic/ → 探测/聊天 404）。"""

    def test_bare_bases_get_format_suffix(self):
        cases = [
            ("https://api.deepseek.com/anthropic/", "anthropic", "https://api.deepseek.com/anthropic/v1/messages"),
            ("https://api.deepseek.com/anthropic", "anthropic", "https://api.deepseek.com/anthropic/v1/messages"),
            ("https://api.deepseek.com/v1", "openai_compatible", "https://api.deepseek.com/v1/chat/completions"),
            ("https://api.example.com", "responses", "https://api.example.com/responses"),
        ]
        for api_url, provider, expected in cases:
            self.assertEqual(normalize_llm_endpoint(api_url, provider), expected)

    def test_complete_endpoints_unchanged(self):
        for api_url, provider in (
            ("https://api.deepseek.com/anthropic/v1/messages", "anthropic"),
            ("https://api.example.com/v1/chat/completions", "openai_compatible"),
            ("https://api.example.com/v1/responses", "responses"),
            # 换格式保护：旧完整端点不被二次加尾巴
            ("https://api.example.com/v1/chat/completions", "anthropic"),
        ):
            self.assertEqual(normalize_llm_endpoint(api_url, provider), api_url)

    def test_probe_normalizes_bare_base_url(self):
        """探测裸 base 档案：实际 POST 到补全后的 /v1/messages 端点。"""
        from app.services import llm_gateway

        profile = mock.Mock()
        profile.api_url = "https://api.deepseek.com/anthropic/"
        profile.provider = "anthropic"
        profile.model_id = "deepseek-chat"
        profile.timeout_seconds = 15
        with mock.patch.object(llm_gateway, "profile_api_key", return_value="sk"), \
                mock.patch.object(llm_gateway, "_HTTP_CLIENT") as client:
            client.post.return_value.status_code = 200
            llm_gateway.test_connectivity(mock.Mock(), profile)
        posted_url = client.post.call_args[0][0]
        self.assertEqual(posted_url, "https://api.deepseek.com/anthropic/v1/messages")


if __name__ == "__main__":
    unittest.main()
