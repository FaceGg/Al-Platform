"""Fernet boundary for LLM profile API keys (mirrors notification_crypto)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr


class LLMCredentialError(RuntimeError):
    """Stable LLM credential failure without plaintext details."""

    def __init__(self, code: str = "LLM_CREDENTIAL_INVALID") -> None:
        super().__init__(code)
        self.code = code


def _fernet(master_key: SecretStr) -> Fernet:
    try:
        return Fernet(master_key.get_secret_value().encode("ascii"))
    except (AttributeError, TypeError, UnicodeEncodeError, ValueError) as error:
        raise LLMCredentialError() from error


def encrypt_llm_api_key(api_key: str, master_key: SecretStr) -> str:
    if not api_key:
        raise LLMCredentialError()
    return _fernet(master_key).encrypt(api_key.encode("utf-8")).decode("ascii")


def decrypt_llm_api_key(token: str | None, master_key: SecretStr) -> str:
    """Return the decrypted key, or ``""`` when the profile stores none."""
    if not token:
        return ""
    try:
        return _fernet(master_key).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError) as error:
        raise LLMCredentialError() from error
