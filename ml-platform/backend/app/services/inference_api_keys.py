"""Lifecycle service for deployment-scoped inference API keys."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import secrets
import uuid

from passlib.context import CryptContext

from app.models.model_registry import InferenceApiKey


ALLOWED_SCOPES = frozenset({"inference.predict"})


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class InferenceApiKeyError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CreatedApiKey:
    record: InferenceApiKey
    plaintext: str = field(repr=False)


@dataclass(frozen=True)
class ApiKeyView:
    id: uuid.UUID
    prefix: str
    scopes: tuple[str, ...]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime | None


class InferenceApiKeyService:
    _context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

    @staticmethod
    def _normalized_scopes(scopes) -> tuple[str, ...]:
        if isinstance(scopes, str):
            raise InferenceApiKeyError("INFERENCE_API_KEY_SCOPE_INVALID")
        try:
            normalized = tuple(sorted(set(scopes)))
        except (TypeError, ValueError):
            raise InferenceApiKeyError("INFERENCE_API_KEY_SCOPE_INVALID") from None
        if not normalized or set(normalized) - ALLOWED_SCOPES:
            raise InferenceApiKeyError("INFERENCE_API_KEY_SCOPE_INVALID")
        return normalized

    @staticmethod
    def _key_id(value) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            raise InferenceApiKeyError("INFERENCE_API_KEY_INVALID") from None

    @staticmethod
    def _view(record: InferenceApiKey) -> ApiKeyView:
        return ApiKeyView(
            id=record.id,
            prefix=record.prefix,
            scopes=tuple(record.scopes or ()),
            expires_at=record.expires_at,
            last_used_at=record.last_used_at,
            revoked_at=record.revoked_at,
            created_at=record.created_at,
        )

    def create(self, db, deployment_id, actor_id, scopes, expires_at) -> CreatedApiKey:
        normalized_scopes = self._normalized_scopes(scopes)
        plaintext = "mli_" + secrets.token_urlsafe(32)
        record = InferenceApiKey(
            deployment_id=deployment_id,
            prefix=plaintext[:12],
            secret_hash=self._context.hash(plaintext),
            scopes=list(normalized_scopes),
            expires_at=expires_at,
            created_by_id=actor_id,
        )
        db.add(record)
        db.flush()
        return CreatedApiKey(record=record, plaintext=plaintext)

    def verify(self, db, plaintext, *, deployment_id=None, scope=None) -> InferenceApiKey:
        if not isinstance(plaintext, str) or not plaintext.startswith("mli_"):
            raise InferenceApiKeyError("INFERENCE_API_KEY_INVALID")
        candidates = db.query(InferenceApiKey).filter(
            InferenceApiKey.prefix == plaintext[:12],
        ).all()
        record = next(
            (
                candidate
                for candidate in candidates
                if self._context.verify(plaintext, candidate.secret_hash)
            ),
            None,
        )
        if record is None:
            raise InferenceApiKeyError("INFERENCE_API_KEY_INVALID")
        if deployment_id is not None and str(record.deployment_id) != str(deployment_id):
            raise InferenceApiKeyError("INFERENCE_API_KEY_INVALID")
        if record.revoked_at is not None:
            raise InferenceApiKeyError("INFERENCE_API_KEY_REVOKED")
        if (
            record.expires_at is not None
            and _as_utc_naive(record.expires_at) <= utcnow()
        ):
            raise InferenceApiKeyError("INFERENCE_API_KEY_EXPIRED")
        if scope is not None and scope not in set(record.scopes or ()):
            raise InferenceApiKeyError("INFERENCE_API_KEY_OUT_OF_SCOPE")
        record.last_used_at = utcnow()
        db.flush()
        return record

    def _record(self, db, key_id) -> InferenceApiKey:
        record = db.query(InferenceApiKey).filter(
            InferenceApiKey.id == self._key_id(key_id),
        ).with_for_update().first()
        if record is None:
            raise InferenceApiKeyError("INFERENCE_API_KEY_INVALID")
        return record

    def revoke(self, db, key_id, actor_id=None) -> InferenceApiKey:
        record = self._record(db, key_id)
        if record.revoked_at is None:
            record.revoked_at = utcnow()
            db.flush()
        return record

    def rotate(self, db, key_id, actor_id) -> CreatedApiKey:
        record = self.revoke(db, key_id, actor_id)
        return self.create(
            db,
            record.deployment_id,
            actor_id,
            record.scopes,
            record.expires_at,
        )

    def list_for_deployment(self, db, deployment_id) -> list[ApiKeyView]:
        records = db.query(InferenceApiKey).filter(
            InferenceApiKey.deployment_id == deployment_id,
        ).order_by(InferenceApiKey.created_at.desc(), InferenceApiKey.id.desc()).all()
        return [self._view(record) for record in records]
