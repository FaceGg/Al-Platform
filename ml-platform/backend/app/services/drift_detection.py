"""Drift detection (补齐路线第一批 F4, B1-09).

特征级漂移检测（技术方案 §9C，D38–D40）：

- **数据来源**：落库时按基线分箱累计的特征直方图（inference_feature_histograms）。
  推理明细窄表不存特征值，快照样本有偏；直方图覆盖全部样本。
- **基线**：模型版本的训练分布（等概率分箱），按血缘从训练数据集版本惰性计算并
  存入 drift_baselines；没有训练数据血缘的模型版本没有基线，也就没有直方图。
- **三类信号**：特征级 PSI、数据质量（缺失率、恒值）。**本期未实现**：PCA 重构误差、
  分数级 PSI 并入报告、分片部署按「版本 × 工况」分桶（D39 如实登记）。
- **定时批检**：对每个运行态部署产出分级报告；漂移是触发器不是自动开关——严重级
  只通知，数据质量命中进预警中心（传感器异常），不自动处置。

本模块**不改动**现有分数级 PSI（services/anomaly_drift.py）：它仍是闭环重拟合的触发器。
"""
from __future__ import annotations

import bisect
import itertools
import logging
import math
import time
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.database import SessionLocal
from app.models.data_version import DatasetSample, DatasetVersion
from app.models.drift import (
    DriftBaseline,
    DriftReport,
    DriftReportFeature,
    InferenceFeatureHistogram,
)
from app.models.model_registry import InferenceDeployment, ModelVersion

logger = logging.getLogger(__name__)

_EPSILON = 1e-6

# 没有基线（无训练数据血缘）的模型版本：短期内不再重复尝试，避免每次落库都去查血缘
_BASELINE_RETRY_SECONDS = 600.0
_baseline_cache: dict[Any, tuple[float, dict | None]] = {}


def reset_baseline_cache() -> None:
    """测试用：清空进程内基线缓存。"""
    _baseline_cache.clear()


# ----------------------------------------------------------------------
# 纯函数
# ----------------------------------------------------------------------

def psi(expected: Sequence, observed: Sequence) -> float:
    """Population Stability Index = Σ (实际占比 − 期望占比) · ln(实际 / 期望)。

    两个分布先各自归一；占比为 0 的箱按 epsilon 参与。两侧都为 0 的箱不贡献
    （否则 epsilon 对 epsilon 会产生纯噪声）。任一侧总量为 0 时返回 0。
    """
    if len(expected) != len(observed):
        raise ValueError("PSI_DISTRIBUTION_LENGTH_MISMATCH")
    expected_sum, observed_sum = sum(expected), sum(observed)
    if expected_sum <= 0 or observed_sum <= 0:
        return 0.0
    total = 0.0
    for expected_raw, observed_raw in zip(expected, observed):
        expected_share = expected_raw / expected_sum
        observed_share = observed_raw / observed_sum
        if expected_share <= _EPSILON and observed_share <= _EPSILON:
            continue
        smoothed_expected = max(expected_share, _EPSILON)
        smoothed_observed = max(observed_share, _EPSILON)
        total += (smoothed_observed - smoothed_expected) * math.log(
            smoothed_observed / smoothed_expected,
        )
    return total


def quantile_edges(values: Sequence[float], bins: int) -> list[float]:
    """等概率分箱的 bins + 1 个边界（按样本分位数取）。重复的边界会被合并。

    所有值相同（常量特征）时返回 [v, v]：这是「退化基线」，bin_index 会把不等于 v
    的观测值归到箱外——否则常量特征永远判不出漂移。
    """
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return []
    count = len(ordered)
    raw = [ordered[round(step * (count - 1) / bins)] for step in range(bins + 1)]
    edges = [raw[0]]
    for value in raw[1:]:
        if value > edges[-1]:
            edges.append(value)
    if len(edges) == 1:
        edges.append(edges[0])
    return edges


def bin_index(value: float, edges: Sequence[float]) -> int:
    """值落在哪个箱。超出非退化基线范围的值归到首 / 末箱；退化基线下不等于常量的
    值返回 len(edges)，表示「箱外」（计数组的最后一个槽位）。"""
    if edges[-1] <= edges[0]:
        return 0 if value == edges[0] else len(edges)
    return bisect.bisect_right(edges[1:-1], value)


def _is_number(raw: Any) -> bool:
    return isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw)


# ----------------------------------------------------------------------
# 基线
# ----------------------------------------------------------------------

