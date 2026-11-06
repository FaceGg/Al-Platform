"""LLMProfile registry API (AutoML Agent plan, Task A1.2).

Writes are system-admin-only (spec v0.9 §14.1); reads are authenticated but
return masked keys only. Every create/update/delete/test is platform-audited.
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.users import get_current_admin
from app.config import settings
from app.database import get_db
from app.models.llm_profile import LLMProfile
from app.models.user import User
from app.schemas.llm_profile import (
    LLMModelListRequest,
    LLMProfileConnectivity,
    LLMProfileCreate,
    LLMProfileOut,
    LLMProfileUpdate,
)
from app.services.llm_gateway import (
    LLMApiUrlError,
    list_upstream_models,
    llm_base_url,
    mask_llm_api_key,
    profile_api_key,
    test_connectivity,
)
from app.services.llm_profile_crypto import (
    LLMCredentialError,
    encrypt_llm_api_key,
)
from app.services.platform_audit import (
    PlatformAuditIntent,
    record_failed_platform_event,
    record_platform_event,
)

router = APIRouter(prefix="/api/llm-profiles", tags=["llm-profiles"])


def _out(db: Session, profile: LLMProfile) -> LLMProfileOut:
    try:
        masked = mask_llm_api_key(profile_api_key(profile))
    except LLMCredentialError:
        masked = None
    return LLMProfileOut(
        id=profile.id,
        name=profile.name,
        provider=profile.provider,
        api_url=profile.api_url,
        model_id=profile.model_id,
        temperature=profile.temperature,
        max_tokens=profile.max_tokens,
        timeout_seconds=profile.timeout_seconds,
        purpose_tags=profile.purpose_tags or [],
        deployment=profile.deployment,
        is_default=profile.is_default,
        api_key_masked=masked,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _master_key() -> SecretStr:
    key = settings.llm_master_key
    if key is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "LLM_MASTER_KEY_NOT_CONFIGURED"},
        )
    return key


def _get_profile(db: Session, profile_id: UUID) -> LLMProfile:
    profile = db.get(LLMProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail={"code": "LLM_PROFILE_NOT_FOUND"})
    return profile


def _unset_other_defaults(db: Session, keep_id: UUID) -> None:
    db.query(LLMProfile).filter(
        LLMProfile.is_default.is_(True), LLMProfile.id != keep_id
    ).update({LLMProfile.is_default: False}, synchronize_session=False)


@router.get("", response_model=list[LLMProfileOut])
def list_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return [_out(db, profile) for profile in db.query(LLMProfile).order_by(LLMProfile.name)]


@router.get("/usage-stats")
def usage_stats(
    days: int = 30,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Tokens 使用统计（系统管理页数据源）。

    注意：必须注册在 GET /{profile_id} 之前，否则 /usage-stats 被当作
    UUID 解析返回 422。聚合 llm_gateway.egress 审计事件：汇总（调用/
    失败/tokens/延迟）、按天趋势、按模型、按用途。tokens 字段自统计
    功能上线起记录——此前事件无 tokens，仅计入调用/延迟。
    重置基线（llm_usage_reset_at）之前的事件不计入——审计记录保留，
    统计口径从基线重新开始。"""
    from datetime import timedelta

    from app.models.platform_audit import PlatformAuditEvent
    from app.models.platform_option import get_option
    from app.tasks.time_utils import utcnow

    days = min(max(days, 1), 365)
    since = utcnow() - timedelta(days=days)
    reset_at = get_option(db, "llm_usage_reset_at")
    if reset_at:
        # 基线晚于窗口起点时收窄窗口（重置后历史事件不再计入）
        from datetime import datetime as _dt

        try:
            reset_dt = _dt.fromisoformat(str(reset_at))
            if reset_dt.tzinfo is None:
                reset_dt = reset_dt.replace(tzinfo=since.tzinfo)
            if reset_dt > since:
                since = reset_dt
        except ValueError:
            pass
    events = (
        db.query(PlatformAuditEvent)
        .filter(
            PlatformAuditEvent.action == "llm_gateway.egress",
            PlatformAuditEvent.created_at >= since,
        )
        .order_by(PlatformAuditEvent.created_at.asc())
        .all()
    )

    total_calls = len(events)
    failed_calls = sum(1 for event in events if event.result != "success")
    prompt_total = completion_total = 0
    latencies: list[float] = []
    by_day: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    by_purpose: dict[str, dict] = {}
    for event in events:
        changes = event.changes if isinstance(event.changes, dict) else {}

        def _tokens(key: str) -> int:
            # 历史事件可能带非数字值（脱敏旧规则写入的 [REDACTED] 等），
            # 按无用量计，不让统计页崩
            try:
                return int(changes.get(key) or 0)
            except (TypeError, ValueError):
                return 0

        prompt_tokens = _tokens("prompt_tokens")
        completion_tokens = _tokens("completion_tokens")
        prompt_total += prompt_tokens
        completion_total += completion_tokens
        if changes.get("latency_ms") is not None:
            try:
                latencies.append(float(changes["latency_ms"]))
            except (TypeError, ValueError):
                pass
        day = (event.created_at or since).strftime("%Y-%m-%d")
        model = str(changes.get("model") or "-")
        purpose = str(changes.get("purpose") or "-")
        failed = event.result != "success"
        for bucket, key in ((by_day, day), (by_model, model), (by_purpose, purpose)):
            entry = bucket.setdefault(
                key, {"calls": 0, "failed": 0, "prompt_tokens": 0, "completion_tokens": 0}
            )
            entry["calls"] += 1
            entry["failed"] += 1 if failed else 0
            entry["prompt_tokens"] += prompt_tokens
            entry["completion_tokens"] += completion_tokens

    return {
        "days": days,
        "since": since.isoformat(),
        "summary": {
            "total_calls": total_calls,
            "failed_calls": failed_calls,
            "prompt_tokens": prompt_total,
            "completion_tokens": completion_total,
            "total_tokens": prompt_total + completion_total,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        },
        "by_day": [
            {"date": key, **value} for key, value in sorted(by_day.items())
        ],
        "by_model": sorted(
            ({"model": key, **value} for key, value in by_model.items()),
            key=lambda item: -(item["prompt_tokens"] + item["completion_tokens"]),
        ),
        "by_purpose": sorted(
            ({"purpose": key, **value} for key, value in by_purpose.items()),
            key=lambda item: -item["calls"],
        ),
    }


