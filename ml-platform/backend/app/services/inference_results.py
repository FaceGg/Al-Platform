"""Per-sample inference result persistence (补齐路线第一批 B1-16).

异步落库路径（D2：BackgroundTasks→ThreadPoolExecutor，与遥测同形）：
- 全量窄表批量插入 + 聚合桶 upsert（PG on_conflict 快路径；键含 NULL 时
  走 SELECT→INSERT，重复桶由读侧 SUM 兜底——NULL 组合在默认唯一约束下
  互异，见 models/inference_result.py 注）；
- 完整快照：命中异常或抽样命中时写对象存储（inference-snapshots/）；
- 日量上限：Redis INCR 当日计数器（24h TTL），超限降级「只存异常 + 抽样」，
  正常样本只进聚合桶计数；计数器不可用时放行（容量护栏 fail-open，
  不是安全控制）；
- 保留期：prune 由每日 beat 清理（独立配置 90 天，先例 prune_inference_telemetry）；
- 失败告警：写失败→域事件 inference.result_persist_failed 入 outbox（D4），
  推理响应不受影响。

demo 隔离（D13）：record_demo 单行通道写 channel='demo'，不进聚合桶；
聚合与查询默认排除 demo。
"""
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.database import SessionLocal
from app.events.domain import create_domain_event
from app.models.compute import EdgeDevice
from app.models.inference_result import InferenceResult, InferenceResultBucket
from app.models.quality_domain import QualityScene, QualityStation
from app.storage.base import StorageError
from app.storage.factory import create_artifact_storage


logger = logging.getLogger(__name__)

# context 保留键 → 明细表专属列；其余键进 extra JSON（技术方案 §3.2）
CONTEXT_RESERVED_KEYS = ("sample_key", "station", "device", "batch_no", "shift", "product", "collected_at")
MAX_CONTEXT_KEYS = 32
MAX_CONTEXT_VALUE_CHARS = 256
CONTEXT_INVALID = "INFERENCE_CONTEXT_INVALID"
MAX_CONTEXT_ROWS = 10000

_SAFE_FILENAME = re.compile(r"[^0-9A-Za-z._-]+")


@dataclass(frozen=True)
class ContextRow:
    sample_key: str | None = None
    station_id: UUID | None = None
    scene_id: UUID | None = None
    device_id: UUID | None = None
    batch_no: str | None = None
    shift: str | None = None
    product_code: str | None = None
    collected_at: datetime | None = None
    extra: dict | None = None


def validate_inference_context(context: Sequence[Mapping] | None, record_count: int) -> list[dict] | None:
    """契约校验（D3）：行式、等长、键数 ≤32、字符串值 ≤256 字符。"""
    if context is None:
        return None
    if not isinstance(context, (list, tuple)):
        raise ValueError(CONTEXT_INVALID)
    if len(context) != record_count:
        raise ValueError(CONTEXT_INVALID)
    rows: list[dict] = []
    for row in context:
        if not isinstance(row, Mapping):
            raise ValueError(CONTEXT_INVALID)
        if len(row) > MAX_CONTEXT_KEYS:
            raise ValueError(CONTEXT_INVALID)
        clean: dict = {}
        for key, value in row.items():
            if not isinstance(key, str) or not key:
                raise ValueError(CONTEXT_INVALID)
            if value is None:
                continue
            if isinstance(value, bool) or isinstance(value, (int, float, str)):
                if isinstance(value, str) and len(value) > MAX_CONTEXT_VALUE_CHARS:
                    raise ValueError(CONTEXT_INVALID)
                clean[key] = value
            else:
                raise ValueError(CONTEXT_INVALID)
        rows.append(clean)
    return rows