def feature_names_of(version: ModelVersion) -> list[str]:
    """模型版本的特征列名；feature_schema 是 [{"name","dtype"}]，兼容裸字符串。"""
    names: list[str] = []
    for item in version.feature_schema or []:
        name = item.get("name") if isinstance(item, Mapping) else item
        if name:
            names.append(str(name))
    return names


def compute_baselines_from_dataset(
    db: Session, dataset_version: DatasetVersion, features: Sequence[str],
) -> dict[str, dict]:
    """从数据集版本按行序流式取数，算每个特征的等概率分箱基线。

    最多读 drift_baseline_max_rows 行；数值不足 drift_baseline_min_samples 的特征不出基线。
    """
    max_rows = app_settings.drift_baseline_max_rows
    minimum = app_settings.drift_baseline_min_samples
    bins = app_settings.drift_psi_bins
    values: dict[str, list[float]] = {name: [] for name in features}
    rows_read = 0
    for sample in (
        db.query(DatasetSample.values)
        .filter(DatasetSample.dataset_version_id == dataset_version.id)
        .order_by(DatasetSample.row_index.asc(), DatasetSample.id.asc())
        .yield_per(2000)
    ):
        rows_read += 1
        record = sample[0] or {}
        for name in features:
            raw = record.get(name)
            if _is_number(raw):
                values[name].append(float(raw))
        if rows_read >= max_rows:
            break
    baselines: dict[str, dict] = {}
    for name in features:
        column = values[name]
        if len(column) < minimum:
            continue
        edges = quantile_edges(column, bins)
        counts = [0] * (len(edges) - 1)
        for value in column:
            counts[bin_index(value, edges)] += 1
        total = len(column)
        baselines[name] = {
            "edges": edges,
            "probs": [count / total for count in counts],
            "sample_count": total,
        }
    return baselines


def load_baselines(db: Session, model_version_id) -> dict[str, dict]:
    rows = db.query(DriftBaseline).filter(DriftBaseline.model_version_id == model_version_id).all()
    return {
        row.feature_name: {
            "id": str(row.id), "edges": list(row.bin_edges or []),
            "probs": list(row.bin_probs or []), "sample_count": int(row.sample_count or 0),
        }
        for row in rows
    }


def ensure_baselines(db: Session, model_version_id) -> dict[str, dict] | None:
    """取模型版本的训练分布基线；没有就按血缘算一次并落库。

    返回 None 表示该版本没有基线（没有训练数据血缘，或特征数值不足）——这种结果
    在进程内缓存一小段时间，避免每次落库都去查血缘。
    """
    now = time.monotonic()
    cached = _baseline_cache.get(model_version_id)
    if cached is not None and (cached[1] is not None or now - cached[0] < _BASELINE_RETRY_SECONDS):
        return cached[1]
    existing = load_baselines(db, model_version_id)
    if existing:
        _baseline_cache[model_version_id] = (now, existing)
        return existing
    version = db.get(ModelVersion, model_version_id)
    features = feature_names_of(version) if version is not None else []
    computed: dict[str, dict] = {}
    if version is not None and features:
        from app.services.evidence_chain import collect_lineage

        lineage = collect_lineage(db, version)
        dataset_version = lineage["dataset_version"]
        if dataset_version is not None:
            computed = compute_baselines_from_dataset(db, dataset_version, features)
    if not computed:
        _baseline_cache[model_version_id] = (now, None)
        return None
    for name, payload in computed.items():
        row = DriftBaseline(
            model_version_id=model_version_id, feature_name=name,
            bin_edges=payload["edges"], bin_probs=payload["probs"],
            sample_count=payload["sample_count"], source="training_dataset",
            dataset_version_id=dataset_version.id, created_at=datetime.utcnow(),
        )
        db.add(row)
        db.flush()
        payload["id"] = str(row.id)
    _baseline_cache[model_version_id] = (now, computed)
    return computed


# ----------------------------------------------------------------------
# 特征直方图（落库路径）
# ----------------------------------------------------------------------

HistogramKey = tuple  # ((scene_id, station_id, condition_value), feature_name)


def _new_counter(baseline: Mapping) -> dict:
    # 最后一个槽位是「箱外」：只在退化基线（训练时常量特征）下才会有计数
    return {"counts": [0] * (len(baseline["probs"]) + 1), "missing": 0, "total": 0}


