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


def model_port_is_enveloped(wire: object) -> bool:
    """判断端口字节是否带验证信封（调用方选择是否记录兼容日志）。"""
    return isinstance(wire, (bytes, bytearray)) and bytes(wire).startswith(
        _PORT_ENVELOPE_MAGIC,
    )


# ---------------------------------------------------------------------------
# DAG 模型端口字节信封（Mimosa Medium 21 项收口：端口字节透传验证）
#
# 端口字节的合法来源只有平台生产者（训练/joblib.dump 算子、密封工件加载）。
# 信封把"内容 hash + 平台密封"随字节一起走端口，消费端在反序列化前验证：
# 篡改/替换端口字节（如未来新增的持久化通道）即被拒。
# 兼容策略：无信封头的裸 joblib 按旧载荷放行（存量运行中的工作流不受影响），
# 有信封头则验签失败必须拒绝。
# ---------------------------------------------------------------------------

_PORT_ENVELOPE_MAGIC = b"MLPLATFORM-MODEL-SEAL1\n"


def seal_model_port_bytes(payload: bytes) -> bytes:
    """生产者侧：把裸模型字节打包成验证信封。"""
    digest = hashlib.sha256(payload).hexdigest()
    header = {
        "sha256": digest,
        "model_seal": compute_model_seal(digest),
    }
    return (
        _PORT_ENVELOPE_MAGIC
        + __import__("json").dumps(header, sort_keys=True).encode("ascii")
        + b"\n"
        + payload
    )


def verify_model_port_bytes(wire: bytes) -> tuple[bytes, bool]:
    """消费侧：信封载荷验签并解包；裸载荷按旧格式放行。

    返回 ``(inner_payload, sealed)``。信封存在但验签失败抛 ValueError
    （篡改/替换即拒绝）；裸载荷 ``sealed=False`` 供调用方记录兼容日志。
    """
    import json as _json

    if not isinstance(wire, (bytes, bytearray)) or not wire.startswith(
        _PORT_ENVELOPE_MAGIC,
    ):
        return bytes(wire) if isinstance(wire, bytearray) else wire, False
    body = bytes(wire[len(_PORT_ENVELOPE_MAGIC):])
    newline = body.find(b"\n")
    if newline < 0:
        raise ValueError("MODEL_PORT_ENVELOPE_CORRUPT")
    try:
        header = _json.loads(body[:newline].decode("ascii"))
    except ValueError as error:
        raise ValueError("MODEL_PORT_ENVELOPE_CORRUPT") from error
    inner = body[newline + 1:]
    digest = hashlib.sha256(inner).hexdigest()
    if not seal_is_valid(header, digest):
        raise ValueError("MODEL_PORT_SEAL_INVALID")
    return inner, True
