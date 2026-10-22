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
    LLMProfileConnectivity,
    LLMProfileCreate,
    LLMProfileOut,
    LLMProfileUpdate,
)
from app.services.llm_gateway import (
    LLMApiUrlError,
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


@router.post("", response_model=LLMProfileOut, status_code=201)
def create_profile(
    payload: LLMProfileCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    try:
        profile_id = uuid4()
        profile = LLMProfile(
            id=profile_id,
            name=payload.name,
            provider=payload.provider,
            api_url=payload.api_url,
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
