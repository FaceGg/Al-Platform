"""LLM gateway service (AutoML Agent plan, Tasks A1.2/A1.3).

Single access point for large-language-model calls: profile resolution,
SSRF-hardened URL validation (spec v0.9 §14.1/§17.1), masked reads,
connectivity probing, egress audit and env-variable bootstrap of the built-in
default profile. All consumer call sites must resolve endpoints through this
module — request-level endpoint overrides were removed (§14.1 收口).
"""

from __future__ import annotations

import ipaddress
import json
import time
import urllib.parse
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models.llm_profile import LLMProfile
from app.services.llm_profile_crypto import (
    LLMCredentialError,
    decrypt_llm_api_key,
    encrypt_llm_api_key,
)

# 模块级共享 HTTP 客户端：连接池复用，避免每次调用重新建立 TCP/TLS。
# 每次请求仍带各自的超时参数（timeout=...），不改任何超时语义。
_HTTP_CLIENT = httpx.Client(
    limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
)


class LLMProfileNotFoundError(LookupError):
    """Explicit profile_id does not resolve to an existing profile."""


def llm_base_url(api_url: str) -> str:
    """剥掉已知协议后缀，存库/展示用裸 base（对齐 ZCode 模型设置习惯：
    Base URL 存 https://api.deepseek.com/anthropic，协议路径调用时内部拼接）。
    无已知后缀则原样返回（含去尾斜杠）。"""
    url = (api_url or "").strip()
    if not url:
        return url
    base = url.rstrip("/")
    for suffix in ("/v1/messages", "/chat/completions", "/responses"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def normalize_llm_endpoint(api_url: str, provider: str) -> str:
    """按 API 格式补全端点后缀（调用时内部拼接）：裸 base 与完整端点都接受，
    返回可直接 POST 的完整端点。已带任一已知后缀则原样返回（换格式时避免
    把旧完整端点二次加尾巴）。"""
    url = (api_url or "").strip()
    if not url:
        return url
    base = url.rstrip("/")
    suffixes = {
        "anthropic": "/v1/messages",
        "openai_compatible": "/chat/completions",
        "responses": "/responses",
    }
    if any(base.endswith(known) for known in suffixes.values()):
        return url
    suffix = suffixes.get(provider)
    if not suffix:
        return url
    return base + suffix


def _env_fallback_config() -> GatewayLLMConfig:
    return GatewayLLMConfig(
        api_url=settings.llm_api_url,
        api_key=settings.llm_api_key,
        model_id=settings.llm_model,
        temperature=None,
        timeout_seconds=60,
        profile_id=None,
        profile_name="env",
    )


@dataclass(frozen=True)
class GatewayLLMConfig:
    """Resolved endpoint configuration handed to consumers."""

    api_url: str
    api_key: str
    model_id: str
    temperature: float | None
    timeout_seconds: int
    profile_id: str | None
    profile_name: str
    # API 格式（openai_compatible=Chat Completions / responses / anthropic）；
    # 默认值保证既有构造点（测试/env fallback）行为不变。
    provider: str = "openai_compatible"
    # ZCode 风格模型配置（上下文窗口/最大输出/推理等级与映射等）；可空
    model_config: dict | None = None


def resolve_profile(
    db: Session, *, profile_id: str | None = None, purpose: str = "chat"
) -> GatewayLLMConfig:
    """Resolve a profile (explicit id → default → env fallback).

    The env fallback keeps deployments without any profile working; once the
    first profile exists, env settings no longer participate in resolution.
    """
    profile: LLMProfile | None = None
    if profile_id:
        try:
            pid = UUID(str(profile_id))
        except (TypeError, ValueError) as error:
            raise LLMProfileNotFoundError("LLM_PROFILE_NOT_FOUND") from error
        profile = db.get(LLMProfile, pid)
        if profile is None:
            raise LLMProfileNotFoundError("LLM_PROFILE_NOT_FOUND")
    else:
        profile = (
            db.query(LLMProfile).filter(LLMProfile.is_default.is_(True)).first()
        )
    if profile is None:
        return _env_fallback_config()
    try:
        api_key = profile_api_key(profile)
    except LLMCredentialError:
        # Profile keys are unreadable without the master key (LLM_MASTER_KEY
        # unset or rotated): degrade to env fallback instead of crashing every
        # consumer surface. Production startup validates the key separately.
        return _env_fallback_config()
    return GatewayLLMConfig(
        api_url=normalize_llm_endpoint(profile.api_url, profile.provider or "openai_compatible"),
        api_key=api_key,
        model_id=profile.model_id,
        temperature=profile.temperature,
        timeout_seconds=profile.timeout_seconds or 60,
        profile_id=str(profile.id),
        profile_name=profile.name,
        provider=profile.provider or "openai_compatible",
        model_config=getattr(profile, "model_config_json", None),
    )


def _build_llm_request(
    config, messages: list[dict], temperature: float, max_tokens: int,
    thinking_level: str | None = None,
) -> tuple[str, dict, dict]:
    """按 API 格式构造请求（url/headers/body）。三格式均走 SSE 流式。

    - openai_compatible：POST {url}/chat/completions（用户填完整端点）
    - responses：POST {url}/responses（OpenAI Responses 协议）
    - anthropic：POST {url}/v1/messages（x-api-key + anthropic-version）
    thinking_level 按格式映射：anthropic → thinking.budget_tokens；responses →
    reasoning.effort；chat completions 无标准参数则忽略（不造假）。模型配置
    （model_config_json.reasoning_mapping）存在时优先按映射表达式求值并合并
    进请求体——映射来自「编辑模型配置」弹窗，与模型能力绑定。
    """
    provider = config.provider or "openai_compatible"
    model_cfg = getattr(config, "model_config", None) or {}
    reasoning_mapping = model_cfg.get("reasoning_mapping")
    mapped_params = (
        apply_reasoning_mapping(reasoning_mapping, thinking_level)
        if thinking_level else None
    )
    if provider == "anthropic":
        system_text = "\n\n".join(
            message.get("content") or ""
            for message in messages
            if message.get("role") == "system"
        )
        chat_messages = [
            {"role": message["role"], "content": message.get("content") or ""}
            for message in messages
            if message.get("role") != "system"
        ]
        headers = {"anthropic-version": "2023-06-01"}
        if config.api_key:
            headers["x-api-key"] = config.api_key
        body = {
            "model": config.model_id,
            "messages": chat_messages,
            "max_tokens": max_tokens or 4096,  # Anthropic 必填
            "stream": True,
        }
        if system_text:
            body["system"] = system_text
        if temperature is not None:
            body["temperature"] = temperature
        if thinking_level in ("low", "medium", "high"):
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": {"low": 4096, "medium": 8192, "high": 16384}[thinking_level],
            }
        if mapped_params:
            body.update(mapped_params)
        return config.api_url, headers, body
    if provider == "responses":
        headers = (
            {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
        )
        body = {
            "model": config.model_id,
            "input": [
                {"role": message.get("role") or "user", "content": message.get("content") or ""}
                for message in messages
            ],
            "stream": True,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens:
            body["max_output_tokens"] = max_tokens
        if thinking_level in ("low", "medium", "high"):
            body["reasoning"] = {"effort": thinking_level}
        if mapped_params:
            body.update(mapped_params)
        return config.api_url, headers, body
    # 默认：Chat Completions（存量路径行为不变）
    headers = (
        {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    )
    body = {
        "model": config.model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    return config.api_url, headers, body


def _parse_llm_stream_event(provider: str, event: dict) -> tuple[str | None, dict | None]:
    """从 SSE 事件里解出 (文本增量, usage)。三格式的增量位置不同：
    - chat completions: choices[0].delta.content
    - responses: type=response.output_text.delta → delta
    - anthropic: type=content_block_delta → delta.text
    """
    if provider == "anthropic":
        if event.get("type") == "content_block_delta":
            delta = (event.get("delta") or {}).get("text")
            return (delta, None) if delta else (None, None)
        if event.get("type") == "message_delta":
            usage_event = event.get("usage") or {}
            return None, {
                "prompt_tokens": usage_event.get("input_tokens"),
                "completion_tokens": usage_event.get("output_tokens"),
            }
        return None, None
    if provider == "responses":
        if event.get("type") == "response.output_text.delta":
            delta = event.get("delta")
            return (delta, None) if delta else (None, None)
        if event.get("type") == "response.completed":
            response = event.get("response") or {}
            usage_event = response.get("usage") or {}
            return None, {
                "prompt_tokens": usage_event.get("input_tokens"),
                "completion_tokens": usage_event.get("output_tokens"),
            }
        return None, None
    # Chat Completions
    choices = event.get("choices") or []
    delta = None
    if choices:
        delta = (choices[0].get("delta") or {}).get("content")
    return (delta, event.get("usage")) if (delta or event.get("usage")) else (None, None)


def _provider_headers(provider: str, api_key: str | None) -> dict[str, str]:
    """按 API 格式选认证头：anthropic 用 x-api-key + anthropic-version
    （真机 DeepSeek anthropic 端点对 Bearer-only 探测回 404/401），其余 Bearer。"""
    if not api_key:
        return {}
    if provider == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {api_key}"}


def apply_reasoning_mapping(mapping: str | None, level: str | None) -> dict | None:
    """按映射表达式求出该推理等级的请求参数（不执行任意代码）。

    表达式是平台/前端生成的三元链：``reasoningLevel == "low" ? {json} :
    reasoningLevel == "high" ? {json} : {json}``。求值 = 定位等值比较中
    等级名匹配的分支，取其后第一个配平的 JSON 对象；无匹配或解析失败
    返回 None（调用方忽略，不造假参数）。"""
    if not mapping or not level:
        return None
    level_variants = (level, level.lower(), level.upper())
    for variant in level_variants:
        marker = f'reasoningLevel == "{variant}"'
        position = mapping.find(marker)
        while position != -1:
            question = mapping.find("?", position + len(marker))
            if question == -1:
                break
            open_brace = mapping.find("{", question + 1)
            if open_brace == -1:
                break
            depth = 0
            end = open_brace
            in_string = False
            escape = False
            for index in range(open_brace, len(mapping)):
                char = mapping[index]
                if escape:
                    escape = False
                elif char == "\\" and in_string:
                    escape = True
                elif char == '"':
                    in_string = not in_string
                elif not in_string:
                    if char == "{":
                        depth += 1
                    elif char == "}":
                        depth -= 1
                        if depth == 0:
                            end = index + 1
                            break
            import json as _json

            try:
                return _json.loads(mapping[open_brace:end])
            except ValueError:
                position = mapping.find(marker, end)
                continue
    # 有映射但等级无匹配分支：按三元链兜底语义返回空参数（不造假）
    return {}


def list_upstream_models(
    api_url: str, api_key: str | None, provider: str
) -> list[str]:
    """拉上游模型列表（「获取」按钮的后端代理）。

    由聊天端点推导列表端点（/chat/completions→/models、/responses→/models、
    /v1/messages→/v1/models）。URL 先过 validate_llm_api_url 的 SSRF 校验
    （https-only、拒私网/环回）。仅 http/https。"""
    validate_llm_api_url(api_url)
    normalized = normalize_llm_endpoint(api_url, provider)
    stripped = normalized.rstrip("/")
    candidates: list[str] = []
    for suffix, list_path in (
        ("/chat/completions", "/models"),
        ("/responses", "/models"),
        ("/messages", "/models"),
    ):
        if stripped.endswith(suffix):
            candidates.append(stripped[: -len(suffix)] + list_path)
            break
    else:
        candidates.append(stripped + "/models")
    # 派生路径 404 时回退源站根 /models：部分供应商的兼容端点不含模型目录
    # （真机 DeepSeek：/anthropic/v1/models 404，原生 /models 存在）
    parts = api_url.split("/", 3)
    if len(parts) >= 3:
        origin = parts[0] + "//" + parts[2]
        if origin + "/models" not in candidates:
            candidates.append(origin + "/models")
    headers = _provider_headers(provider, api_key)
    response: httpx.Response | None = None
    for list_url in candidates:
        response = _HTTP_CLIENT.get(list_url, headers=headers, timeout=15)
        if response.status_code != 404:
            break
    if response is None:
        return []
    response.raise_for_status()
    data = response.json()
    if provider == "anthropic":
        items = data.get("data") or []
        return [str(item.get("id")) for item in items if item.get("id")]
    # OpenAI 系（chat completions / responses 同构）：{data: [{id}]}
    items = data.get("data") or []
    return [str(item.get("id")) for item in items if item.get("id")]


def chat_completion(
    db: Session,
    *,
    config: GatewayLLMConfig,
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = 2000,
    purpose: str = "chat",
    actor=None,
    request=None,
    timeout_floor: float | None = None,
    thinking_level: str | None = None,
) -> tuple[str | None, dict]:
    """Synchronous completion through the resolved config, with egress audit.

    Audit records destination metadata only — profile, purpose, model and
    payload size — never message content (spec v0.9 §17.1). Network failures
    propagate to the caller's existing error handling.

    ``timeout_floor`` raises the effective HTTP timeout for callers whose
    completions legitimately run long (the agent's S1/S2/S4 stages emit
    multi-thousand-token JSON and routinely exceed the 60s profile default
    tuned for chat).
    """
    from app.services.platform_audit import PlatformAuditIntent, record_platform_event

    resolved_temperature = (
        temperature
        if temperature is not None
        else (config.temperature if config.temperature is not None else 0.7)
    )
    effective_timeout = (
        max(config.timeout_seconds, timeout_floor)
        if timeout_floor is not None
        else config.timeout_seconds
    )
    payload_chars = sum(len(message.get("content") or "") for message in messages)
    started = time.perf_counter()
    # 流式接收（SSE）：非流式长生成在静默等待整个响应期会被网络中间设备
    # 按"空闲连接"掐断（实测 Errno 104 Connection reset，60-200s 静默窗口，
    # 短请求测试调用则完全正常——极具迷惑性）。流式让字节持续回流规避
    # 空闲超时；对调用方语义不变（仍是完整文本 + usage）。
    # 三种 API 格式共用同一流式框架：构造器/解析器按 provider 分派
    # （openai_compatible=Chat Completions / responses / anthropic）。
    url, headers, body = _build_llm_request(
        config, messages, resolved_temperature, max_tokens, thinking_level
    )
    reply_parts: list[str] = []
    usage: dict = {}
    status_code: int = 0
    try:
        with _HTTP_CLIENT.stream(
            "POST",
            url,
            headers=headers,
            json=body,
            timeout=effective_timeout,
        ) as response:
            status_code = response.status_code
            if status_code != 200:
                error_body = response.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(error_body)
                except ValueError:
                    data = {"raw": error_body[:500]}
            else:
                for line in response.iter_lines():
                    if not line.startswith("data:") and not line.startswith("event:"):
                        continue
                    if line.startswith("event:"):
                        continue
                    chunk_text = line[len("data:"):].strip()
                    if not chunk_text or chunk_text == "[DONE]":
                        continue
                    try:
                        event = json.loads(chunk_text)
                    except ValueError:
                        continue
                    delta, event_usage = _parse_llm_stream_event(
                        config.provider, event
                    )
                    if delta:
                        reply_parts.append(delta)
                    if event_usage:
                        usage = event_usage
    except httpx.HTTPError:
        # 传输层异常统一归一为非 200 形态，走下方既有的失败审计路径
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        changes = {
            "purpose": purpose,
            "model": config.model_id,
            "chars": payload_chars,
            "status_code": 0,
            "latency_ms": latency_ms,
        }
        if config.profile_id:
            changes["profile"] = config.profile_name
            if request is None:
                request = SimpleNamespace(state=SimpleNamespace(request_id=None), client=None)
            try:
                record_platform_event(
                    db,
                    actor=actor,
                    request=request,
                    intent=PlatformAuditIntent(
                        action="llm_gateway.egress",
                        resource_type="llm_profile",
                        resource_id=config.profile_id,
                        changes=changes,
                    ),
                    result="failed",
                    error_code="LLM_TRANSPORT_ERROR",
                )
            except Exception:  # noqa: BLE001
                pass
        raise
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    if status_code == 200:
        data = {
            "choices": [{"message": {"content": "".join(reply_parts)}}],
            "usage": usage,
        }
    reply = (
        data.get("choices", [{}])[0].get("message", {}).get("content", "") or None
    )
    changes = {
        "purpose": purpose,
        "model": config.model_id,
        "chars": payload_chars,
        "status_code": status_code,
        "latency_ms": latency_ms,
    }
    # tokens 用量随审计落库（使用统计页的数据源）。三格式 usage 已归一为
    # prompt_tokens/completion_tokens；上游未回 usage（部分兼容端点）则缺省。
    if usage:
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if prompt_tokens is not None or completion_tokens is not None:
            changes["prompt_tokens"] = int(prompt_tokens or 0)
            changes["completion_tokens"] = int(completion_tokens or 0)
            changes["total_tokens"] = (
                int(prompt_tokens or 0) + int(completion_tokens or 0)
            )
    if config.profile_id:
        changes["profile"] = config.profile_name
        if request is None:
            # Non-HTTP callers (agent runner, scripts): synthesize the minimal
            # request shape audit_request_context reads.
            request = SimpleNamespace(state=SimpleNamespace(request_id=None), client=None)
        try:
            record_platform_event(
                db,
                actor=actor,
                request=request,
                intent=PlatformAuditIntent(
                    action="llm_gateway.egress",
                    resource_type="llm_profile",
                    resource_id=config.profile_id,
                    changes=changes,
                ),
                result="success" if reply else "failed",
                error_code=None if reply else "LLM_EMPTY_COMPLETION",
            )
        except Exception:  # noqa: BLE001 - audit must not break the answer path
            pass
    return reply, usage


class LLMApiUrlError(ValueError):
    """Raised when a profile URL fails the egress hardening rules."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_llm_api_url(url: str) -> str:
    """Enforce spec v0.9 §14.1: https only, no loopback/private/metadata hosts.

    The connectivity probe makes server-side requests to this URL, so it is a
    ready-made SSRF vector — validation happens before any outbound call.
    """
    parsed = urllib.parse.urlsplit(url or "")
    if parsed.scheme != "https":
        raise LLMApiUrlError("LLM_API_URL_REQUIRES_HTTPS")
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        raise LLMApiUrlError("LLM_API_URL_MISSING_HOST")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise LLMApiUrlError("LLM_API_URL_PRIVATE_HOST")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return url
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_reserved
    ):
        raise LLMApiUrlError("LLM_API_URL_PRIVATE_HOST")
    return url


def mask_llm_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    return "***" + api_key[-4:]


def profile_api_key(profile: LLMProfile) -> str:
    return decrypt_llm_api_key(profile.api_key_encrypted, settings.llm_master_key)


def _post_chat(
    api_url: str,
    api_key: str,
    model_id: str,
    timeout_seconds: int,
    provider: str = "openai_compatible",
) -> tuple[int, float, str]:
    """Single outbound probe call, kept trivially monkeypatchable."""
    started = time.perf_counter()
    response = _HTTP_CLIENT.post(
        api_url,
        json={
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        },
        headers=_provider_headers(provider, api_key),
        timeout=timeout_seconds,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    return response.status_code, latency_ms, ""


def test_connectivity(db: Session, profile: LLMProfile) -> dict:
    validate_llm_api_url(normalize_llm_endpoint(profile.api_url, profile.provider or "openai_compatible"))
    try:
        status_code, latency_ms, error = _post_chat(
            normalize_llm_endpoint(profile.api_url, profile.provider or "openai_compatible"),
            profile_api_key(profile),
            profile.model_id,
            profile.timeout_seconds or 60,
            provider=profile.provider,
        )
    except httpx.HTTPError as error:
        return {"ok": False, "status_code": None, "latency_ms": None, "error": type(error).__name__}
    return {
        "ok": 200 <= status_code < 300,
        "status_code": status_code,
        "latency_ms": round(latency_ms, 1),
        "error": error or None,
    }


def bootstrap_default_llm_profile(session_factory: sessionmaker) -> bool:
    """Migrate legacy ``llm_api_url/key/model`` env settings into a profile.

    Idempotent: runs only when no profile exists. Operator-configured env URLs
    are inserted without the https/private validation — they are deployment
    settings, not user input — and always create a single default profile.
    """
    with session_factory() as db:
        if db.query(LLMProfile).count():
            return False
        api_url = (settings.llm_api_url or "").strip()
        api_key = (settings.llm_api_key or "").strip()
        model_id = (settings.llm_model or "").strip()
        if not api_url and not api_key:
            return False
        profile = LLMProfile(
            name="内置默认档案",
            provider="openai_compatible",
            api_url=api_url or "https://api.openai.com/v1/chat/completions",
            api_key_encrypted=(
                encrypt_llm_api_key(api_key, settings.llm_master_key) if api_key else None
            ),
            model_id=model_id or "gpt-3.5-turbo",
            is_default=True,
            deployment="cloud",
            purpose_tags=["chat", "agent"],
        )
        db.add(profile)
        try:
            db.commit()
        except Exception:
            # Multi-worker startup race on the unique profile name: another
            # worker won the bootstrap — treat as "already bootstrapped".
            db.rollback()
            return False
        return True
