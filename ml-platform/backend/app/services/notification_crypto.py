"""Authenticated encryption boundary for notification endpoint configuration."""

from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr


class NotificationCredentialError(RuntimeError):
    """Stable notification credential failure without plaintext details."""

    def __init__(self, code: str = "NOTIFICATION_CREDENTIAL_INVALID") -> None:
        super().__init__(code)
        self.code = code


def _fernet(master_key: SecretStr) -> Fernet:
    try:
        return Fernet(master_key.get_secret_value().encode("ascii"))
    except (AttributeError, TypeError, UnicodeEncodeError, ValueError) as error:
        raise NotificationCredentialError() from error


def _encode_config(config: dict[str, object]) -> bytes:
    if not isinstance(config, dict) or any(not isinstance(key, str) for key in config):
        raise NotificationCredentialError()
    try:
        return json.dumps(
            config,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise NotificationCredentialError() from error


def encrypt_config(config: dict[str, object], master_key: SecretStr) -> str:
    """Encrypt a JSON object without retaining a plaintext representation."""
    return _fernet(master_key).encrypt(_encode_config(config)).decode("ascii")


def decrypt_config(token: str, master_key: SecretStr) -> dict[str, object]:
    """Decrypt an endpoint configuration and reject malformed credential data."""
    if not isinstance(token, str):
        raise NotificationCredentialError()
    try:
        raw = _fernet(master_key).decrypt(token.encode("ascii"))
        value = json.loads(raw.decode("utf-8"))
    except (InvalidToken, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise NotificationCredentialError() from error
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise NotificationCredentialError()
    return value
