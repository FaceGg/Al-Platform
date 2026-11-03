"""模型工件反序列化封印（Mimosa 2026-11-03 深扫"不安全反序列化"收口）。

威胁模型：自助注册成员可上传任意 `.joblib` 工件并在编排中接到
apply_model/load_model_port——裸 pickle 反序列化即服务端任意代码执行。
模型持久化是平台核心功能，不能禁；改为"平台签名"防线：

- **写入侧**（ArtifactService.create_from_file）：model 类工件落库时在
  metadata 里写入 `model_seal = HMAC-SHA256(派生密钥, sha256)`，标签随
  工件行一起存储。派生密钥来自服务端 SECRET_KEY，不出进程。
- **加载侧**（load_model_port / LoadModelArtifact / apply_model 等
  joblib/pickle 入口）：反序列化前验签。自助上传的裸 pickle 没有 seal
  （或 seal 对不上内容 hash）→ 拒绝加载，训练产物/经平台写入口的工件
  照常工作。

密封不改变存储内容本身（向后兼容：既有带正确 sha256 的工件在下次
经平台读取时可按需补验——见 legacy 兼容分支）。
"""
import hashlib
import hmac

from app.config import settings

_SEAL_KEY_INFO = b"ml-platform:model-artifact-seal:v1"


def _seal_key() -> bytes:
    secret = (
        settings.secret_key.get_secret_value()
        if settings.secret_key is not None
        else ""
    )
    return hashlib.pbkdf2_hmac(
        "sha256", secret.encode("utf-8"), _SEAL_KEY_INFO, 1,
    )


def compute_model_seal(content_sha256: str) -> str:
    """HMAC-SHA256(派生密钥, 工件内容 sha256) → 十六进制密封标签。"""
    return hmac.new(
        _seal_key(), str(content_sha256).encode("ascii"), hashlib.sha256,
    ).hexdigest()


def seal_is_valid(metadata: dict | None, content_sha256: str) -> bool:
    """验密封：metadata 缺标签或标签与内容 hash 不符即拒绝。"""
    if not isinstance(metadata, dict):
        return False
    claimed = metadata.get("model_seal")
    if not isinstance(claimed, str) or not claimed:
        return False
    return hmac.compare_digest(claimed, compute_model_seal(content_sha256))


def model_seal_metadata(content_sha256: str) -> dict:
    """写入侧便捷函数：返回应合并进 artifact metadata 的密封字段。"""
    return {"model_seal": compute_model_seal(content_sha256)}