@router.post("", response_model=LLMProfileOut, status_code=201)
def create_profile(
    payload: LLMProfileCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    try:
        profile_id = uuid4()
        # 存库用裸 base（对齐供应商文档/ZCode 惯例）：协议路径由调用侧
        # normalize_llm_endpoint 内部拼接（探测/聊天/拉模型均已接入）
        normalized_url = llm_base_url(payload.api_url)
        profile = LLMProfile(
            id=profile_id,
            name=payload.name,
            provider=payload.provider,
            api_url=normalized_url,
            api_key_encrypted=(
                encrypt_llm_api_key(payload.api_key, _master_key())
                if payload.api_key
                else None
            ),
            model_id=payload.model_id,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            timeout_seconds=payload.timeout_seconds,
            purpose_tags=payload.purpose_tags,
            deployment=payload.deployment,
            is_default=payload.is_default,
            created_by=admin.id,
        )
        # Clear prior defaults before INSERT: the partial unique index would
        # otherwise reject the flush while two defaults coexist.
        if payload.is_default:
            _unset_other_defaults(db, profile_id)
        db.add(profile)
        db.flush()
        record_platform_event(
            db,
            actor=admin,
            request=request,
            intent=PlatformAuditIntent(
                action="llm_profile.create",
                resource_type="llm_profile",
                resource_id=str(profile.id),
                changes={"name": profile.name, "deployment": profile.deployment},
            ),
            result="success",
        )
        db.commit()
    except IntegrityError as error:
        record_failed_platform_event(
            db,
            actor=admin,
            request=request,
            intent=PlatformAuditIntent(
                action="llm_profile.create",
                resource_type="llm_profile",
                changes={"name": payload.name},
            ),
            error_code="LLM_PROFILE_NAME_CONFLICT",
        )
        raise HTTPException(
            status_code=409, detail={"code": "LLM_PROFILE_NAME_CONFLICT"}
        ) from error
    db.refresh(profile)
    return _out(db, profile)


@router.get("/{profile_id}", response_model=LLMProfileOut)
def get_profile(
    profile_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _out(db, _get_profile(db, profile_id))


@router.patch("/{profile_id}", response_model=LLMProfileOut)
def update_profile(
    profile_id: UUID,
    payload: LLMProfileUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    profile = _get_profile(db, profile_id)
    changes: dict[str, object] = {}
    for field in (
        "name",
        "provider",
        "api_url",
        "model_id",
        "temperature",
        "max_tokens",
        "timeout_seconds",
        "purpose_tags",
        "deployment",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(profile, field, value)
            changes[field] = value
    # 存库用裸 base：provider 或 api_url 变更后剥掉协议后缀（调用侧内部拼接）
    if "provider" in changes or "api_url" in changes:
        profile.api_url = llm_base_url(profile.api_url)
        changes["api_url"] = profile.api_url
    if payload.api_key:
        profile.api_key_encrypted = encrypt_llm_api_key(payload.api_key, _master_key())
        changes["api_key"] = "rotated"
    if payload.is_default:
        _unset_other_defaults(db, profile.id)
        profile.is_default = True
        changes["is_default"] = True
    try:
        record_platform_event(
            db,
            actor=admin,
            request=request,
            intent=PlatformAuditIntent(
                action="llm_profile.update",
                resource_type="llm_profile",
                resource_id=str(profile.id),
                changes=changes,
            ),
            result="success",
        )
        db.commit()
    except IntegrityError as error:
        record_failed_platform_event(
            db,
            actor=admin,
            request=request,
            intent=PlatformAuditIntent(
                action="llm_profile.update",
                resource_type="llm_profile",
                resource_id=str(profile.id),
                changes=changes,
            ),
            error_code="LLM_PROFILE_NAME_CONFLICT",
        )
        raise HTTPException(
            status_code=409, detail={"code": "LLM_PROFILE_NAME_CONFLICT"}
        ) from error
    db.refresh(profile)
    return _out(db, profile)


@router.delete("/{profile_id}", status_code=204)
def delete_profile(
    profile_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    profile = _get_profile(db, profile_id)
    record_platform_event(
        db,
        actor=admin,
        request=request,
        intent=PlatformAuditIntent(
            action="llm_profile.delete",
            resource_type="llm_profile",
            resource_id=str(profile.id),
            changes={"name": profile.name},
        ),
        result="success",
    )
    db.delete(profile)
    db.commit()


@router.post("/usage-stats/reset")
def reset_usage_stats(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """重置 Tokens 用量统计：设置统计基线为当前时刻。

    审计事件是安全记录不删除；聚合从基线重新开始（历史不计入）。
    从基线起重新统计 tokens 用量。"""
    from app.models.platform_option import set_option
    from app.tasks.time_utils import utcnow

    reset_at = utcnow().isoformat()
    set_option(db, "llm_usage_reset_at", reset_at)
    record_platform_event(
        db,
        actor=admin,
        request=request,
        intent=PlatformAuditIntent(
            action="llm_usage.reset",
            resource_type="platform_option",
            resource_id="llm_usage_reset_at",
            changes={"reset": True},
        ),
        result="success",
    )
    db.commit()
    return {"reset_at": reset_at}


@router.post("/list-models")
def list_models(
    payload: LLMModelListRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """「获取模型列表」代理：用表单 URL/Key 拉上游模型目录。

    浏览器直连上游会跨域且暴露 Key 策略，必须走后端代理；URL 过
    validate_llm_api_url（https-only、拒私网/环回）。编辑档案时 Key
    留空 → profile_id 复用已存 Key。"""
    api_key = payload.api_key
    if not api_key and payload.profile_id is not None:
        stored = db.get(LLMProfile, payload.profile_id)
        if stored is not None:
            try:
                api_key = profile_api_key(stored)
            except LLMCredentialError:
                api_key = None
    try:
        models = list_upstream_models(payload.api_url, api_key, payload.provider)
    except LLMApiUrlError as error:
        raise HTTPException(status_code=422, detail={"code": error.reason}) from error
    except Exception as error:  # noqa: BLE001 - 上游错误原样透传给表单提示
        message = str(error)[:300]
        record_failed_platform_event(
            db,
            actor=admin,
            request=request,
            intent=PlatformAuditIntent(
                action="llm_profile.list_models",
                resource_type="llm_profile",
                changes={"provider": payload.provider},
            ),
            error_code="LLM_UPSTREAM_ERROR",
        )
        raise HTTPException(
            status_code=502,
            detail={"code": "LLM_UPSTREAM_ERROR", "message": message},
        ) from error
    record_platform_event(
        db,
        actor=admin,
        request=request,
        intent=PlatformAuditIntent(
            action="llm_profile.list_models",
            resource_type="llm_profile",
            changes={"provider": payload.provider, "count": len(models)},
        ),
        result="success",
    )
    db.commit()
    return {"models": models}


@router.post("/{profile_id}/test", response_model=LLMProfileConnectivity)
def probe_profile(
    profile_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    profile = _get_profile(db, profile_id)
    try:
        result = test_connectivity(db, profile)
    except LLMApiUrlError as error:
        raise HTTPException(status_code=422, detail={"code": error.reason}) from error
    except LLMCredentialError as error:
        raise HTTPException(
            status_code=503, detail={"code": error.code}
        ) from error
    record_platform_event(
        db,
        actor=admin,
        request=request,
        intent=PlatformAuditIntent(
            action="llm_profile.test",
            resource_type="llm_profile",
            resource_id=str(profile.id),
            changes={"ok": result["ok"]},
        ),
        result="success" if result["ok"] else "failed",
    )
    db.commit()
    return result