def resolve_context_rows(db: Session, context: Sequence[Mapping] | None, record_count: int | None = None) -> list[ContextRow]:
    """保留键换算（工位 code→工位/场景、设备名→设备）；工位在场景内按
    code 解析，多场景同 code 时首个命中。契约校验需要记录数对齐。"""
    expected = record_count if record_count is not None else (len(context) if context is not None else 0)
    rows: list[ContextRow] = []
    for clean in validate_inference_context(context, expected) or []:
        sample_key = clean.get("sample_key")
        batch_no = clean.get("batch_no")
        shift = clean.get("shift")
        product_code = clean.get("product")
        station_id = scene_id = device_id = None
        collected_at = None
        station_code = clean.get("station")
        if isinstance(station_code, str) and station_code:
            station = (
                db.query(QualityStation)
                .join(QualityScene, QualityScene.id == QualityStation.scene_id)
                .filter(QualityStation.code == str(station_code)[:128])
                .order_by(QualityStation.created_at.asc(), QualityStation.id.asc())
                .first()
            )
            if station is not None:
                station_id = station.id
                scene_id = station.scene_id
        device_name = clean.get("device")
        if isinstance(device_name, str) and device_name:
            device = (
                db.query(EdgeDevice)
                .filter(EdgeDevice.name == str(device_name)[:128])
                .order_by(EdgeDevice.created_at.asc(), EdgeDevice.id.asc())
                .first()
            )
            if device is not None:
                device_id = device.id
        raw_collected = clean.get("collected_at")
        if isinstance(raw_collected, str) and raw_collected:
            collected_at = _parse_collected_at(raw_collected)
        extra = {key: value for key, value in clean.items() if key not in CONTEXT_RESERVED_KEYS}
        rows.append(ContextRow(
            sample_key=str(sample_key)[:256] if isinstance(sample_key, str) and sample_key else None,
            station_id=station_id,
            scene_id=scene_id,
            device_id=device_id,
            batch_no=str(batch_no)[:128] if isinstance(batch_no, str) and batch_no else None,
            shift=str(shift)[:128] if isinstance(shift, str) and shift else None,
            product_code=str(product_code)[:128] if isinstance(product_code, str) and product_code else None,
            collected_at=collected_at,
            extra=extra or None,
        ))
    return rows


def _parse_collected_at(raw: str) -> datetime | None:
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        # PG now() 带时区与 naive 列比较会崩——入库前统一归一 naive UTC（坑）
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


@lru_cache(maxsize=1)
def _snapshot_storage():
    return create_artifact_storage(app_settings)


@lru_cache(maxsize=1)
def _daily_counter_client():
    url = app_settings.redis_events_url
    if url is None:
        return None
    try:
        from redis import Redis

        return Redis.from_url(url.get_secret_value(), decode_responses=True)
    except Exception:
        return None


def _snapshot_filename(request_id: str, index: int) -> str:
    stem = _SAFE_FILENAME.sub("-", str(request_id))[:64].strip("-") or uuid4().hex
    return f"{stem}-{index}.json"