def record_feature_histograms(
    db: Session, *, project_id, model_version_id, scopes, records,
    now: datetime | None = None,
) -> int:
    """落库路径的挂钩：按基线分箱累计本次请求的特征直方图并落库（不 commit）。

    scopes 与 records 等长成对：每个 scope 是 (scene_id, station_id, condition_value,
    channel)，**必须覆盖本次请求的全部样本**——不能用明细行列表代替，超限降级时
    明细只留异常与抽样，拿它累计会得到有偏的分布。只累计 online / batch 通道；
    没有基线的模型版本直接返回 0。返回写入（新建或累加）的特征行数。
    """
    baselines = ensure_baselines(db, model_version_id)
    if not baselines:
        return 0
    now = now or datetime.utcnow()
    limit = app_settings.inference_histogram_max_records
    pairs: Any = zip(scopes, records)
    if limit > 0:
        pairs = itertools.islice(pairs, limit)
    counters: dict[HistogramKey, dict] = {}
    for scope, record in pairs:
        scene_id, station_id, condition_value, channel = scope
        if (channel or "online") not in ("online", "batch"):
            continue
        if not isinstance(record, Mapping):
            record = {}
        scope = (scene_id, station_id, condition_value)
        for name, baseline in baselines.items():
            key = (scope, name)
            entry = counters.get(key)
            if entry is None:
                entry = counters[key] = _new_counter(baseline)
            entry["total"] += 1
            raw = record.get(name)
            if _is_number(raw):
                entry["counts"][bin_index(float(raw), baseline["edges"])] += 1
            else:
                entry["missing"] += 1
    if not counters:
        return 0
    bucket_start = now.replace(minute=0, second=0, microsecond=0)
    written = 0
    for (scope, name), entry in counters.items():
        scene_id, station_id, condition_value = scope
        existing = (
            db.query(InferenceFeatureHistogram)
            .filter(
                InferenceFeatureHistogram.bucket_start == bucket_start,
                InferenceFeatureHistogram.model_version_id == model_version_id,
                InferenceFeatureHistogram.feature_name == name,
                InferenceFeatureHistogram.scene_id.is_(None) if scene_id is None
                else InferenceFeatureHistogram.scene_id == scene_id,
                InferenceFeatureHistogram.station_id.is_(None) if station_id is None
                else InferenceFeatureHistogram.station_id == station_id,
                InferenceFeatureHistogram.condition_value.is_(None) if condition_value is None
                else InferenceFeatureHistogram.condition_value == condition_value,
            )
            .first()
        )
        if existing is None:
            db.add(InferenceFeatureHistogram(
                bucket_start=bucket_start, project_id=project_id,
                scene_id=scene_id, station_id=station_id, condition_value=condition_value,
                model_version_id=model_version_id, feature_name=name,
                bin_counts=list(entry["counts"]), missing_count=entry["missing"],
                total_count=entry["total"], updated_at=now,
            ))
        else:
            # 箱数以较宽的一方为准（基线重算后箱数可能变化）
            current = list(existing.bin_counts or [])
            width = max(len(current), len(entry["counts"]))
            current = current + [0] * (width - len(current))
            incoming = list(entry["counts"]) + [0] * (width - len(entry["counts"]))
            existing.bin_counts = [left + right for left, right in zip(current, incoming)]
            existing.missing_count = int(existing.missing_count or 0) + entry["missing"]
            existing.total_count = int(existing.total_count or 0) + entry["total"]
            existing.updated_at = now
        written += 1
    return written


# ----------------------------------------------------------------------
# 定时批检
# ----------------------------------------------------------------------

def aggregate_window(
    db: Session, *, project_id, model_version_id, started: datetime, ended: datetime,
) -> dict[str, dict]:
    """把窗口内（按整点桶）的直方图按特征求和。"""
    rows = (
        db.query(InferenceFeatureHistogram)
        .filter(
            InferenceFeatureHistogram.project_id == project_id,
            InferenceFeatureHistogram.model_version_id == model_version_id,
            InferenceFeatureHistogram.bucket_start >= started.replace(
                minute=0, second=0, microsecond=0,
            ),
            InferenceFeatureHistogram.bucket_start <= ended,
        )
        .all()
    )
    aggregated: dict[str, dict] = {}
    for row in rows:
        entry = aggregated.setdefault(
            row.feature_name, {"counts": [], "missing": 0, "total": 0},
        )
        counts = list(row.bin_counts or [])
        width = max(len(counts), len(entry["counts"]))
        entry["counts"] = [
            (entry["counts"][index] if index < len(entry["counts"]) else 0)
            + (counts[index] if index < len(counts) else 0)
            for index in range(width)
        ]
        entry["missing"] += int(row.missing_count or 0)
        entry["total"] += int(row.total_count or 0)
    return aggregated


def _level_for(value: float, severe_threshold: float, watch_threshold: float) -> str:
    if value >= severe_threshold:
        return "severe"
    if value >= watch_threshold:
        return "watch"
    return "stable"


