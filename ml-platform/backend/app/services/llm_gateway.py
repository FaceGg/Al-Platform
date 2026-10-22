"""LLM gateway service (AutoML Agent plan, Tasks A1.2/A1.3).

Single access point for large-language-model calls: profile resolution,
SSRF-hardened URL validation (spec v0.9 §14.1/§17.1), masked reads,
connectivity probing, egress audit and env-variable bootstrap of the built-in
default profile. All consumer call sites must resolve endpoints through this
module — request-level endpoint overrides were removed (§14.1 收口).
"""

from __future__ import annotations

import ipaddress
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


class LLMProfileNotFoundError(LookupError):
    """Explicit profile_id does not resolve to an existing profile."""


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
        api_url=profile.api_url,
        api_key=api_key,
        model_id=profile.model_id,
        temperature=profile.temperature,
        timeout_seconds=profile.timeout_seconds or 60,
        profile_id=str(profile.id),
        profile_name=profile.name,
    )


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
) -> tuple[str | None, dict]:
    """Synchronous completion through the resolved config, with egress audit.

    Audit records destination metadata only — profile, purpose, model and
    payload size — never message content (spec v0.9 §17.1). Network failures
    propagate to the caller's existing error handling.
    """
    from app.services.platform_audit import PlatformAuditIntent, record_platform_event

    resolved_temperature = (
        temperature
        if temperature is not None
        else (config.temperature if config.temperature is not None else 0.7)
    )
    payload_chars = sum(len(message.get("content") or "") for message in messages)
    started = time.perf_counter()
    response = httpx.post(
        config.api_url,
        headers={"Authorization": f"Bearer {config.api_key}"} if config.api_key else {},
        json={
            "model": config.model_id,
            "messages": messages,
            "temperature": resolved_temperature,
            "max_tokens": max_tokens,
        },
        timeout=config.timeout_seconds,
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    data = response.json() if response.status_code == 200 else {}
    reply = (
        data.get("choices", [{}])[0].get("message", {}).get("content", "") or None
    )
    usage = data.get("usage") or {}
    changes = {
        "purpose": purpose,
        "model": config.model_id,
        "chars": payload_chars,
        "status_code": response.status_code,
        "latency_ms": latency_ms,
    }
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
) -> tuple[int, float, str]:
    """Single outbound probe call, kept trivially monkeypatchable."""
    started = time.perf_counter()
    response = httpx.post(
        api_url,
        json={
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        },
        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        timeout=timeout_seconds,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    return response.status_code, latency_ms, ""


def test_connectivity(db: Session, profile: LLMProfile) -> dict:
    validate_llm_api_url(profile.api_url)
    try:
        status_code, latency_ms, error = _post_chat(
            profile.api_url,
            profile_api_key(profile),
            profile.model_id,
            profile.timeout_seconds or 60,
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