class InferenceResultRecorder:
    """异步落库执行体：一个后台任务一批（一次请求的所有记录）。"""

    def __init__(self, *, storage=None, counter=None, sample_rate: float | None = None):
        self._storage = storage
        self._counter = counter
        self._sample_rate = (
            app_settings.inference_snapshot_sample_rate
            if sample_rate is None else sample_rate
        )

    def _storage_or_default(self):
        if self._storage is not None:
            return self._storage
        return _snapshot_storage()

    def _counter_or_default(self):
        if self._counter is not None:
            return self._counter
        return _daily_counter_client()

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------

    def record_prediction(
        self,
        *,
        request_id: str,
        project_id,
        deployment_id=None,
        revision_id=None,
        model_version_id=None,
        condition_values: Sequence[str | None] | None = None,
        context_rows: Sequence[ContextRow] | None = None,
        result: Mapping,
        records: Sequence[Mapping],
        occurred_at: datetime | None = None,
        retention_days: int | None = None,
        channel: str = "online",
        threshold: float | None = None,
    ) -> None:
        """批量落库（后台线程执行）；任何异常向上抛出由调用方转告警事件。"""
        now = occurred_at or datetime.utcnow()
        retention_days = (
            app_settings.inference_result_retention_days
            if retention_days is None else retention_days
        )
        record_count = len(records)
        predictions = result.get("predictions") or []
        probabilities = result.get("probabilities") or []
        scores = result.get("anomaly_score") or []
        anomaly_flags = result.get("is_anomaly") or []
        if result.get("thresholds") is not None:
            thresholds = result.get("thresholds") or []
        elif threshold is not None:
            thresholds = [threshold] * record_count
        else:
            thresholds = []
        context_rows = list(context_rows or [])
        if len(context_rows) != record_count:
            context_rows = context_rows + [ContextRow()] * (record_count - len(context_rows))

        # 日量计数（fail-open）：超限降级「只存异常 + 抽样」
        over_cap = False
        cap = app_settings.inference_result_daily_cap
        if cap and cap > 0:
            counter = self._counter_or_default()
            if counter is not None:
                try:
                    day_key = f"inference-result-count:{now:%Y%m%d}"
                    used = counter.incr(day_key)
                    if used == 1:
                        counter.expire(day_key, 86400)
                    over_cap = int(used) > int(cap)
                except Exception:
                    logger.warning("inference result daily counter unavailable; persist unrestricted")

        rows: list[InferenceResult] = []
        buckets: dict[tuple, dict] = {}
        expires_at = now + timedelta(days=retention_days)
        for index in range(record_count):
            context_row = context_rows[index] if index < len(context_rows) else ContextRow()
            prediction = _scalar(predictions[index]) if index < len(predictions) else None
            probability = _number(probabilities[index]) if index < len(probabilities) else None
            score = _number(scores[index]) if index < len(scores) else None
            is_anomaly = _bool(anomaly_flags[index]) if index < len(anomaly_flags) else None
            threshold = _number(thresholds[index]) if index < len(thresholds) else None
            condition_value = None
            if condition_values is not None and index < len(condition_values):
                raw_condition = condition_values[index]
                condition_value = str(raw_condition)[:128] if raw_condition is not None else None

            snapshot_uri = None
            take_detail = True
            if over_cap:
                # 降级：只存异常 + 抽样，正常样本只进聚合桶计数
                take_detail = bool(is_anomaly) or random.random() < self._sample_rate
            if take_detail:
                if is_anomaly or random.random() < self._sample_rate:
                    snapshot_uri = self._write_snapshot(
                        project_id=project_id,
                        request_id=request_id,
                        index=index,
                        record=records[index] if index < len(records) else {},
                        context_row=context_row,
                        prediction=prediction,
                        probability=probability,
                        score=score,
                        is_anomaly=is_anomaly,
                        threshold=threshold,
                        condition_value=condition_value,
                        occurred_at=now,
                    )
                rows.append(InferenceResult(
                    request_id=str(request_id)[:128],
                    sample_key=context_row.sample_key,
                    channel=channel,
                    project_id=project_id,
                    scene_id=context_row.scene_id,
                    station_id=context_row.station_id,
                    device_id=context_row.device_id,
                    condition_value=condition_value,
                    deployment_id=deployment_id,
                    revision_id=revision_id,
                    model_version_id=model_version_id,
                    predicted_label=str(prediction)[:128] if prediction is not None and isinstance(prediction, (str, int)) and not isinstance(prediction, bool) else None,
                    predicted_value=_number(prediction),
                    probability=probability,
                    anomaly_score=score,
                    is_anomaly=is_anomaly,
                    threshold=threshold,
                    batch_no=context_row.batch_no,
                    shift=context_row.shift,
                    product_code=context_row.product_code,
                    collected_at=context_row.collected_at,
                    extra=context_row.extra,
                    occurred_at=now,
                    expires_at=expires_at,
                    snapshot_uri=snapshot_uri,
                ))

            # 聚合桶（永久保留；demo 通道由调用方拦截不进桶）
            bucket_key = (
                now.replace(minute=0, second=0, microsecond=0),
                context_row.scene_id,
                context_row.station_id,
                condition_value,
            )
            stats = buckets.setdefault(bucket_key, {"total": 0, "ok": 0, "anomaly": 0, "score_sum": 0.0, "score_n": 0})
            stats["total"] += 1
            if is_anomaly:
                stats["anomaly"] += 1
            else:
                stats["ok"] += 1
            if score is not None:
                stats["score_sum"] += float(score)
                stats["score_n"] += 1

        for row in rows:
            row.project_id = project_id
        if rows:
            db_session = SessionLocal()
            try:
                db_session.add_all(rows)
                db_session.flush()
                for bucket_key, stats in buckets.items():
                    self._upsert_bucket(db_session, project_id=project_id, bucket_key=bucket_key, stats=stats, now=now)
                db_session.commit()
            except Exception:
                db_session.rollback()
                raise
            finally:
                db_session.close()
        elif buckets:
            # 仅桶计数（超限降级下的纯正常样本）：同样要落桶
            db_session = SessionLocal()
            try:
                for bucket_key, stats in buckets.items():
                    self._upsert_bucket(db_session, project_id=project_id, bucket_key=bucket_key, stats=stats, now=now)
                db_session.commit()
            except Exception:
                db_session.rollback()
                raise
            finally:
                db_session.close()

    def record_demo(
        self,
        *,
        db: Session,
        project_id,
        deployment_id=None,
        revision_id=None,
        model_version_id=None,
        predicted_label=None,
        probability=None,
        anomaly_score=None,
        is_anomaly=None,
        threshold=None,
        record: Mapping | None = None,
        occurred_at: datetime | None = None,
        retention_days: int | None = None,
    ) -> None:
        """演示链路（D13）：单行 channel='demo'，不进聚合桶；写失败只记日志
        （演示链路绝不因明细落库中断）。"""
        now = occurred_at or datetime.utcnow()
        retention_days = (
            app_settings.inference_result_retention_days
            if retention_days is None else retention_days
        )
        try:
            db.add(InferenceResult(
                request_id=f"demo-{uuid4().hex}",
                sample_key=None,
                channel="demo",
                project_id=project_id,
                deployment_id=deployment_id,
                revision_id=revision_id,
                model_version_id=model_version_id,
                predicted_label=str(predicted_label)[:128] if predicted_label is not None else None,
                predicted_value=_number(predicted_label),
                probability=probability,
                anomaly_score=anomaly_score,
                is_anomaly=is_anomaly,
                threshold=threshold,
                extra={"record": dict(record)} if record else None,
                occurred_at=now,
                expires_at=now + timedelta(days=retention_days),
            ))
            db.flush()
        except Exception:
            logger.exception("demo inference result persistence failed")

    def prune(self, db: Session, now: datetime | None = None) -> int:
        """保留期清理（每日 beat；聚合桶永久保留）。"""
        moment = now or datetime.utcnow()
        deleted = db.query(InferenceResult).filter(
            InferenceResult.expires_at <= moment,
        ).delete(synchronize_session="fetch")
        return int(deleted)

    # ------------------------------------------------------------------

    def _write_snapshot(self, *, project_id, request_id, index, record, context_row, prediction, probability, score, is_anomaly, threshold, condition_value, occurred_at) -> str | None:
        """完整快照（特征+context+结果）→ 对象存储；失败不影响明细落库。"""
        payload = {
            "request_id": str(request_id),
            "occurred_at": occurred_at.isoformat(),
            "record": dict(record),
            "context": context_row.extra or {},
            "sample_key": context_row.sample_key,
            "station_id": str(context_row.station_id) if context_row.station_id else None,
            "scene_id": str(context_row.scene_id) if context_row.scene_id else None,
            "batch_no": context_row.batch_no,
            "shift": context_row.shift,
            "product_code": context_row.product_code,
            "collected_at": context_row.collected_at.isoformat() if context_row.collected_at else None,
            "condition_value": condition_value,
            "result": {
                "predicted_label": prediction if isinstance(prediction, str) else None,
                "predicted_value": _number(prediction),
                "probability": probability,
                "anomaly_score": score,
                "is_anomaly": is_anomaly,
                "threshold": threshold,
            },
        }
        try:
            import tempfile
            from pathlib import Path

            storage = self._storage_or_default()
            date_key = f"{occurred_at:%Y-%m-%d}"
            with tempfile.NamedTemporaryFile(
                "w", suffix=".json", encoding="utf-8", delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=False, default=str)
                source = Path(handle.name)
            try:
                stored = storage.put_snapshot(
                    source, str(project_id), date_key,
                    _snapshot_filename(request_id, index),
                )
            finally:
                source.unlink(missing_ok=True)
            return stored.uri
        except StorageError:
            logger.warning("inference snapshot upload failed for request %s", request_id)
            return None
        except Exception:
            logger.exception("inference snapshot write failed for request %s", request_id)
            return None

    def _upsert_bucket(self, db: Session, *, project_id, bucket_key, stats, now) -> None:
        bucket_start, scene_id, station_id, condition_value = bucket_key
        score_increment = float(stats["score_sum"])
        score_count = int(stats["score_n"])
        bind = db.get_bind()
        # 快路径：键全非空时 PG 用唯一约束仲裁（先例 InferenceMetricBucket）
        if bind.dialect.name == "postgresql" and None not in (scene_id, station_id):
            db.execute(
                postgres_insert(InferenceResultBucket).values(
                    bucket_start=bucket_start,
                    project_id=project_id,
                    scene_id=scene_id,
                    station_id=station_id,
                    condition_value=condition_value,
                    total=stats["total"],
                    ok_count=stats["ok"],
                    anomaly_count=stats["anomaly"],
                    ng_confirmed_count=0,
                    avg_score=(score_increment / score_count) if score_count else None,
                    updated_at=now,
                ).on_conflict_do_update(
                    index_elements=[
                        InferenceResultBucket.bucket_start,
                        InferenceResultBucket.scene_id,
                        InferenceResultBucket.station_id,
                        InferenceResultBucket.condition_value,
                    ],
                    set_={
                        "total": InferenceResultBucket.total + stats["total"],
                        "ok_count": InferenceResultBucket.ok_count + stats["ok"],
                        "anomaly_count": InferenceResultBucket.anomaly_count + stats["anomaly"],
                        "avg_score": _avg_score_sql(score_increment, score_count),
                        "updated_at": now,
                    },
                ),
            )
            return
        # NULL 键组合在 PG 默认唯一约束下互异——SELECT→INSERT，读侧 SUM 兜底
        bucket = db.query(InferenceResultBucket).filter(
            InferenceResultBucket.bucket_start == bucket_start,
            InferenceResultBucket.scene_id.is_(None) if scene_id is None else InferenceResultBucket.scene_id == scene_id,
            InferenceResultBucket.station_id.is_(None) if station_id is None else InferenceResultBucket.station_id == station_id,
            InferenceResultBucket.condition_value.is_(None) if condition_value is None else InferenceResultBucket.condition_value == condition_value,
        ).with_for_update().first()
        if bucket is None:
            bucket = InferenceResultBucket(
                bucket_start=bucket_start,
                project_id=project_id,
                scene_id=scene_id,
                station_id=station_id,
                condition_value=condition_value,
                total=0, ok_count=0, anomaly_count=0, ng_confirmed_count=0,
                avg_score=None,
            )
            db.add(bucket)
            db.flush()
        total_after = bucket.total + stats["total"]
        score_n_after = score_count
        if bucket.avg_score is not None and bucket.total > 0:
            # 权重不重平衡坑：加权均值按行数展开，不按已有均值二次加权
            prior_sum = float(bucket.avg_score) * bucket.total
            prior_n = bucket.total
        else:
            prior_sum, prior_n = 0.0, 0
        bucket.avg_score = (
            (prior_sum + score_increment) / (prior_n + score_n_after)
            if (prior_n + score_n_after) else None
        )
        bucket.total = total_after
        bucket.ok_count = bucket.ok_count + stats["ok"]
        bucket.anomaly_count = bucket.anomaly_count + stats["anomaly"]
        bucket.updated_at = now


