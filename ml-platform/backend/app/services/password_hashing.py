"""pbkdf2_sha256 口令哈希（passlib 兼容格式，stdlib 实现）。

背景（2026-11-03 升级批次 P1）：passlib 1.7 已停维护两年（其 [bcrypt] extra
还会钉住旧 bcrypt），平台仅用它的 ``CryptContext(schemes=["pbkdf2_sha256"])``
一种算法。本模块用 hashlib 原位重实现同一线上格式，全部既有哈希零迁移可用：

- 格式：``$pbkdf2-sha256$<rounds>$<salt_ab64>$<hash_ab64>``（passlib ab64 =
  标准 base64 字母表去 ``=`` 填充）；
- 新哈希轮数升至 600_000（OWASP 2023 对 pbkdf2-sha256 的建议值；passlib
  1.7 默认 29_000）。旧轮数哈希 verify 照常通过，``needs_update`` 返回
  True，登录路径既有的 rehash 钩子（auth.py）会在下一次成功登录时自动
  升级到新轮数——无需任何数据迁移；
- 兼容向量（真实 passlib 1.7.4 产出，固化在 test_password_hashing）锁死
  格式兼容性。

API 保持 passlib 风格（``hash``/``verify``/``needs_update``），畸形哈希
verify/needs_update 抛 ``ValueError``（等价旧 ``UnknownHashError`` 的调用方
语义：auth 捕获后按登录失败处理）。
"""
import base64
import hashlib
import hmac
import os
import re

_SCHEME = "pbkdf2-sha256"
_DIGEST = "sha256"
_KEYLEN = 32  # passlib pbkdf2_sha256 派生键长（256-bit）
DEFAULT_ROUNDS = 600_000
# passlib 1.7 时代的轮数：只用于识别"待升级"，不再用于新哈希
LEGACY_ROUNDS = 29_000

_HASH_RE = re.compile(
    rf"^\${_SCHEME}\$(\d+)\$([A-Za-z0-9./]+)\$([A-Za-z0-9./]+)$"
)


class UnknownHashError(ValueError):
    """哈希串不是本平台格式（历史上来自 passlib.exc，语义保持一致）。"""


def _ab64_encode(raw: bytes) -> str:
    # passlib ab64：标准 base64 的 '+' 写作 '.'，无 '=' 填充
    return base64.b64encode(raw).decode("ascii").rstrip("=").replace("+", ".")


def _ab64_decode(token: str) -> bytes:
    padding = "=" * (-len(token) % 4)
    return base64.b64decode(token.replace(".", "+") + padding)


def _parse(stored: str) -> tuple[int, bytes, bytes]:
    if not isinstance(stored, str):
        raise UnknownHashError("hash must be a string")
    match = _HASH_RE.match(stored)
    if match is None:
        raise UnknownHashError("unrecognized hash format")
    rounds = int(match.group(1))
    if rounds < 1 or rounds > 10_000_000:
        raise UnknownHashError("hash rounds out of range")
    salt = _ab64_decode(match.group(2))
    digest = _ab64_decode(match.group(3))
    if not salt or len(digest) != _KEYLEN:
        raise UnknownHashError("hash salt/digest malformed")
    return rounds, salt, digest


def pbkdf2_sha256_hash(password: str, *, rounds: int = DEFAULT_ROUNDS, salt: bytes | None = None) -> str:
    """生成 passlib 兼容格式的哈希（默认 600k 轮；测试可注入 salt/轮数）。"""
    if isinstance(password, bytes):
        password = password.decode("utf-8")
    salt = salt if salt is not None else os.urandom(16)
    derived = hashlib.pbkdf2_hmac(
        _DIGEST, password.encode("utf-8"), salt, rounds, dklen=_KEYLEN,
    )
    return f"${_SCHEME}${rounds}${_ab64_encode(salt)}${_ab64_encode(derived)}"


def pbkdf2_sha256_verify(password: str, stored: str) -> bool:
    """常量时间校验；畸形哈希抛 UnknownHashError（ValueError 子类）。"""
    rounds, salt, expected = _parse(stored)
    if isinstance(password, bytes):
        password = password.decode("utf-8")
    derived = hashlib.pbkdf2_hmac(
        _DIGEST, password.encode("utf-8"), salt, rounds, dklen=_KEYLEN,
    )
    return hmac.compare_digest(derived, expected)


def pbkdf2_sha256_needs_update(stored: str) -> bool:
    """轮数低于当前默认即待升级（登录 rehash 钩子消费）。畸形哈希抛错。"""
    rounds, _, _ = _parse(stored)
    return rounds < DEFAULT_ROUNDS


class PasswordHasher:
    """passlib CryptContext 风格的门面（hash/verify/needs_update）。

    四处旧调用点（auth/main/annotator_identity/inference_api_keys）与
    全部测试夹具都只用了这三个方法——保持同名门面使迁移零改动。
    """

    hash = staticmethod(pbkdf2_sha256_hash)
    verify = staticmethod(pbkdf2_sha256_verify)
    needs_update = staticmethod(pbkdf2_sha256_needs_update)
