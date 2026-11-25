"""Inference result query API（B1-16 生产记录查询，读走 project.read）.

- 明细分页查询：样本键 / 批次 / 工位 / 场景 / 时间窗 / 异常标记 / 通道筛选，
  默认排除 demo 通道（诚实设计⑥/D13）；
- 计数摘要：按聚合桶统计（读侧不扫明细），桶数字与明细化并口径一致
  （单测锁「桶数字 = 明细计数」）。
"""

import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.project_security import require_project_access
from app.database import get_db
from app.models.inference_result import InferenceResult, InferenceResultBucket
from app.models.user import User

router = APIRouter(tags=["inference_results"])

PAGE_LIMIT = 100


def _uuid_or_none(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(422, {"code": "INFERENCE_RESULT_TIME_INVALID"}) from None
    if parsed.tzinfo is not None:
        # 与明细写入同口径：归一 naive UTC（PG now() 时区比较坑）
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _result_out(item: InferenceResult) -> dict:
    return {
        "id": str(item.id),
        "request_id": item.request_id,
        "sample_key": item.sample_key,
        "channel": item.channel,
        "project_id": str(item.project_id),
        "scene_id": str(item.scene_id) if item.scene_id else None,
        "station_id": str(item.station_id) if item.station_id else None,
        "device_id": str(item.device_id) if item.device_id else None,
        "condition_value": item.condition_value,
        "deployment_id": str(item.deployment_id) if item.deployment_id else None,
        "revision_id": str(item.revision_id) if item.revision_id else None,
        "model_version_id": str(item.model_version_id) if item.model_version_id else None,
        "predicted_label": item.predicted_label,
        "predicted_value": item.predicted_value,
        "probability": item.probability,
        "anomaly_score": item.anomaly_score,
        "is_anomaly": item.is_anomaly,
        "threshold": item.threshold,
        "batch_no": item.batch_no,
        "shift": item.shift,
        "product_code": item.product_code,
        "collected_at": item.collected_at.isoformat() if item.collected_at else None,
        "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "alert_triggered": item.alert_triggered,
        "snapshot_uri": item.snapshot_uri,
        "source_uri": item.source_uri,
        "extra": item.extra,
    }


@router.get("/api/projects/{project_id}/inference-results")
def list_inference_results(
    project_id: UUID,
    sample_key: str | None = None,
    batch_no: str | None = None,
    station_id: str | None = None,
    scene_id: str | None = None,
    occurred_from: str | None = None,
    occurred_to: str | None = None,
    is_anomaly: bool | None = None,
    channel: str | None = Query(default=None, pattern="^(online|batch|shadow|replay|demo)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=PAGE_LIMIT),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    query = db.query(InferenceResult).filter(InferenceResult.project_id == project_id)
    # 演示隔离（D13）：默认排除 demo；显式 channel='demo' 才看演示数据
    if channel is None:
        query = query.filter(InferenceResult.channel != "demo")
    else:
        query = query.filter(InferenceResult.channel == channel)
    if sample_key:
        query = query.filter(InferenceResult.sample_key == sample_key)
    if batch_no:
        query = query.filter(InferenceResult.batch_no == batch_no)
    station_uuid = _uuid_or_none(station_id)
    if station_id:
        if station_uuid is None:
            raise HTTPException(422, {"code": "INFERENCE_RESULT_FILTER_INVALID"})
        query = query.filter(InferenceResult.station_id == station_uuid)
    scene_uuid = _uuid_or_none(scene_id)
    if scene_id:
        if scene_uuid is None:
            raise HTTPException(422, {"code": "INFERENCE_RESULT_FILTER_INVALID"})
        query = query.filter(InferenceResult.scene_id == scene_uuid)
    occurred_from_at = _parse_datetime(occurred_from)
    occurred_to_at = _parse_datetime(occurred_to)
    if occurred_from_at is not None:
        query = query.filter(InferenceResult.occurred_at >= occurred_from_at)
    if occurred_to_at is not None:
        query = query.filter(InferenceResult.occurred_at <= occurred_to_at)
    if is_anomaly is not None:
        query = query.filter(InferenceResult.is_anomaly.is_(bool(is_anomaly)))
    total = query.count()
    items = (
        query.order_by(InferenceResult.occurred_at.desc(), InferenceResult.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"items": [_result_out(item) for item in items], "total": total, "page": page, "page_size": page_size}


@router.get("/api/projects/{project_id}/inference-results/summary")
def inference_results_summary(
    project_id: UUID,
    scene_id: str | None = None,
    occurred_from: str | None = None,
    occurred_to: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """按聚合桶的计数摘要（读桶不扫明细；聚合本就默认无 demo 通道）。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    now = datetime.utcnow()
    occurred_from_at = _parse_datetime(occurred_from) or (now - timedelta(hours=24))
    occurred_to_at = _parse_datetime(occurred_to) or now
    query = (
        db.query(
            InferenceResultBucket.bucket_start,
            sa_func.coalesce(sa_func.sum(InferenceResultBucket.total), 0),
            sa_func.coalesce(sa_func.sum(InferenceResultBucket.ok_count), 0),
            sa_func.coalesce(sa_func.sum(InferenceResultBucket.anomaly_count), 0),
            sa_func.avg(InferenceResultBucket.avg_score),
        )
        .filter(
            InferenceResultBucket.project_id == project_id,
            InferenceResultBucket.bucket_start >= occurred_from_at,
            InferenceResultBucket.bucket_start <= occurred_to_at,
        )
        .group_by(InferenceResultBucket.bucket_start)
        .order_by(InferenceResultBucket.bucket_start.asc())
    )
    scene_uuid = _uuid_or_none(scene_id)
    if scene_id:
        if scene_uuid is None:
            raise HTTPException(422, {"code": "INFERENCE_RESULT_FILTER_INVALID"})
        query = query.filter(InferenceResultBucket.scene_id == scene_uuid)
    rows = query.all()
    buckets = [
        {
            "bucket_start": row[0].isoformat() if row[0] else None,
            "total": int(row[1] or 0),
            "ok_count": int(row[2] or 0),
            "anomaly_count": int(row[3] or 0),
            "avg_score": float(row[4]) if row[4] is not None else None,
        }
        for row in rows
    ]
    return {
        "from": occurred_from_at.isoformat(),
        "to": occurred_to_at.isoformat(),
        "total": sum(bucket["total"] for bucket in buckets),
        "ok_count": sum(bucket["ok_count"] for bucket in buckets),
        "anomaly_count": sum(bucket["anomaly_count"] for bucket in buckets),
        "buckets": buckets,
    }