def _avg_score_sql(increment: float, count: int):
    """PG on_conflict 分支的加权均值：new = (old_avg*old_total + inc)/(old_total + count)。"""
    if count <= 0:
        return InferenceResultBucket.avg_score
    return case(
        (
            InferenceResultBucket.avg_score.isnot(None),
            (
                func.coalesce(InferenceResultBucket.avg_score, 0.0) * InferenceResultBucket.total + increment
            ) / (InferenceResultBucket.total + count),
        ),
        else_=(increment / count),
    )


def emit_persist_failed_event(db: Session, *, project_id, deployment_id, error_code: str) -> None:
    """落库失败→outbox 告警事件（D4）；推理响应不受影响。"""
    try:
        from app.services.notification_outbox import OutboxDomainEventRecorder

        OutboxDomainEventRecorder().record(
            db,
            create_domain_event(
                idempotency_key=f"inference-result-persist-failed:{uuid4().hex}",
                event_type="inference.result_persist_failed",
                severity="warning",
                occurred_at=datetime.utcnow(),
                project_id=project_id,
                actor_id=None,
                resource_type="inference_result",
                resource_id=None,
                payload={
                    "deployment_id": str(deployment_id) if deployment_id else None,
                    "error_code": str(error_code)[:128],
                },
            ),
        )
    except Exception:
        # 告警链路自身的失败绝不反噬调用方
        logger.exception("inference result persist-failed event recording failed")


def _scalar(value):
    if isinstance(value, (list, tuple)):
        return _scalar(value[0]) if value else None
    return value


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    return None
