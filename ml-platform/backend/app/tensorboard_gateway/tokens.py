"""Short-lived signed TensorBoard session claims."""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable


class SessionTokenInvalid(ValueError):
    pass


@dataclass(frozen=True)
class SessionClaims:
    session_id: str
    run_id: str
    relative_logdir: str
    expires_at: int


class SessionSigner:
    def __init__(self, secret: str | bytes, *, clock: Callable[[], float] = time.time):
        encoded = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        if len(encoded) < 32:
            raise ValueError("TensorBoard session secret must be at least 32 bytes")
        self.secret = encoded
        self.clock = clock

    def issue(self, *, session_id: str, run_id: str, relative_logdir: str, expires_at) -> str:
        _validate_segment(session_id, "session ID")
        _validate_segment(run_id, "Run ID")
        normalized = validate_relative_logdir(relative_logdir)
        payload = json.dumps({
            "session_id": session_id,
            "run_id": run_id,
            "relative_logdir": normalized,
            "expires_at": int(expires_at),
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        encoded = _encode(payload)
        signature = _encode(hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def verify(self, token: str) -> SessionClaims:
        try:
            encoded, supplied = token.split(".", maxsplit=1)
            expected = _encode(
                hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied, expected):
                raise SessionTokenInvalid("Session token signature is invalid")
            data = json.loads(_decode(encoded))
            if set(data) != {"session_id", "run_id", "relative_logdir", "expires_at"}:
                raise SessionTokenInvalid("Session token claims are invalid")
            claims = SessionClaims(
                session_id=str(data["session_id"]),
                run_id=str(data["run_id"]),
                relative_logdir=validate_relative_logdir(str(data["relative_logdir"])),
                expires_at=int(data["expires_at"]),
            )
            _validate_segment(claims.session_id, "session ID")
            _validate_segment(claims.run_id, "Run ID")
            if self.clock() >= claims.expires_at:
                raise SessionTokenInvalid("Session token has expired")
            return claims
        except SessionTokenInvalid:
            raise
        except Exception as error:
            raise SessionTokenInvalid("Session token is invalid") from error


def validate_relative_logdir(value: str) -> str:
    if not value or "\\" in value:
        raise SessionTokenInvalid("Session log directory is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SessionTokenInvalid("Session log directory is invalid")
    return path.as_posix()


def _validate_segment(value: str, label: str) -> None:
    if not value or "/" in value or "\\" in value or value in {".", ".."}:
        raise SessionTokenInvalid(f"Invalid {label}")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
