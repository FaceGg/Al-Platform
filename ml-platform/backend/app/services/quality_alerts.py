"""Quality alert engine & disposition services (补齐路线第一批 F2a).

预警中心与处置工作台的服务层（技术方案 §9.2–§9.6，D14–D22）：
- 规则解析：场景 alert_settings 覆盖平台默认（触发下限独立于分级阈值）。
- create_alert：同因合并（E20/D15）——同合并键、未关闭且仍接受合并的预警，
  在合并窗口内只增计数并追加 occurred 轨迹（轨迹里保留每次发生的明细）。
- evaluate_inference_alerts：推理落库任务内的两类来源产生器
  （model_risk 越触发阈值或模型判异 / param_exceed 越规格），命中行回写
  inference_results.alert_triggered + alert_id。
- 判据链（B1-02 竞品口径可复算）：规格超限 → 3σ → 2σ → 基线偏离 30%；
  σ 级判据绑定冻结基线，无基线显式 skipped。
- 基线冻结（E08 前移）：数值由服务端从数据集版本的稳定时段取出，
  I-MR 口径（中心=均值、σ=平均移动极差/1.128），20–500 样本、恒定拒绝、
  版本化，引用窗口（数据集版本与首末样本）可追溯。
- 处置单快照（E07）：当时生效的 SOP 版本、SPC 基线版本、模型版本。
- SLA beat（D21）与设备心跳 beat（D16）。
- 演示循环并入（C14/D18）与误报回流复核任务（C13/D22）。

事务约定：产生与处置函数不 commit（由调用方决定事务边界）；beat 任务体
自带 commit。预警评估自身的失败绝不反噬调用方的主链路。
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.events.domain import create_domain_event
from app.models.data_version import DatasetSample, DatasetVersion
from app.models.inference_result import InferenceResult, InferenceResultBucket
from app.models.quality_alerts import (
    ALERT_EVENT_ACTIONS,
    ALERT_RESOLUTIONS,
    ALERT_SEVERITIES,
    ALERT_SOURCE_TYPES,
    ALERT_STATUS_FLOW,
    ALERT_STATUSES,
    QualityAlert,
    QualityAlertEvent,
    QualitySop,
    QualitySpcBaseline,
)
from app.models.quality_domain import QualityScene, QualitySpecLimit, QualityStation
from app.services.notification_outbox import OutboxDomainEventRecorder
from app.services.quality_aggregates import OPEN_STATUSES

logger = logging.getLogger(__name__)

# 设备离线判定阈值：与 api/compute.py 的心跳口径一致
# （COMPUTE_HEARTBEAT_STALE_SECONDS，默认 180s，下限 30s）
_HEARTBEAT_STALE_SECONDS = max(30, int(os.getenv("COMPUTE_HEARTBEAT_STALE_SECONDS", "180")))

# SLA 临期档：剩余时长 ≤ 总时长的 25%
_SLA_DUE_RATIO = 0.25

# 基线冻结的样本量窗口（E08：20–500 个样本）
BASELINE_MIN_SAMPLES = 20
BASELINE_MAX_SAMPLES = 500

_SEVERITY_RANK = {"warning": 0, "high": 1, "critical": 2}

# 预警规则键（D14）
ALERT_SETTING_KEYS = (
    "trigger_threshold",
    "high_threshold",
    "critical_threshold",
    "sla_hours",
    "merge_window_minutes",
)


class AlertTransitionError(ValueError):
    """非法阶段流转（流转图外跳转 / 终态 / 缺责任人 / 缺关闭结论）。"""


def _utcnow() -> datetime:
    return datetime.utcnow()


def resolve_alert_settings(scene: QualityScene | None) -> dict:
    """场景 alert_settings 覆盖平台默认（D14）；未配置的键取平台默认。"""
    resolved = {
        "trigger_threshold": float(app_settings.quality_alert_trigger_threshold),
        "high_threshold": float(app_settings.quality_alert_high_threshold),
        "critical_threshold": float(app_settings.quality_alert_critical_threshold),
        "sla_hours": int(app_settings.quality_alert_sla_hours),
        "merge_window_minutes": int(app_settings.quality_alert_merge_window_minutes),
    }
    if scene is not None and scene.alert_settings:
        for key, value in dict(scene.alert_settings).items():
            if key in resolved and value is not None:
                try:
                    resolved[key] = type(resolved[key])(value)
                except (TypeError, ValueError):
                    logger.warning("alert_settings.%s 不可解析，保留默认", key)
    return resolved


def validate_alert_settings(settings_map: Mapping[str, Any]) -> None:
    """校验合并平台默认后的完整规则：阈值次序触发 ≤ 高 ≤ 严重。

    只校验请求体里的值不够——场景只改「高」档时，它仍须不低于平台默认的
    触发下限，否则会出现「高分级阈值低于触发阈值」的矛盾配置。
    """
    trigger = float(settings_map["trigger_threshold"])
    high = float(settings_map["high_threshold"])
    critical = float(settings_map["critical_threshold"])
    if not trigger <= high <= critical:
        raise ValueError("ALERT_THRESHOLD_ORDER_INVALID（须满足 触发 ≤ 高 ≤ 严重）")


def severity_for_score(score: float, thresholds: Mapping[str, float]) -> str:
    """风险分级：≥严重阈值→critical；≥高阈值→high；否则 warning。

    触发（score ≥ trigger_threshold）先于分级判定；本函数只管已触发样本。
    """
    if score >= thresholds["critical_threshold"]:
        return "critical"
    if score >= thresholds["high_threshold"]:
        return "high"
    return "warning"


def append_event(
    db: Session,
    alert: QualityAlert,
    action: str,
    *,
    actor_id=None,
    from_status: str | None = None,
    to_status: str | None = None,
    note: str | None = None,
    form_snapshot: dict | None = None,
    snapshot: dict | None = None,
    created_at: datetime | None = None,
) -> QualityAlertEvent:
    """追加处置轨迹（不 commit）。action 必须在枚举内（CHECK 双保险）。

    同一预警的轨迹时间戳严格递增：调用方常在同一次处置里用同一个 now 连写
    多条轨迹（流转 + 处置提交），只靠 created_at 排序时先后是不确定的。
    """
    if action not in ALERT_EVENT_ACTIONS:
        raise ValueError(f"Unknown alert event action: {action}")
    created_at = created_at or _utcnow()
    latest = (
        db.query(QualityAlertEvent.created_at)
        .filter(QualityAlertEvent.alert_id == alert.id)
        .order_by(QualityAlertEvent.created_at.desc())
        .first()
    )
    if latest is not None and created_at <= latest[0]:
        created_at = latest[0] + timedelta(microseconds=1)
    event = QualityAlertEvent(
        alert_id=alert.id,
        action=action,
        from_status=from_status,
        to_status=to_status,
        actor_id=actor_id,
        note=note,
        form_snapshot=form_snapshot,
        snapshot=snapshot,
        created_at=created_at,
    )
    db.add(event)
    return event


def _same_scope_filters(scene_id, station_id, device_id, condition_value, is_demo: bool):
    """「同因」的归属口径：场景 / 工位 / 设备 / 工况 / 演示标记全部一致。

    NULL 键用 is_ 精确匹配——SQL 的三值逻辑会让 `col = NULL` 永假，
    也会让两个 NULL 行互不相等，都会造成漏合并。
    """
    return (
        QualityAlert.scene_id.is_(None) if scene_id is None
        else QualityAlert.scene_id == scene_id,
        QualityAlert.station_id.is_(None) if station_id is None
        else QualityAlert.station_id == station_id,
        QualityAlert.device_id.is_(None) if device_id is None
        else QualityAlert.device_id == device_id,
        QualityAlert.condition_value.is_(None) if condition_value is None
        else QualityAlert.condition_value == condition_value,
        QualityAlert.is_demo.is_(bool(is_demo)),
    )


def create_alert(
    db: Session,
    *,
    project_id,
    merge_key: str,
    source_type: str,
    title: str,
    severity: str = "warning",
    scene_id=None,
    station_id=None,
    device_id=None,
    condition_value: str | None = None,
    risk_score: float | None = None,
    sample_key: str | None = None,
    batch_no: str | None = None,
    product_code: str | None = None,
    evidence: dict | None = None,
    source_ref: dict | None = None,
    is_demo: bool = False,
    actor_id=None,
    alert_settings: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> tuple[QualityAlert, bool]:
    """产生一条预警；同因预警在合并窗口内只增计数（E20/D15）。

    同因 = 同项目 + 同合并键 + 同归属（场景/工位/设备/工况/演示标记）。
    合并键由调用方给出，须包含区分「原因」的因子（来源类型、参数超限的
    字段名、模型部署等）——否则两个不同参数同时超限会被并成一条。
    返回 (alert, created)；合并路径 created=False，只追加 occurred 轨迹。
    """
    if source_type not in ALERT_SOURCE_TYPES:
        raise ValueError(f"Unknown alert source type: {source_type}")
    if severity not in ALERT_SEVERITIES:
        raise ValueError(f"Unknown alert severity: {severity}")
    if not merge_key:
        raise ValueError("merge_key is required")
    now = now or _utcnow()
    settings_map = dict(alert_settings or {})
    window_minutes = int(
        settings_map.get("merge_window_minutes")
        or app_settings.quality_alert_merge_window_minutes
    )
    window_start = now - timedelta(minutes=window_minutes)

    existing = (
        db.query(QualityAlert)
        .filter(
            QualityAlert.project_id == project_id,
            QualityAlert.merge_key == str(merge_key)[:256],
            QualityAlert.merge_open.is_(True),
            QualityAlert.status != "closed",
            QualityAlert.last_event_at >= window_start,
            *_same_scope_filters(
                scene_id, station_id, device_id, condition_value, is_demo
            ),
        )
        .order_by(QualityAlert.last_event_at.desc())
        .first()
    )
    if existing is not None:
        existing.occurrence_count = int(existing.occurrence_count or 1) + 1
        existing.last_event_at = now
        existing.updated_at = now
        # 严重级别只升不降：组内出现过更严重的一次，整组按最严重的显示
        if _SEVERITY_RANK[severity] > _SEVERITY_RANK.get(existing.severity, 0):
            existing.severity = severity
        append_event(
            db, existing, "occurred", actor_id=actor_id, created_at=now,
            # 每次发生的明细留在轨迹里，组内展开时有据可查
            form_snapshot={
                "sample_key": sample_key,
                "risk_score": risk_score,
                "evidence": dict(evidence or {}),
            },
        )
        return existing, False

    sla_hours = int(
        settings_map.get("sla_hours") or app_settings.quality_alert_sla_hours
    )
    alert = QualityAlert(
        project_id=project_id,
        scene_id=scene_id,
        station_id=station_id,
        device_id=device_id,
        condition_value=condition_value,
        source_type=source_type,
        risk_score=risk_score,
        severity=severity,
        title=str(title)[:256],
        sample_key=sample_key,
        batch_no=batch_no,
        product_code=product_code,
        evidence=dict(evidence or {}),
        source_ref=dict(source_ref) if source_ref else None,
        status="open",
        sla_due_at=now + timedelta(hours=sla_hours),
        occurrence_count=1,
        merge_key=str(merge_key)[:256],
        merge_open=True,
        last_event_at=now,
        is_demo=is_demo,
        created_at=now,
        updated_at=now,
    )
    db.add(alert)
    db.flush()
    append_event(db, alert, "created", actor_id=actor_id, created_at=now)
    return alert, True


def evaluate_inference_alerts(
    db: Session,
    pairs: Sequence[tuple[InferenceResult, Mapping]],
    *,
    now: datetime | None = None,
) -> list[QualityAlert]:
    """推理落库后的两类预警来源产生器（D19，技术方案 §9.2）。

    pairs 是成对的（明细行, 该行特征记录）。调用方必须在构造明细行的同一
    次遍历里配对——日量超限时正常样本会被跳过，只传两个平行序列会错位。

    - model_risk：有监督概率 / 无监督异常分数 ≥ 触发阈值，或无监督模型
      直接判异（异常分数的量纲因族而异，不能只靠固定阈值比较）；severity
      按 D14 阈值映射；命中行回写 alert_triggered + alert_id。
    - param_exceed：特征值越过场景规格（statistic='value' 的 USL/LSL）；
      证据存实测值与规格快照。波形统计量规格（statistic≠'value'）随接入
      通道保存波形原文后生效，此处不评（诚实登记）。

    只评 online/batch 通道（shadow/replay 是对照与回放，不产生业务预警；
    demo 走 relay_demo_alert 单独投递）。调用方负责 commit 与异常兜底。
    """
    now = now or _utcnow()
    created: list[QualityAlert] = []
    eligible = [
        (row, record) for row, record in pairs
        if (row.channel or "online") in ("online", "batch")
    ]
    if not eligible:
        return created

    scene_ids = {row.scene_id for row, _ in eligible if row.scene_id is not None}
    scenes: dict[Any, QualityScene] = {}
    specs_by_scene: dict[Any, list] = {}
    # 冻结基线（F4/D37）：有基线的字段做 3σ 判定，越限即产生 spc_violation 预警；
    # 没有冻结基线的字段不产生 σ 类预警（与判据链口径一致）
    baselines_by_scene: dict[Any, list] = {}
    if scene_ids:
        scenes = {
            scene.id: scene
            for scene in db.query(QualityScene).filter(QualityScene.id.in_(scene_ids)).all()
        }
        for spec in (
            db.query(QualitySpecLimit)
            .filter(QualitySpecLimit.scene_id.in_(scene_ids))
            .all()
        ):
            specs_by_scene.setdefault(spec.scene_id, []).append(spec)
        for baseline in (
            db.query(QualitySpcBaseline)
            .filter(
                QualitySpcBaseline.scene_id.in_(scene_ids),
                QualitySpcBaseline.is_active.is_(True),
                QualitySpcBaseline.statistic == "value",
            )
            .all()
        ):
            baselines_by_scene.setdefault(baseline.scene_id, []).append(baseline)
    settings_cache: dict[Any, dict] = {}

    for row, record in eligible:
        record = record if isinstance(record, Mapping) else {}
        if row.scene_id not in settings_cache:
            settings_cache[row.scene_id] = resolve_alert_settings(scenes.get(row.scene_id))
        settings_map = settings_cache[row.scene_id]
        common = dict(
            scene_id=row.scene_id,
            station_id=row.station_id,
            device_id=row.device_id,
            condition_value=row.condition_value,
            sample_key=row.sample_key,
            batch_no=row.batch_no,
            product_code=row.product_code,
            source_ref={
                "kind": "inference_result",
                "id": str(row.id),
                "request_id": row.request_id,
            },
            alert_settings=settings_map,
            now=now,
        )
        occurred_at = row.occurred_at.isoformat() if row.occurred_at else now.isoformat()

        # —— model_risk ——
        score = row.probability if row.probability is not None else row.anomaly_score
        is_unsupervised = row.probability is None and row.anomaly_score is not None
        flagged_by_model = bool(is_unsupervised and row.is_anomaly)
        over_threshold = score is not None and float(score) >= float(
            settings_map["trigger_threshold"]
        )
        if flagged_by_model or over_threshold:
            score_value = float(score) if score is not None else None
            score_kind = "probability" if row.probability is not None else "anomaly_score"
            if score_value is not None and 0.0 <= score_value <= 1.0:
                severity = severity_for_score(score_value, settings_map)
            else:
                severity = "high"
            alert, was_created = create_alert(
                db,
                project_id=row.project_id,
                merge_key=f"model_risk:deployment={row.deployment_id}",
                source_type="model_risk",
                title=(
                    f"模型风险：{score_kind}={score_value:.3f} 越过触发阈值"
                    if over_threshold else "模型风险：模型判定样本异常"
                ) + (f"（样本 {row.sample_key}）" if row.sample_key else ""),
                severity=severity,
                risk_score=score_value,
                evidence={
                    "kind": "model_risk",
                    "score_kind": score_kind,
                    "score": score_value,
                    # 触发依据：阈值比较 / 模型判异 / 两者皆命中
                    "rule": (
                        "threshold+is_anomaly" if flagged_by_model and over_threshold
                        else "is_anomaly" if flagged_by_model
                        else "threshold"
                    ),
                    "trigger_threshold": float(settings_map["trigger_threshold"]),
                    "severity_thresholds": {
                        "high": float(settings_map["high_threshold"]),
                        "critical": float(settings_map["critical_threshold"]),
                    },
                    "model_version_id": (
                        str(row.model_version_id) if row.model_version_id else None
                    ),
                    # 预测的类别标签（无监督模型为空）：F3 缺陷帕累托按它经 NG 词表归并
                    "predicted_label": (
                        str(row.predicted_label)[:128]
                        if row.predicted_label is not None else None
                    ),
                    "occurred_at": occurred_at,
                },
                **common,
            )
            row.alert_triggered = True
            row.alert_id = alert.id
            if was_created:
                created.append(alert)

        # —— param_exceed（数值特征 vs 规格）——
        for spec in specs_by_scene.get(row.scene_id) or ():
            if spec.statistic != "value":
                continue
            raw = record.get(spec.field)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            value = float(raw)
            above = spec.usl is not None and value > float(spec.usl)
            below = spec.lsl is not None and value < float(spec.lsl)
            if not (above or below):
                continue
            alert, was_created = create_alert(
                db,
                project_id=row.project_id,
                # 合并键含字段名：不同参数超限是不同的「因」，不得并成一条
                merge_key=f"param_exceed:field={spec.field}",
                source_type="param_exceed",
                title=f"参数超限：{spec.field}={value:g} "
                + ("超上限" if above else "低于下限")
                + (f"（样本 {row.sample_key}）" if row.sample_key else ""),
                severity="high",
                evidence={
                    "kind": "param_exceed",
                    "field": spec.field,
                    "statistic": "value",
                    "recorded_value": value,
                    "spec": {
                        "id": str(spec.id),
                        "usl": spec.usl,
                        "lsl": spec.lsl,
                        "target": spec.target,
                        "unit": spec.unit,
                    },
                    "occurred_at": occurred_at,
                },
                **common,
            )
            row.alert_triggered = True
            if row.alert_id is None:
                row.alert_id = alert.id
            if was_created:
                created.append(alert)

        # —— spc_violation：越冻结基线控制限（中心 ± 3σ）——
        for baseline in _baselines_for_row(
            baselines_by_scene.get(row.scene_id) or [], row.station_id, row.condition_value,
        ):
            raw = record.get(baseline.field)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            value = float(raw)
            sigma = float(baseline.sigma)
            if sigma <= 0 or abs(value - baseline.center) <= 3 * sigma:
                continue
            alert, was_created = create_alert(
                db,
                project_id=row.project_id,
                merge_key=f"spc:3sigma:{baseline.field}",
                source_type="spc_violation",
                title=f"SPC 判异：{baseline.field}={value:g} 越出冻结基线控制限"
                + (f"（样本 {row.sample_key}）" if row.sample_key else ""),
                severity="high",
                # 归属（场景 / 工位 / 设备 / 工况 / 样本键）由 common 统一带入，不重复传
                evidence={
                    "kind": "spc_violation",
                    "rule": "3sigma",
                    "field": baseline.field,
                    "recorded_value": value,
                    "center": baseline.center,
                    "sigma": baseline.sigma,
                    "baseline": {"id": str(baseline.id), "version": int(baseline.version or 1)},
                    "model_version_id": (
                        str(row.model_version_id) if row.model_version_id else None
                    ),
                    "occurred_at": occurred_at,
                },
                **common,
            )
            row.alert_triggered = True
            if row.alert_id is None:
                row.alert_id = alert.id
            if was_created:
                created.append(alert)

    return created


def _baselines_for_row(candidates, station_id, condition_value) -> list:
    """从场景的活动基线里，为每个字段挑出与该行归属最匹配的一条。

    匹配分：基线的工位 / 工况为空表示适用全部；与该行不同则不适用。
    """
    best: dict[str, tuple[int, Any]] = {}
    for baseline in candidates:
        score = 0
        if baseline.station_id is None:
            score += 2
        elif baseline.station_id == station_id:
            score += 3
        else:
            continue
        if baseline.condition_value is None:
            score += 1
        elif baseline.condition_value == condition_value:
            score += 2
        else:
            continue
        current = best.get(baseline.field)
        if current is None or score > current[0]:
            best[baseline.field] = (score, baseline)
    return [item[1] for item in best.values()]


# ----------------------------------------------------------------------
# 判据链与 SPC 基线冻结（B1-02 / E08）
# ----------------------------------------------------------------------

def compute_i_mr(values: Sequence[float]) -> tuple[float, float]:
    """I-MR 口径：中心=均值，σ=平均移动极差/1.128（E08）。"""
    if len(values) < 2:
        raise ValueError("I-MR 至少需要 2 个样本")
    count = len(values)
    center = sum(values) / count
    moving_ranges = [
        abs(values[index] - values[index - 1]) for index in range(1, count)
    ]
    sigma = (sum(moving_ranges) / len(moving_ranges)) / 1.128
    return center, sigma


def _parse_time(value) -> datetime | None:
    """把样本里的时间值归一成不带时区的 UTC；解析不了返回 None。"""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is None else value.astimezone(
            timezone.utc
        ).replace(tzinfo=None)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed.astimezone(
            timezone.utc
        ).replace(tzinfo=None)
    return None


def collect_baseline_values(
    db: Session,
    *,
    dataset_version: DatasetVersion,
    field: str,
    condition_column: str | None = None,
    condition_value: str | None = None,
    time_column: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    row_index_from: int | None = None,
    row_index_to: int | None = None,
) -> tuple[list[float], dict]:
    """从数据集版本按行序取稳定时段的某字段数值（E08「已结束的稳定时段」）。

    - 行号范围在 SQL 侧过滤（row_index 是普通整数列，可走索引）；
    - 工况值与时间窗在 Python 侧过滤（样本值是 JSON，两个方言的 JSON
      函数不通用，不为此写两套 SQL）；
    - 命中样本超过 BASELINE_MAX_SAMPLES 即报错，让调用方缩小范围——
      静默截断会得到一个与请求窗口不符的基线。

    返回 (按行序排列的数值, 引用窗口 {first, last})，first/last 是首末样本的
    (sample_id, row_index)，供基线复算与追溯。
    """
    query = db.query(DatasetSample).filter(
        DatasetSample.dataset_version_id == dataset_version.id
    )
    if row_index_from is not None:
        query = query.filter(DatasetSample.row_index >= int(row_index_from))
    if row_index_to is not None:
        query = query.filter(DatasetSample.row_index <= int(row_index_to))
    query = query.order_by(DatasetSample.row_index.asc(), DatasetSample.id.asc())
    values: list[float] = []
    reference: dict = {"first": None, "last": None}
    for sample in query.yield_per(2000):
        row = sample.values or {}
        if condition_column and condition_value is not None:
            if str(row.get(condition_column)) != str(condition_value):
                continue
        if time_column and (time_from is not None or time_to is not None):
            stamp = _parse_time(row.get(time_column))
            if stamp is None:
                continue
            if time_from is not None and stamp < time_from:
                continue
            if time_to is not None and stamp > time_to:
                continue
        raw = row.get(field)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        marker = {"sample_id": str(sample.sample_id), "row_index": int(sample.row_index)}
        if reference["first"] is None:
            reference["first"] = marker
        reference["last"] = marker
        values.append(float(raw))
        if len(values) > BASELINE_MAX_SAMPLES:
            raise ValueError(
                "SPC_BASELINE_TOO_MANY_SAMPLES（窗口内样本超过 500，请缩小范围）"
            )
    return values, reference


def freeze_baseline(
    db: Session,
    *,
    project_id,
    scene_id,
    field: str,
    values: Sequence[float],
    statistic: str = "value",
    station_id=None,
    condition_value: str | None = None,
    reference: Mapping[str, Any] | None = None,
    window_start=None,
    window_end=None,
    actor_id=None,
) -> QualitySpcBaseline:
    """冻结 SPC 基线（E08）：统一 I-MR 计算与校验，版本化并失效同键旧版本。

    规则：样本数 20–500；时段内数值恒定（平均移动极差为 0）拒绝；
    重新冻结生成新版本并把同键旧版本置为失效（旧行保留可查）。
    """
    cleaned = [float(value) for value in values]
    if not BASELINE_MIN_SAMPLES <= len(cleaned) <= BASELINE_MAX_SAMPLES:
        raise ValueError(
            f"SPC_BASELINE_SAMPLE_COUNT_INVALID（需 {BASELINE_MIN_SAMPLES}–"
            f"{BASELINE_MAX_SAMPLES} 个样本，实际 {len(cleaned)}）"
        )
    center, sigma = compute_i_mr(cleaned)
    if sigma <= 0:
        raise ValueError("SPC_BASELINE_CONSTANT_WINDOW（时段内数值恒定，无法冻结）")
    now = _utcnow()
    same_key = db.query(QualitySpcBaseline).filter(
        QualitySpcBaseline.scene_id == scene_id,
        QualitySpcBaseline.field == field,
        QualitySpcBaseline.statistic == statistic,
        QualitySpcBaseline.station_id.is_(None) if station_id is None
        else QualitySpcBaseline.station_id == station_id,
        QualitySpcBaseline.condition_value.is_(None) if condition_value is None
        else QualitySpcBaseline.condition_value == condition_value,
    )
    previous = same_key.order_by(QualitySpcBaseline.version.desc()).first()
    same_key.update({"is_active": False}, synchronize_session=False)
    baseline = QualitySpcBaseline(
        project_id=project_id,
        scene_id=scene_id,
        station_id=station_id,
        condition_value=condition_value,
        field=field,
        statistic=statistic,
        center=center,
        sigma=sigma,
        sample_count=len(cleaned),
        window_start=window_start or now,
        window_end=window_end or now,
        reference=dict(reference or {}),
        version=(int(previous.version or 0) + 1) if previous else 1,
        is_active=True,
        created_by_id=actor_id,
        created_at=now,
    )
    db.add(baseline)
    db.flush()
    return baseline


def find_active_baseline(
    db: Session, *, scene_id, station_id, condition_value, field: str
) -> QualitySpcBaseline | None:
    """按「工位+工况精确 → 工位级 → 工况级 → 场景级」回退查找活动基线。"""
    for candidate_station, candidate_condition in (
        (station_id, condition_value),
        (station_id, None),
        (None, condition_value),
        (None, None),
    ):
        baseline = (
            db.query(QualitySpcBaseline)
            .filter(
                QualitySpcBaseline.scene_id == scene_id,
                QualitySpcBaseline.field == field,
                QualitySpcBaseline.is_active.is_(True),
                QualitySpcBaseline.station_id.is_(None) if candidate_station is None
                else QualitySpcBaseline.station_id == candidate_station,
                QualitySpcBaseline.condition_value.is_(None) if candidate_condition is None
                else QualitySpcBaseline.condition_value == candidate_condition,
            )
            .order_by(QualitySpcBaseline.version.desc())
            .first()
        )
        if baseline is not None:
            return baseline
    return None


def evaluate_criteria_chain(db: Session, alert: QualityAlert) -> list[dict]:
    """判据优先级链复算（B1-02，D20 口径）：

    规格超限 → 3σ 超限 → 2σ 偏离 → 基线偏离 30%。
    - 规格读**当前** quality_spec_limits（路线验收：修改规格后判据同步变化）；
    - σ 级判据绑定冻结基线；没有冻结基线的工位或工况，三级 σ 判据显式
      skipped 并提示「仅规格判据可用」（路线 B1-02〔规划〕）；
    - 非数值样本（无实测值）相关判据 skipped。
    """
    evidence = dict(alert.evidence or {})
    value = evidence.get("recorded_value")
    if value is None and evidence.get("kind") == "model_risk":
        value = evidence.get("score")
    value = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    field = evidence.get("field")
    chain: list[dict] = []
    sigma_criteria = ("sigma_3", "sigma_2", "baseline_deviation_30")

    # ① 规格超限（读当前规格）
    spec = None
    if alert.scene_id and field and value is not None:
        spec = (
            db.query(QualitySpecLimit)
            .filter(
                QualitySpecLimit.scene_id == alert.scene_id,
                QualitySpecLimit.field == field,
                QualitySpecLimit.statistic == "value",
            )
            .first()
        )
    if spec is None:
        chain.append({
            "criterion": "spec_exceed", "status": "skipped",
            "detail": "该字段无规格定义，或预警无字段/数值上下文",
        })
    else:
        above = spec.usl is not None and value > float(spec.usl)
        below = spec.lsl is not None and value < float(spec.lsl)
        chain.append({
            "criterion": "spec_exceed",
            "status": "hit" if (above or below) else "pass",
            "detail": {
                "value": value, "usl": spec.usl, "lsl": spec.lsl,
                "unit": spec.unit, "spec_id": str(spec.id),
            },
        })

    # ②③④ σ 级判据（绑定冻结基线）
    if alert.scene_id is None or field is None or value is None:
        for criterion in sigma_criteria:
            chain.append({"criterion": criterion, "status": "skipped",
                          "detail": "无场景/字段/数值上下文"})
        return chain
    baseline = find_active_baseline(
        db, scene_id=alert.scene_id, station_id=alert.station_id,
        condition_value=alert.condition_value, field=field,
    )
    if baseline is None:
        for criterion in sigma_criteria:
            chain.append({"criterion": criterion, "status": "skipped",
                          "detail": "未冻结基线，仅规格判据可用"})
        return chain
    deviation = value - baseline.center
    sigma = float(baseline.sigma)
    baseline_ref = {"id": str(baseline.id), "version": baseline.version}
    chain.append({
        "criterion": "sigma_3",
        "status": "hit" if abs(deviation) > 3 * sigma else "pass",
        "detail": {"value": value, "center": baseline.center, "sigma": sigma,
                   "baseline": baseline_ref},
    })
    chain.append({
        "criterion": "sigma_2",
        "status": "hit" if abs(deviation) > 2 * sigma else "pass",
        "detail": {"value": value, "center": baseline.center, "sigma": sigma,
                   "baseline": baseline_ref},
    })
    ratio = abs(deviation) / abs(baseline.center) if baseline.center else None
    chain.append({
        "criterion": "baseline_deviation_30",
        "status": "skipped" if ratio is None else ("hit" if ratio >= 0.30 else "pass"),
        "detail": {"value": value, "center": baseline.center,
                   "deviation_ratio": ratio, "baseline": baseline_ref},
    })
    return chain


# ----------------------------------------------------------------------
# 处置单快照（E07）与处置流转
# ----------------------------------------------------------------------

def build_disposition_snapshot(db: Session, alert: QualityAlert) -> dict:
    """处置单快照三要素（E07）：当时生效的 SOP 版本 / SPC 基线 / 模型版本。

    「当时生效」口径：SOP 取该场景与工况下所有未退役版本（可能有多个编号，
    全部记录而不是任意挑一个）；基线取判据字段按回退顺序找到的活动版本；
    模型取预警来源里的模型版本。快照落库后不可变——后续 SOP、基线、模型的
    变更都不改写已提交的处置单（路线 B1-02 验收）。
    """
    from uuid import UUID

    from app.models.model_registry import ModelVersion

    now = _utcnow()
    evidence = dict(alert.evidence or {})
    sops: list[dict] = []
    if alert.project_id:
        sop_query = db.query(QualitySop).filter(
            QualitySop.project_id == alert.project_id,
            QualitySop.effective_from <= now,
            or_(QualitySop.retired_at.is_(None), QualitySop.retired_at > now),
        )
        if alert.scene_id:
            sop_query = sop_query.filter(
                or_(QualitySop.scene_id.is_(None), QualitySop.scene_id == alert.scene_id)
            )
        else:
            # 预警不属于任何场景：只有项目级 SOP（scene_id 为空）适用
            sop_query = sop_query.filter(QualitySop.scene_id.is_(None))
        if alert.condition_value:
            sop_query = sop_query.filter(
                or_(
                    QualitySop.condition_value.is_(None),
                    QualitySop.condition_value == alert.condition_value,
                )
            )
        else:
            # 预警没有工况值：只适用于某个工况的 SOP 不适用，只收全工况的
            sop_query = sop_query.filter(QualitySop.condition_value.is_(None))
        sops = [
            {"id": str(row.id), "code": row.code, "version": int(row.version or 1),
             "title": row.title}
            for row in sop_query.order_by(
                QualitySop.code.asc(), QualitySop.version.desc(),
            ).limit(20).all()
        ]
    baseline = None
    field = evidence.get("field")
    if alert.scene_id and field:
        row = find_active_baseline(
            db, scene_id=alert.scene_id, station_id=alert.station_id,
            condition_value=alert.condition_value, field=field,
        )
        if row is not None:
            baseline = {"id": str(row.id), "version": int(row.version or 1),
                        "center": row.center, "sigma": row.sigma}
    model_version = None
    raw_version_id = evidence.get("model_version_id")
    if raw_version_id:
        try:
            version = db.query(ModelVersion).filter(
                ModelVersion.id == UUID(str(raw_version_id))
            ).first()
        except (ValueError, AttributeError):
            version = None
        model_version = (
            {"id": str(version.id), "version_number": version.version_number}
            if version is not None else {"id": str(raw_version_id)}
        )
    return {
        "sops": sops,
        "spc_baseline": baseline,
        "model_version": model_version,
        "criteria": evaluate_criteria_chain(db, alert),
        "frozen_at": now.isoformat(),
    }


def transition_alert(
    db: Session,
    alert: QualityAlert,
    to_status: str,
    *,
    actor_id=None,
    note: str | None = None,
    resolution: str | None = None,
    action: str = "status_changed",
    now: datetime | None = None,
) -> QualityAlert:
    """阶段流转（五阶段流转图）。责任人为空不得流转；closed 必须带结论。

    action 指定轨迹动作名：确认走 acknowledged、请求复核走 review_requested、
    其余走 status_changed——轨迹里只留一条流转记录，不重复。
    """
    if to_status not in ALERT_STATUSES:
        raise AlertTransitionError("ALERT_STATUS_INVALID")
    previous = alert.status
    if to_status == previous:
        raise AlertTransitionError("ALERT_STATUS_UNCHANGED")
    if to_status not in ALERT_STATUS_FLOW.get(previous, set()):
        raise AlertTransitionError("ALERT_TRANSITION_INVALID")
    # 防呆：责任人为空不得流转——竞品 14 条预警全部超时无人认领的反面教材
    if alert.assigned_to_id is None:
        raise AlertTransitionError("ALERT_ASSIGNEE_REQUIRED")
    if to_status == "closed" and resolution not in ALERT_RESOLUTIONS:
        raise AlertTransitionError("ALERT_RESOLUTION_REQUIRED")
    now = now or _utcnow()
    if to_status == "closed":
        alert.resolution = resolution
        alert.closed_at = now
    alert.status = to_status
    alert.updated_at = now
    # 离开 open 即首次处理（E09「首次处理均时」的起算点）
    if previous == "open":
        alert.first_ack_at = now
    append_event(
        db, alert, action, actor_id=actor_id,
        from_status=previous, to_status=to_status,
        note=note, created_at=now,
    )
    return alert


def acknowledge_alert(
    db: Session, alert: QualityAlert, *, assignee_id, actor_id=None,
    note: str | None = None, now: datetime | None = None,
) -> QualityAlert:
    """确认动作：强制填写责任人（防呆优于竞品）；缺失直接报错（422 语义）。"""
    if assignee_id is None:
        raise AlertTransitionError("ALERT_ASSIGNEE_REQUIRED")
    alert.assigned_to_id = assignee_id
    alert.updated_at = now or _utcnow()
    return transition_alert(
        db, alert, "acknowledged", actor_id=actor_id, note=note,
        action="acknowledged", now=now,
    )


def close_bucket_confirmation(db: Session, alert: QualityAlert, *, now=None) -> bool:
    """处置确认为真实异常：回写该小时桶的 ng_confirmed_count（B1-16 预留列）。

    桶由推理落库时建立；找不到对应桶（演示预警、证据无发生时间等）就不写，
    绝不凭空造一个 total=0 的桶——那会破坏「桶数字 = 明细计数」的不变式。
    """
    now = now or _utcnow()
    occurred_at = _parse_time(dict(alert.evidence or {}).get("occurred_at"))
    if occurred_at is None:
        return False
    bucket_start = occurred_at.replace(minute=0, second=0, microsecond=0)
    bucket = (
        db.query(InferenceResultBucket)
        .filter(
            InferenceResultBucket.project_id == alert.project_id,
            InferenceResultBucket.bucket_start == bucket_start,
            InferenceResultBucket.scene_id.is_(None) if alert.scene_id is None
            else InferenceResultBucket.scene_id == alert.scene_id,
            InferenceResultBucket.station_id.is_(None) if alert.station_id is None
            else InferenceResultBucket.station_id == alert.station_id,
            InferenceResultBucket.condition_value.is_(None) if alert.condition_value is None
            else InferenceResultBucket.condition_value == alert.condition_value,
        )
        .first()
    )
    if bucket is None:
        return False
    bucket.ng_confirmed_count = int(bucket.ng_confirmed_count or 0) + 1
    bucket.updated_at = now
    return True


def submit_disposition(
    db: Session,
    alert: QualityAlert,
    *,
    actor_id,
    form: Mapping[str, Any],
    resolution: str,
    note: str | None = None,
    review_annotator_ids: Sequence = (),
    now: datetime | None = None,
) -> dict:
    """处置表单提交（B1-02）：表单快照 + 三要素快照落轨迹，并关闭预警。

    - confirmed_issue：回写聚合桶 ng_confirmed_count（B1-16 预留列）；
    - false_positive：误报回流复核任务（D22），可选同时指派标注员。

    返回 {"bucket_confirmed": bool, "review_task_id": str | None}。
    附带动作（回桶、建复核任务）的失败都不反噬处置本身。
    """
    if resolution not in ALERT_RESOLUTIONS:
        raise AlertTransitionError("ALERT_RESOLUTION_REQUIRED")
    now = now or _utcnow()
    form_snapshot = {
        "type": form.get("type"),
        "cause": form.get("cause"),
        "action": form.get("action"),
        "downtime": bool(form.get("downtime")),
        "rework": bool(form.get("rework")),
        "expanded_inspection": bool(form.get("expanded_inspection")),
        "is_false_positive": resolution == "false_positive",
    }
    snapshot = build_disposition_snapshot(db, alert)
    transition_alert(
        db, alert, "closed", actor_id=actor_id, note=note,
        resolution=resolution, now=now,
    )
    append_event(
        db, alert, "disposition_submitted",
        actor_id=actor_id, note=note, form_snapshot=form_snapshot,
        snapshot=snapshot, created_at=now,
    )
    outcome: dict[str, Any] = {"bucket_confirmed": False, "review_task_id": None}
    if resolution == "confirmed_issue":
        try:
            outcome["bucket_confirmed"] = close_bucket_confirmation(db, alert, now=now)
        except Exception:
            logger.exception("bucket ng_confirmed writeback failed for alert %s", alert.id)
        # critical 确认异常 → 自动开质量案例（第三批 D4/B3-07；三批复审发现自动
        # 开案从未接线，验收口径 6 标 passed 不成立——现为补实现）。失败只告警，
        # 不反噬处置流。
        if alert.severity == "critical":
            try:
                from app.services.qms_core import open_case

                case = open_case(
                    db, project_id=alert.project_id,
                    code=f"CASE-{uuid.uuid4().hex[:8].upper()}",
                    title=f"自动开案：{alert.title}",
                    severity="critical", source_alert_id=alert.id,
                    keywords=alert.source_type,
                    created_by_id=actor_id,
                )
                outcome["auto_case_id"] = str(case.id)
            except Exception:
                logger.exception("auto case open failed for alert %s", alert.id)
    elif resolution == "false_positive":
        outcome["review_task_id"] = _create_review_task_safely(
            db, alert, actor_id, list(review_annotator_ids), now=now,
        )
    return outcome


def _create_review_task_safely(
    db: Session, alert: QualityAlert, actor_id, annotator_ids: list, *, now: datetime
) -> str | None:
    """误报回流（D22）：在保存点里建复核任务，失败只降级为轨迹注释。

    不能在失败时回滚整个会话——调用方的事务里还有刚写入的处置结论与审计
    事件，整段回滚会把处置一起丢掉。保存点只撤销建任务这一段。
    """
    try:
        with db.begin_nested():
            task_id = create_review_task_for_alert(db, alert, actor_id, annotator_ids)
    except Exception as error:  # noqa: BLE001 - 任何失败都不得阻断处置
        logger.exception("false-positive review task failed for alert %s", alert.id)
        append_event(
            db, alert, "comment", actor_id=actor_id,
            note=f"误报回流复核任务创建失败（{type(error).__name__}），处置结论已保存",
            created_at=now,
        )
        return None
    if task_id is None:
        append_event(
            db, alert, "comment", actor_id=actor_id,
            note="样本不在任何就绪数据集版本中，未创建复核任务",
            created_at=now,
        )
        return None
    append_event(
        db, alert, "review_task_created", actor_id=actor_id,
        note=f"误报回流复核任务 {task_id}",
        form_snapshot={"task_id": str(task_id), "annotators": len(annotator_ids)},
        created_at=now,
    )
    return str(task_id)


def create_review_task_for_alert(
    db: Session, alert: QualityAlert, actor_id, annotator_ids: Sequence = ()
):
    """误报结论 → 复核标注任务（复用演示循环的同形原语，更正 C13）。

    样本定位：项目内最新的就绪数据集版本里 sample_id == 预警样本键的行；
    找不到返回 None。任务幂等键固定为预警 id——同一预警只建一次复核任务。
    任务落在待标注状态；未指派时管理者可经既有指派接口指派（「可指派」）。
    """
    from uuid import UUID

    from app.models.data_version import DatasetSchemaColumn
    from app.models.platform_models import GenericAnnotationTask
    from app.services.annotation_concurrency import AssignmentError, create_assignments
    from app.services.annotation_scope import (
        persist_scope_entries,
        scope_descriptor,
        scope_digest,
    )
    from app.services.label_schema import (
        bind_label_schema_to_task,
        create_label_schema,
        label_schema_snapshot,
    )

    if not alert.sample_key:
        return None
    sample = (
        db.query(DatasetSample)
        .join(DatasetVersion, DatasetSample.dataset_version_id == DatasetVersion.id)
        .filter(
            DatasetVersion.project_id == alert.project_id,
            DatasetVersion.status == "ready",
            DatasetSample.sample_id == str(alert.sample_key),
        )
        .order_by(DatasetVersion.version.desc(), DatasetSample.row_index.asc())
        .first()
    )
    if sample is None:
        return None
    version = db.get(DatasetVersion, sample.dataset_version_id)
    if version is None:
        return None

    entries = [(str(sample.sample_id), int(sample.row_index))]
    count, scope_hash = scope_digest(entries)
    schema = create_label_schema(
        db,
        project_id=alert.project_id,
        name=f"误报复核-{str(alert.id)[:8]}",
        columns=[{
            "machine_key": "review_label",
            "display_name": "复核标签",
            "value_type": "string",
            "required": True,
            "enum_values": ["keep_false_positive", "restore_ng"],
        }],
        commit=False,
    )
    source_columns = [
        {"name": column.name, "dtype": column.dtype, "nullable": column.nullable,
         "position": column.position}
        for column in sorted(
            db.query(DatasetSchemaColumn)
            .filter(DatasetSchemaColumn.dataset_version_id == version.id).all(),
            key=lambda item: item.position,
        )
    ]
    snapshot = {
        "dataset_version": {
            "id": str(version.id),
            "version": version.version,
            "content_hash": version.content_hash,
            "schema_hash": version.schema_hash,
            "columns": source_columns,
        },
        "scope": scope_descriptor(count, scope_hash),
        "visible_columns": [column["name"] for column in (source_columns or [])],
        "label_schema": label_schema_snapshot(schema),
        "instructions": "预警误报回流复核：请确认该样本是否确为误报（维持误报或改判异常）。",
        "completion_criteria": "",
        "configuration": {"alert_id": str(alert.id)},
        "field_descriptions": {},
    }
    task = GenericAnnotationTask(
        project_id=alert.project_id,
        dataset_version_id=version.id,
        label_schema_id=schema.id,
        owner_id=actor_id,
        name=f"误报复核-{str(alert.id)[:8]}",
        mode="manual",
        # 与演示闭环同形：直接落到可指派的待标注状态
        status="awaiting_annotation",
        sample_scope={"kind": "ids", "sample_ids": [str(sample.sample_id)]},
        label_snapshot=snapshot["label_schema"],
        task_snapshot=snapshot,
        idempotency_key=f"quality-alert-review-{alert.id}",
    )
    db.add(task)
    db.flush()
    persisted = persist_scope_entries(db, task.id, task.task_revision, entries)
    if persisted != count:
        raise ValueError("REVIEW_SCOPE_MISMATCH")
    bind_label_schema_to_task(db, task_id=task.id, schema=schema)
    if annotator_ids:
        try:
            create_assignments(
                db,
                task_id=task.id,
                annotator_ids=[UUID(str(item)) for item in annotator_ids],
                sample_scope={"kind": "all"},
                due_at=None,
                actor=actor_id,
                idempotency_key=f"quality-alert-review-assign-{alert.id}",
            )
        except AssignmentError as error:
            # 指派失败不算回流失败：任务已建好，管理者可稍后手动指派
            logger.warning("review task assignment skipped for alert %s: %s", alert.id, error)
    return task.id


def relay_demo_alert(
    db: Session,
    *,
    project_id,
    demo_config_id,
    source_type: str,
    severity: str,
    title: str,
    risk_score: float | None = None,
    evidence: dict | None = None,
    now: datetime | None = None,
) -> tuple[QualityAlert, bool]:
    """演示循环预警并入预警中心（C14/D18）：is_demo=true，原站内通知不变。"""
    return create_alert(
        db,
        project_id=project_id,
        merge_key=f"demo:{demo_config_id}:{source_type}",
        source_type=source_type,
        title=title,
        severity=severity,
        risk_score=risk_score,
        evidence=dict(evidence or {}),
        source_ref={"kind": "demo_loop", "id": str(demo_config_id)},
        is_demo=True,
        now=now,
    )


def decode_waveform_column(encoded: object) -> list[float] | None:
    """平台波形列的编码约定：base64(大端 int16 序列)。

    通用平台不依赖任何行业的波形模块（泛化门禁禁止通用代码引用点焊域
    特征模块），也不限定点数——点数由场景的波形列决定。解码不了返回 None，
    由调用方给出显式空态（诚实设计③）。
    """
    import base64
    import binascii
    import struct

    if not isinstance(encoded, str) or not encoded.strip():
        return None
    try:
        raw = base64.b64decode(encoded.strip(), validate=True)
    except (ValueError, TypeError, binascii.Error):
        return None
    if not raw or len(raw) % 2:
        return None
    return [float(value) for value in struct.unpack(f">{len(raw) // 2}h", raw)]


# ----------------------------------------------------------------------
# beat 任务体（D16 设备心跳 / D21 SLA）
# ----------------------------------------------------------------------

def _heartbeat_stale(last_heartbeat: datetime | None, now: datetime) -> bool:
    """心跳是否过期：与 api/compute.py 的判定同口径（从未心跳视为过期）。"""
    return _parse_time(last_heartbeat) is None or (
        (now - _parse_time(last_heartbeat)).total_seconds() > _HEARTBEAT_STALE_SECONDS
    )


def watch_devices(db: Session, *, now: datetime | None = None) -> dict:
    """设备心跳巡检（D16）。

    心跳过期 → device_anomaly 预警（同因合并，每 5 分钟一轮不会刷出一串）；
    心跳恢复 → 恰好记一条 device_recovered 轨迹并让该预警停止接受合并——
    之后再来一次离线是新的「因」，必须产生新预警。恢复不自动关闭预警
    （人工确认后关闭，与防呆口径一致）。
    """
    now = now or _utcnow()
    from app.models.compute import EdgeDevice

    stations = (
        db.query(QualityStation)
        .filter(
            QualityStation.enabled.is_(True),
            QualityStation.edge_device_id.isnot(None),
        )
        .order_by(QualityStation.id.asc())
        .all()
    )
    scene_ids = {station.scene_id for station in stations}
    scenes = (
        {scene.id: scene for scene in db.query(QualityScene).filter(
            QualityScene.id.in_(scene_ids)
        ).all()} if scene_ids else {}
    )
    device_ids = {station.edge_device_id for station in stations}
    devices = (
        {device.id: device for device in db.query(EdgeDevice).filter(
            EdgeDevice.id.in_(device_ids)
        ).all()} if device_ids else {}
    )
    checked = created = recovered = 0
    for station in stations:
        scene = scenes.get(station.scene_id)
        device = devices.get(station.edge_device_id)
        if scene is None or device is None:
            continue
        checked += 1
        if _heartbeat_stale(device.last_heartbeat, now):
            _, was_created = create_alert(
                db,
                project_id=scene.project_id,
                merge_key="device_anomaly",
                source_type="device_anomaly",
                title=f"设备离线：{device.name}（工位 {station.code}）",
                severity="warning",
                scene_id=station.scene_id,
                station_id=station.id,
                device_id=device.id,
                evidence={
                    "kind": "device_anomaly",
                    "device_name": device.name,
                    "device_status": device.status,
                    "last_heartbeat": (
                        device.last_heartbeat.isoformat()
                        if device.last_heartbeat else None
                    ),
                    "occurred_at": now.isoformat(),
                },
                source_ref={"kind": "edge_device", "id": str(device.id)},
                alert_settings=resolve_alert_settings(scene),
                now=now,
            )
            if was_created:
                created += 1
            continue
        open_alerts = (
            db.query(QualityAlert)
            .filter(
                QualityAlert.station_id == station.id,
                QualityAlert.source_type == "device_anomaly",
                QualityAlert.status != "closed",
                QualityAlert.merge_open.is_(True),
                QualityAlert.is_demo.is_(False),
            )
            .all()
        )
        for open_alert in open_alerts:
            open_alert.merge_open = False
            open_alert.updated_at = now
            append_event(
                db, open_alert, "device_recovered",
                note=f"设备 {device.name} 心跳已恢复；预警保留，待人工确认后关闭",
                created_at=now,
            )
            recovered += 1
    return {
        "stations_checked": checked,
        "created": created,
        "recovered": recovered,
    }


def close_requires_approval(db: Session, alert: QualityAlert) -> bool:
    """D8 场景开关：critical 关闭是否走审批（quality_scenes.alert_settings
    .require_close_approval_for_critical，默认 False=F2 行为零变化）。"""
    if getattr(alert, "severity", None) != "critical" or alert.scene_id is None:
        return False
    scene = db.get(QualityScene, alert.scene_id)
    scene_settings = (getattr(scene, "alert_settings", None) or {}) if scene else {}
    return bool(scene_settings.get("require_close_approval_for_critical"))


def watch_sla(db: Session, *, now: datetime | None = None) -> dict:
    """SLA 巡检（D21）：临期（剩余 ≤25% 总时长）与超时两档域事件入 outbox，
    由既有订阅路由投递；预警上的档位保证每档只通知一次。
    """
    now = now or _utcnow()
    recorder = OutboxDomainEventRecorder()
    due_count = overdue_count = 0
    pending = (
        db.query(QualityAlert)
        .filter(
            # 单一口径（三批复审）：review_pending 也是未关闭状态，SLA 巡检此前漏掉
            # 它——该状态的预警收不到任何 SLA 通知，且与驾驶舱「超时」卡不一致
            QualityAlert.status.in_(OPEN_STATUSES),
            QualityAlert.sla_due_at.isnot(None),
            QualityAlert.sla_notify_level < 2,
            QualityAlert.is_demo.is_(False),
        )
        .all()
    )
    for alert in pending:
        total = (alert.sla_due_at - alert.created_at).total_seconds()
        if total <= 0:
            continue
        remaining = (alert.sla_due_at - now).total_seconds()
        if remaining <= 0:
            level, event_type, severity = 2, "quality.alert.sla_overdue", "critical"
        elif remaining <= total * _SLA_DUE_RATIO:
            level, event_type, severity = 1, "quality.alert.sla_due", "warning"
        else:
            continue
        if int(alert.sla_notify_level or 0) >= level:
            continue
        recorder.record(
            db,
            create_domain_event(
                idempotency_key=f"quality-alert-sla-{alert.id}-{level}",
                event_type=event_type,
                severity=severity,
                occurred_at=now,
                project_id=alert.project_id,
                actor_id=None,
                resource_type="quality_alert",
                resource_id=str(alert.id),
                payload={
                    "alert_id": str(alert.id),
                    "title": alert.title,
                    "severity": alert.severity,
                    "sla_due_at": alert.sla_due_at.isoformat(),
                },
            ),
        )
        alert.sla_notify_level = level
        alert.updated_at = now
        append_event(
            db, alert, "sla_notified",
            note="SLA 临期提醒" if level == 1 else "SLA 已超时",
            created_at=now,
        )
        if level == 1:
            due_count += 1
        else:
            overdue_count += 1
    return {"due_notified": due_count, "overdue_notified": overdue_count}
