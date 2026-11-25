#!/usr/bin/env python3
"""Fernet master key rotation tool (补齐路线第一批 E17/D8).

三把主密钥共用的离线运维脚本，逐行解密后用新密钥重加密：
- notification_endpoints.encrypted_config（通知凭据）
- llm_profiles.api_key_encrypted（LLM 档案 API Key 密文）
- external_data_sources.password_encrypted（外部数据源口令密文）

形态：MultiFernet 过渡（新密钥加密写回、旧密钥仅解密）；幂等——已能用
新密钥解开的行跳过；--dry-run 只统计不写回；全程不回显明文；动作写
平台审计（platform_audit_events，审计事件不含任何明文/密文）。

用法：
    python tools/rotate_fernet_keys.py \
        --new-key <NEW_FERNET_KEY> [--old-key <OLD_FERNET_KEY>]
        [--scope all|notification|llm|datasource] [--dry-run]

密钥来源优先级：命令行 > 环境变量（ROTATE_NEW_KEY / ROTATE_OLD_KEY）>
应用配置（old key 取当前生效的 resolved_*_master_key）。API Key 是哈希
存储（secret_hash）非 Fernet 密文，明确不在轮换范围。
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime
from pathlib import Path

# 允许从仓库根/后端根直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.fernet import Fernet, InvalidToken, MultiFernet  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.services.notification_crypto import decrypt_config, encrypt_config  # noqa: E402
from app.services.llm_profile_crypto import decrypt_llm_api_key, encrypt_llm_api_key  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rotate Fernet master keys (notification/LLM/datasource).")
    parser.add_argument("--new-key", default=None, help="New Fernet key (or env ROTATE_NEW_KEY)")
    parser.add_argument("--old-key", default=None, help="Old Fernet key (defaults to the active configured key)")
    parser.add_argument("--scope", choices=["all", "notification", "llm", "datasource"], default="all")
    parser.add_argument("--dry-run", action="store_true", help="Count rotatable rows without writing")
    return parser.parse_args()


def _resolve_key(explicit: str | None, env_name: str, configured) -> bytes | None:
    if explicit:
        return explicit.encode("ascii")
    import os

    env_value = os.environ.get(env_name)
    if env_value:
        return env_value.encode("ascii")
    if configured is not None:
        return configured.get_secret_value().encode("ascii")
    return None


def _validate_fernet(key: bytes, label: str) -> Fernet:
    try:
        return Fernet(key)
    except (ValueError, TypeError) as error:
        print(f"[error] {label} is not a valid Fernet key: {error}")
        sys.exit(2)


def _audit_rotation(db, *, scope: str, dry_run: bool, counts: dict[str, int]) -> None:
    """动作写平台审计（不含任何明文/密文；dry-run 同样留痕）。"""
    try:
        from app.models.platform_audit import PlatformAuditEvent

        db.add(PlatformAuditEvent(
            actor_id=None,
            actor_username="rotate_fernet_keys",
            action="platform.fernet_keys.rotate",
            resource_type="platform_option",
            resource_id=f"scope={scope}",
            result="success",
            request_id=uuid.uuid4(),
            source_ip=None,
            changes={
                "scope": scope,
                "dry_run": bool(dry_run),
                "rotated": {key: int(value) for key, value in counts.items()},
            },
            error_code=None,
        ))
        db.commit()
    except Exception as error:
        print(f"[warn] platform audit recording failed: {error}")
        db.rollback()


def rotate_notifications(old_secret, new_secret, old: Fernet, new: Fernet, dry_run: bool) -> int:
    """notification_endpoints.encrypted_config：JSON 配置整段密文。"""
    from app.models.notifications import NotificationEndpoint

    count = 0
    with SessionLocal() as db:
        rows = db.query(NotificationEndpoint).all()
        for row in rows:
            token = row.encrypted_config
            if not token:
                continue
            try:
                # 幂等：新密钥已能解开 → 跳过
                new.decrypt(token.encode("ascii"))
                continue
            except InvalidToken:
                pass
            config = decrypt_config(token, old_secret)
            db.add(row)
            row.encrypted_config = encrypt_config(config, new_secret)
            count += 1
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return count


def rotate_llm_profiles(old_secret, new_secret, old: Fernet, new: Fernet, dry_run: bool) -> int:
    from app.models.llm_profile import LLMProfile

    count = 0
    with SessionLocal() as db:
        rows = db.query(LLMProfile).all()
        for row in rows:
            token = row.api_key_encrypted
            if not token:
                continue
            try:
                new.decrypt(token.encode("ascii"))
                continue
            except InvalidToken:
                pass
            api_key = decrypt_llm_api_key(token, old_secret)
            row.api_key_encrypted = encrypt_llm_api_key(api_key, new_secret)
            count += 1
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return count


def rotate_datasources(old_secret, new_secret, old: Fernet, new: Fernet, dry_run: bool) -> int:
    from app.models.external_data_source import ExternalDataSource
    from app.services.external_data_sources import encrypt_password

    count = 0
    with SessionLocal() as db:
        rows = db.query(ExternalDataSource).all()
        for row in rows:
            token = row.password_encrypted
            if not token:
                continue
            try:
                new.decrypt(token.encode("ascii"))
                continue
            except InvalidToken:
                pass
            # 旧密文直接用 old Fernet 解（不回显，密钥对象内流转）
            password = old.decrypt(token.encode("ascii")).decode("utf-8")
            row.password_encrypted = new.encrypt(password.encode("utf-8")).decode("ascii")
            count += 1
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return count


def main() -> None:
    args = _parse_args()
    new_key = _resolve_key(args.new_key, "ROTATE_NEW_KEY", None)
    old_key = _resolve_key(args.old_key, "ROTATE_OLD_KEY", None)
    if new_key is None:
        print("[error] --new-key or env ROTATE_NEW_KEY is required")
        sys.exit(2)
    new_fernet = _validate_fernet(new_key, "new key")
    new_secret = SecretStr(new_key.decode("ascii"))

    # old key 缺省取当前生效密钥（按 scope 聚合：通知密钥为基准形制）
    if old_key is None:
        candidates = [
            settings.resolved_notification_master_key,
            settings.resolved_llm_master_key,
            settings.resolved_datasource_master_key,
        ]
        configured = next((key for key in candidates if key is not None), None)
        if configured is None:
            print("[error] no old key available: pass --old-key or configure the active master key")
            sys.exit(2)
        old_key = configured.get_secret_value().encode("ascii")
    old_fernet = _validate_fernet(old_key, "old key")
    old_secret = SecretStr(old_key.decode("ascii"))

    # MultiFernet 过渡形制说明：解密语义由各列显式实现（幂等跳过已轮换行，
    # 未轮换行用旧密钥解、新密钥写回），与 MultiFernet([new, old]) 等价。
    _ = MultiFernet([new_fernet, old_fernet])

    counts: dict[str, int] = {}
    scope = args.scope
    if scope in ("all", "notification"):
        counts["notification_endpoints"] = rotate_notifications(
            old_secret, new_secret, old_fernet, new_fernet, args.dry_run,
        )
        print(f"[ok] notification_endpoints rotated: {counts['notification_endpoints']}")
    if scope in ("all", "llm"):
        counts["llm_profiles"] = rotate_llm_profiles(
            old_secret, new_secret, old_fernet, new_fernet, args.dry_run,
        )
        print(f"[ok] llm_profiles rotated: {counts['llm_profiles']}")
    if scope in ("all", "datasource"):
        counts["external_data_sources"] = rotate_datasources(
            old_secret, new_secret, old_fernet, new_fernet, args.dry_run,
        )
        print(f"[ok] external_data_sources rotated: {counts['external_data_sources']}")

    with SessionLocal() as db:
        _audit_rotation(db, scope=scope, dry_run=args.dry_run, counts=counts)
    print(f"[done] scope={scope} dry_run={args.dry_run} at {datetime.utcnow().isoformat()}")


if __name__ == "__main__":
    main()