def scan_deployment(
    db: Session, deployment: InferenceDeployment, *, now: datetime | None = None,
    notify: bool = True,
) -> DriftReport:
    """对一个运行态部署做一次漂移批检并落报告。

    notify=True 时执行副作用（严重级通知、数据质量命中进预警中心）——生产路径；
    测试里关掉副作用可以只验证判定。调用方负责 commit。
    """
    now = now or datetime.utcnow()
    started = now - timedelta(hours=app_settings.drift_window_hours)
    baselines = ensure_baselines(db, deployment.model_version_id) or {}
    aggregated = aggregate_window(
        db, project_id=deployment.project_id, model_version_id=deployment.model_version_id,
        started=started, ended=now,
    )
    sample_count = max((entry["total"] for entry in aggregated.values()), default=0)
    severe_threshold = float(app_settings.drift_severe_psi)
    watch_threshold = min(float(app_settings.drift_watch_psi), severe_threshold)
    missing_threshold = float(app_settings.drift_missing_ratio)
    constant_threshold = float(app_settings.drift_constant_share)
    notes: list[str] = []
    signals: list[dict] = []

    if not baselines:
        level = "insufficient"
        notes.append("该模型版本没有训练分布基线（没有训练数据血缘，或训练数据里特征数值不足），无法做特征级检测")
    elif sample_count < app_settings.drift_min_samples:
        level = "insufficient"
        notes.append(
            f"窗口内样本 {sample_count} 个，少于最小样本 {app_settings.drift_min_samples} 个，不做判定"
        )
    else:
        for feature in sorted(baselines):
            baseline = baselines[feature]
            entry = aggregated.get(feature)
            if not entry or entry["total"] <= 0:
                continue
            bins = len(baseline["probs"])
            observed = list(entry["counts"])
            core = observed[:bins] + [0] * (bins - min(len(observed), bins))
            outside = sum(observed[bins:])
            total = entry["total"]
            shares = [count / total for count in core]
            value = psi(list(baseline["probs"]) + [0.0], core + [outside])
            feature_level = _level_for(value, severe_threshold, watch_threshold)
            if feature_level != "stable":
                signals.append({
                    "feature_name": feature, "signal_kind": "feature_psi",
                    "value": round(value, 6), "threshold": severe_threshold,
                    "level": feature_level,
                    "detail": {
                        "baseline_id": baseline.get("id"),
                        "baseline_sample_count": baseline.get("sample_count"),
                        "expected_shares": [round(item, 6) for item in baseline["probs"]],
                        "observed_shares": [round(item, 6) for item in shares],
                        "outside_ratio": round(outside / total, 6),
                        "bin_edges": baseline["edges"],
                    },
                })
            missing_ratio = entry["missing"] / total
            if missing_ratio > missing_threshold:
                signals.append({
                    "feature_name": feature, "signal_kind": "dq_missing",
                    "value": round(missing_ratio, 6), "threshold": missing_threshold,
                    "level": "severe" if missing_ratio >= 2 * missing_threshold else "watch",
                    "detail": {"missing": entry["missing"], "total": total},
                })
            # 恒值：训练时本来就常量的特征（退化基线）不算异常
            degenerate = baseline["edges"][-1] <= baseline["edges"][0]
            dominant = max(core) / total
            if not degenerate and dominant >= constant_threshold:
                signals.append({
                    "feature_name": feature, "signal_kind": "dq_constant",
                    "value": round(dominant, 6), "threshold": constant_threshold,
                    "level": "watch",
                    "detail": {"dominant_share": round(dominant, 6), "total": total},
                })
        if any(item["level"] == "severe" for item in signals):
            level = "severe"
        elif any(item["level"] == "watch" for item in signals):
            level = "watch"
        else:
            level = "stable"

    signal_counts: dict[str, int] = {}
    for item in signals:
        signal_counts[item["signal_kind"]] = signal_counts.get(item["signal_kind"], 0) + 1
    report = DriftReport(
        project_id=deployment.project_id, deployment_id=deployment.id,
        model_version_id=deployment.model_version_id, started_at=started, ended_at=now,
        level=level, sample_count=sample_count,
        summary={
            "notes": notes,
            "signal_counts": signal_counts,
            "feature_count": len(baselines),
            "window_hours": app_settings.drift_window_hours,
            "severe_psi": severe_threshold, "watch_psi": watch_threshold,
            # 如实写进报告：本期未接入的信号
            "not_wired": [
                "pca_reconstruction_error", "score_psi_in_report", "per_shard_buckets",
            ],
        },
        created_at=now,
    )
    db.add(report)
    db.flush()
    for item in signals:
        db.add(DriftReportFeature(report_id=report.id, **item))

    if notify:
        _dispatch_side_effects(db, deployment, report, signals, now=now)
    return report


