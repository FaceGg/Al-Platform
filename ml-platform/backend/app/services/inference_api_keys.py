"""Lifecycle service for deployment-scoped inference API keys."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import secrets
import threading
import time
import uuid

from passlib.context import CryptContext

from app.models.model_registry import InferenceApiKey


ALLOWED_SCOPES = frozenset({"inference.predict"})
USAGE_TOUCH_INTERVAL_SECONDS = 60
VERIFICATION_CACHE_TTL_SECONDS = 300
VERIFICATION_CACHE_MAX_ENTRIES = 1024


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
    _verification_locks_guard = threading.Lock()
    _verification_locks: dict[bytes, threading.Lock] = {}
    _verification_cache_lock = threading.RLock()
    _verification_cache: dict[bytes, tuple[str, str, float]] = {}

    @classmethod
    def _cache_key(cls, plaintext):
        return hashlib.sha256(plaintext.encode("utf-8")).digest()

    @classmethod
    def _verification_lock(cls, cache_key):
        with cls._verification_locks_guard:
            lock = cls._verification_locks.get(cache_key)
            if lock is None:
                lock = threading.Lock()
                cls._verification_locks[cache_key] = lock
                if len(cls._verification_locks) > 4096:
                    for stale_key in tuple(cls._verification_locks):
                        if stale_key not in cls._verification_cache:
                            cls._verification_locks.pop(stale_key, None)
                            if len(cls._verification_locks) <= 4096:
                                break
            return lock

    @classmethod
    def _cached_record(cls, cache_key, candidates):
        now = time.monotonic()
        with cls._verification_cache_lock:
            cached = cls._verification_cache.get(cache_key)
            if cached is None:
                return None
            record_id, secret_hash, expires_at = cached
            if expires_at <= now:
                cls._verification_cache.pop(cache_key, None)
                return None
            for candidate in candidates:
                if str(candidate.id) == record_id and candidate.secret_hash == secret_hash:
                    return candidate
        return None

    @classmethod
    def _cache_record(cls, cache_key, record):
        with cls._verification_cache_lock:
            if len(cls._verification_cache) >= VERIFICATION_CACHE_MAX_ENTRIES:
                oldest_key = min(
                    cls._verification_cache,
                    key=lambda key: cls._verification_cache[key][2],
                )
                cls._verification_cache.pop(oldest_key, None)
            cls._verification_cache[cache_key] = (
                str(record.id),
                record.secret_hash,
                time.monotonic() + VERIFICATION_CACHE_TTL_SECONDS,
            )

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

    def verify(
        self,
        db,
        plaintext,
        *,
        deployment_id=None,
        scope=None,
        touch_last_used: bool = True,
    ) -> InferenceApiKey:
        if not isinstance(plaintext, str) or not plaintext.startswith("mli_"):
            raise InferenceApiKeyError("INFERENCE_API_KEY_INVALID")
        candidates = db.query(InferenceApiKey).filter(
            InferenceApiKey.prefix == plaintext[:12],
        ).all()
        cache_key = self._cache_key(plaintext)
        record = self._cached_record(cache_key, candidates)
        if record is None:
            with self._verification_lock(cache_key):
                record = self._cached_record(cache_key, candidates)
                if record is None:
                    record = next(
                        (
                            candidate
                            for candidate in candidates
                            if self._context.verify(plaintext, candidate.secret_hash)
                        ),
                        None,
                    )
                    if record is not None:
                        self._cache_record(cache_key, record)
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
        if not touch_last_used:
            return record
        now = utcnow()
        # Avoid serializing every prediction on one API-key row.  Usage metadata
        # remains current within a bounded interval while revocation/expiry checks
        # still query the authoritative row on every request.
        if (
            record.last_used_at is None
            or (now - _as_utc_naive(record.last_used_at)).total_seconds()
            >= USAGE_TOUCH_INTERVAL_SECONDS
        ):
            record.last_used_at = now
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
