"""Event ingest pipeline (补齐路线第一批 F5b, B1-07).

实时接入通道（技术方案 §9A.2，D50–D53）：
- 契约（E18）pydantic 校验：payload_version=v1 要求 station / business_event_id /
  occurred_at / payload（波形原文可选）；
- 幂等：同 (source, business_event_id) 且内容相同 → duplicate 跳过；同 ID 不同内容
  → 落 rejected 行可追查（不覆盖、不静默）；校验失败 → rejected + 原因；
- 消费入口有两个，走同一 `ingest_batch`：Kafka 消费循环（D51，KAFKA_INGEST_ENABLED
  开关，默认关）与手动发布端点（无 Kafka 环境的等价路径）；
- 心跳写 PlatformOption `ingest.heartbeat`（多进程/重启后页脚仍可读）；页脚状态由
  心跳新鲜度驱动（D52）：未启用 / 心跳超时告警 / 正常——未启用就如实说未启用。

分数级 PSI（services/anomaly_drift.py）与本模块互不影响；本模块不产生预警，
只落原始记录（接入通道保存原文，D53）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, Field, ValidationError

from app.config import settings as app_settings
from app.models.ingest import IngestEvent
from app.models.platform_option import get_option, set_option

logger = logging.getLogger(__name__)

INGEST_HEARTBEAT_KEY = "ingest.heartbeat"
INGEST_PAYLOAD_VERSION = "v1"


class IngestContractError(ValueError):
    """接入契约校验失败（payload_version、必填字段、字段类型）。"""


class IngestPayloadV1(BaseModel):
    """版本化输入契约 v1（E18）：来源、工位、业务事件 ID、采集时间、载荷版本、
    关键字段与单位；波形原文可选（编码串）。"""

    station: str = Field(min_length=1, max_length=128)
    business_event_id: str = Field(min_length=1, max_length=128)
    occurred_at: str = Field(min_length=10, max_length=64)
    payload: dict = Field(default_factory=dict)
    waveform: str | None = Field(default=None, max_length=2_000_000)
    unit: str | None = Field(default=None, max_length=32)


def payload_hash(payload: Mapping) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_contract(raw: Mapping) -> IngestPayloadV1:
    try:
        return IngestPayloadV1.model_validate(raw)
    except ValidationError as error:
        reasons = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()[:5]
        )
        raise IngestContractError(f"契约校验失败（{reasons}）") from None


def ingest_batch(
    db, *, project_id, source: str, events: Sequence[Mapping],
    topic: str | None = None, partition: int | None = None,
    offsets: Sequence[int | None] | None = None, now: datetime | None = None,
) -> dict:
    """校验并落一批事件（调用方 commit）。返回各状态计数。

    幂等键 = (source, business_event_id)。唯一约束冲突按已存行的 hash 分流：
    相同 → duplicate；不同 → rejected（同键不同内容可追查，不覆盖）。
    """
    now = now or datetime.utcnow()
    batch_id = uuid.uuid4()
    counts = {"accepted": 0, "duplicate": 0, "rejected": 0}
    for index, raw in enumerate(events):
        offset = offsets[index] if offsets is not None and index < len(offsets) else None
        status = "accepted"
        reason = None
        occurred_at = None
        latency = None
        contract = None
        raw_map = raw if isinstance(raw, Mapping) else {}
        try:
            contract = _parse_contract(raw)
            occurred_at = _parse_time(contract.occurred_at)
            if occurred_at is None:
                raise IngestContractError("occurred_at 不是可解析的 ISO 时间")
            latency = int((now - occurred_at).total_seconds())
            # 幂等哈希只算业务内容（E18「同键不同内容」的「内容」口径）：
            # occurred_at 是采集时间戳，重试/重放时必然略有差异，不参与
            content_hash = payload_hash({
                "station": contract.station, "payload": contract.payload,
                "waveform": contract.waveform, "unit": contract.unit,
            })
            business_event_id = contract.business_event_id
            existing = (
                db.query(IngestEvent)
                .filter(
                    IngestEvent.source == source,
                    IngestEvent.business_event_id == business_event_id,
                )
                .first()
            )
            if existing is not None:
                if existing.payload_hash == content_hash:
                    status = "duplicate"
                    reason = "同源同业务事件 ID 已接受过（幂等跳过）"
                else:
                    status = "rejected"
                    reason = (
                        f"同业务事件 ID 内容不一致（原 hash {existing.payload_hash[:12]}，"
                        f"本次 {content_hash[:12]}）——不覆盖，可追查"
                    )
                    logger.warning(
                        "ingest event %s/%s replayed with different content",
                        source, business_event_id,
                    )
            payload_out = {
                "station": contract.station,
                "business_event_id": business_event_id,
                "occurred_at": contract.occurred_at,
                "payload": contract.payload,
                "waveform": contract.waveform,
                "unit": contract.unit,
            }
        except IngestContractError as error:
            status = "rejected"
            reason = str(error)[:256]
            payload_out = dict(raw_map)
            content_hash = payload_hash(payload_out)
            # 契约失败时可能没有业务事件 ID：给可追查的临时 ID（不与真实 ID 冲突）
            business_event_id = f"rejected-{uuid.uuid4().hex[:16]}"
        if status == "rejected" and reason and "内容不一致" in reason:
            # 同 ID 不同内容的追查行不能复用原 ID——(source, business_event_id)
            # 唯一约束下它顶替不了原 accepted 行；派生 ID 保留可追查性（原 ID 在
            # business_event_id 前缀与 payload 里都在）
            business_event_id = f"{business_event_id}#replay-{content_hash[:8]}"
        existing_for_write = (
            db.query(IngestEvent)
            .filter(
                IngestEvent.source == source,
                IngestEvent.business_event_id == business_event_id,
            )
            .first()
        )
        if existing_for_write is not None and status == "accepted":
            # 并发下唯一约束兜底：已存在即 duplicate
            status = "duplicate"
        if status == "duplicate":
            # duplicate = 跳过：原 ID 已占用唯一键，不能再插一行（否则撞约束）；
            # 幂等语义就是「不产生新记录」
            counts[status] = counts.get(status, 0) + 1
            continue
        db.add(IngestEvent(
            project_id=project_id, source=source, topic=topic, partition=partition,
            offset=offset,
            business_event_id=business_event_id[:128],
            station=str((contract.station if contract else raw_map.get("station", "")) or "")[:128] or None,
            occurred_at=occurred_at, latency_seconds=latency,
            payload_version=INGEST_PAYLOAD_VERSION if contract else "unknown",
            payload=payload_out, payload_hash=content_hash, status=status,
            reject_reason=reason, ingest_batch_id=batch_id, received_at=now,
        ))
        counts[status] = counts.get(status, 0) + 1
    record_heartbeat(db, state="ok", at=now)
    return {"batch_id": str(batch_id), **counts}


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(None).replace(tzinfo=None)
    # naive 输入按原值使用（平台时间口径为 naive UTC）——转时区会让 UTC+8 环境下的
    # 事件时间平移 8 小时，延迟标签变成负数
    return parsed


def record_heartbeat(db, *, state: str, at: datetime | None = None) -> None:
    """消费心跳（D51）：落 PlatformOption，多进程与重启后页脚仍可读。
    set_option 内部自行 commit（既有先例）。"""
    at = at or datetime.utcnow()
    set_option(db, INGEST_HEARTBEAT_KEY, {"state": state, "at": at.isoformat()})


def ingest_status(db) -> dict:
    """页脚实时链路状态（D52，诚实设计⑤）：未启用如实说未启用；心跳超时 = 告警。"""
    enabled = bool(app_settings.kafka_ingest_enabled)
    now = datetime.utcnow()
    if not enabled:
        return {
            "enabled": False, "state": "disabled",
            "detail": "实时链路未启用（KAFKA_INGEST_ENABLED 未开启）",
            "last_heartbeat_at": None, "checked_at": now.isoformat(),
        }
    heartbeat = get_option(db, INGEST_HEARTBEAT_KEY) or {}
    last_at = _parse_time(str(heartbeat.get("at", ""))) if heartbeat.get("at") else None
    state = str(heartbeat.get("state", "unknown"))
    stale_after = int(app_settings.ingest_heartbeat_stale_seconds)
    if last_at is None:
        return {
            "enabled": True, "state": "stale",
            "detail": "消费进程尚未产生心跳（未启动或启动失败）",
            "last_heartbeat_at": None, "checked_at": now.isoformat(),
        }
    age = (now - last_at).total_seconds()
    if age > stale_after:
        return {
            "enabled": True, "state": "stale",
            "detail": f"心跳已超时 {int(age)} 秒（阈值 {stale_after} 秒）",
            "last_heartbeat_at": last_at.isoformat(), "checked_at": now.isoformat(),
        }
    return {
        "enabled": True, "state": state if state in ("ok", "stale") else "ok",
        "detail": f"消费正常（心跳 {int(age)} 秒前）",
        "last_heartbeat_at": last_at.isoformat(), "checked_at": now.isoformat(),
    }