def _dispatch_side_effects(
    db: Session, deployment: InferenceDeployment, report: DriftReport,
    signals: Sequence[dict], *, now: datetime,
) -> None:
    """数据质量命中进预警中心（传感器异常）；严重级通知项目负责人。失败只记日志。"""
    from app.services.quality_alerts import create_alert

    for item in signals:
        if not item["signal_kind"].startswith("dq_"):
            continue
        try:
            missing = item["signal_kind"] == "dq_missing"
            create_alert(
                db, project_id=deployment.project_id, source_type="sensor_anomaly",
                merge_key=f"drift:{item['signal_kind']}:{item['feature_name']}",
                severity="high" if item["level"] == "severe" else "warning",
                title=(
                    f"数据质量异常：特征 {item['feature_name']} "
                    + (f"缺失率 {item['value']:.1%}（阈值 {item['threshold']:.1%}）" if missing else
                       # 不说「恒值」：分布整体平移时取值也会集中在训练分布的同一个分箱里
                       f"的取值全部集中在训练分布的同一个分箱内（占比 {item['value']:.1%}）")
                ),
                evidence={
                    "kind": "sensor_anomaly", "signal": item["signal_kind"],
                    "feature": item["feature_name"], "value": item["value"],
                    "threshold": item["threshold"], "report_id": str(report.id),
                    "deployment_id": str(deployment.id),
                    "occurred_at": now.isoformat(),
                },
                source_ref={"kind": "drift_report", "id": str(report.id)},
                now=now,
            )
        except Exception:  # noqa: BLE001 - 副作用失败不影响报告落库
            logger.exception("drift dq alert failed for report %s", report.id)
    if report.level != "severe":
        return
    drifted = [item["feature_name"] for item in signals if item["signal_kind"] == "feature_psi"]
    try:
        _emit_severe_event(db, deployment=deployment, report=report, drifted=drifted, now=now)
    except Exception:  # noqa: BLE001
        logger.exception("drift severe event failed for report %s", report.id)
    try:
        from app.services.closed_loop_actions import notify_project_admins

        notify_project_admins(
            db, deployment.project_id,
            title=f"模型漂移严重：部署 {deployment.name}",
            body=(
                f"窗口内 {len(drifted)} 个特征的分布明显偏离训练基线"
                + (f"（{'、'.join(drifted[:5])}{'…' if len(drifted) > 5 else ''}）" if drifted else "")
                + f"。漂移是触发信号，请人工评估是否需要重训。报告 {str(report.id)[:8]}。"
            ),
            severity="warning", event_type="drift.severe",
            payload={"report_id": str(report.id), "deployment_id": str(deployment.id)},
        )
    except Exception:  # noqa: BLE001
        logger.exception("drift severe notification failed for report %s", report.id)


def _emit_severe_event(
    db: Session, *, deployment: InferenceDeployment, report: DriftReport,
    drifted: Sequence[str], now: datetime,
) -> None:
    from app.events.domain import create_domain_event
    from app.services.notification_outbox import OutboxDomainEventRecorder

    OutboxDomainEventRecorder().record(
        db,
        create_domain_event(
            idempotency_key=f"drift-severe:{report.id}",
            event_type="drift.severe",
            severity="critical",
            occurred_at=now,
            project_id=deployment.project_id,
            actor_id=None,
            resource_type="drift_report",
            resource_id=str(report.id),
            payload={
                "deployment_id": str(deployment.id),
                "report_id": str(report.id),
                "drifted_feature_count": len(drifted),
            },
        ),
    )


def run_drift_scan(*, session_factory=None) -> dict:
    """对所有运行态部署各做一次批检。每个部署一个事务，单个失败不影响其余。"""
    factory = session_factory or SessionLocal
    summary: dict[str, Any] = {"scanned": 0, "errors": 0, "levels": {}}
    with factory() as db:
        deployment_ids = [
            row.id for row in db.query(InferenceDeployment.id)
            .filter(InferenceDeployment.desired_state == "running").all()
        ]
    for deployment_id in deployment_ids:
        with factory() as db:
            deployment = db.get(InferenceDeployment, deployment_id)
            if deployment is None:
                continue
            try:
                report = scan_deployment(db, deployment)
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
                summary["errors"] += 1
                logger.exception("drift scan failed for deployment %s", deployment_id)
                continue
            summary["scanned"] += 1
            summary["levels"][report.level] = summary["levels"].get(report.level, 0) + 1
    return summary
