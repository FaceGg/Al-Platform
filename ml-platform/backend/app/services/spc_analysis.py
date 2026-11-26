"""SPC analysis (补齐路线第一批 F4, B1-06).

把 spc_statistics 的纯函数接到平台数据上（技术方案 §9C，D36–D37）：

- 两个取数来源：数据集版本（任意数值字段）与推理结果（预测值 / 异常分数 / 预测概率）；
  各取时间窗内最新的至多 5,000 个点。
- 规格限优先取场景规格定义，同时保留手工录入，结果里标明规格来源。
- 判异点带样本键与时间，可从 SPC 页跳到预警、也可把判异点登记为 spc_violation 预警
  （合并键 = 图类型 + 字段 + 图 + 规则，窗口内折叠成一条）。
- 组内 σ 无法由子群或冻结基线得到时会回退整体 σ——结果里必须写明，不得当成真正的 Cpk。
"""
from __future__ import annotations

import math
import uuid
from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from app.models.data_version import DatasetSample, DatasetSchemaColumn, DatasetVersion
from app.models.inference_result import InferenceResult
from app.services import quality_alerts as alert_service
from app.services import spc_statistics as spc

MAX_POINTS = 5000

# 推理结果窄表里可做 SPC 的数值列
INFERENCE_FIELDS = {
    "predicted_value": "预测值",
    "anomaly_score": "异常分数",
    "probability": "预测概率",
}
VARIABLE_CHARTS = ("xbar_r", "xbar_s", "i_mr")
ATTRIBUTE_CHARTS = ("p", "np", "c", "u")
ALL_CHARTS = VARIABLE_CHARTS + ATTRIBUTE_CHARTS


class SpcAnalysisError(ValueError):
    """分析请求不满足前提（来源字段非法、数据不足、子群数不足等）。"""


def dataset_fields(db: Session, project_id, dataset_version_id) -> list[dict]:
    version = db.get(DatasetVersion, _uuid(dataset_version_id))
    if version is None or version.project_id != project_id:
        raise SpcAnalysisError("DATASET_VERSION_NOT_FOUND")
    columns = (
        db.query(DatasetSchemaColumn)
        .filter(DatasetSchemaColumn.dataset_version_id == version.id)
        .order_by(DatasetSchemaColumn.position.asc())
        .all()
    )
    return [
        {"name": column.name, "dtype": column.dtype, "nullable": bool(column.nullable),
         "numeric": _looks_numeric(column.dtype)}
        for column in columns
    ]


def _uuid(value) -> Any:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise SpcAnalysisError("ID_INVALID") from None


def _looks_numeric(dtype: str | None) -> bool:
    text = str(dtype or "").lower()
    return any(token in text for token in ("int", "float", "double", "number", "decimal", "real"))


def _is_number(raw: Any) -> bool:
    return isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw)


def load_dataset_samples(
    db: Session, project_id, dataset_version_id, field: str, *,
    defect_field: str | None = None, row_from: int | None = None, row_to: int | None = None,
) -> list[dict]:
    """按行序流式读取某字段，取最新（行号最大）的至多 MAX_POINTS 个数值。"""
    version = db.get(DatasetVersion, _uuid(dataset_version_id))
    if version is None or version.project_id != project_id:
        raise SpcAnalysisError("DATASET_VERSION_NOT_FOUND")
    query = (
        db.query(DatasetSample.values, DatasetSample.sample_id, DatasetSample.row_index)
        .filter(DatasetSample.dataset_version_id == version.id)
    )
    if row_from is not None:
        query = query.filter(DatasetSample.row_index >= int(row_from))
    if row_to is not None:
        query = query.filter(DatasetSample.row_index <= int(row_to))
    query = query.order_by(DatasetSample.row_index.asc(), DatasetSample.id.asc())
    kept: deque = deque(maxlen=MAX_POINTS)
    for values, sample_id, row_index in query.yield_per(2000):
        record = values or {}
        raw = record.get(field)
        if not _is_number(raw):
            continue
        kept.append({
            "value": float(raw), "sample_key": str(sample_id), "occurred_at": None,
            "row_index": int(row_index),
            "defect": bool(record.get(defect_field)) if defect_field else False,
        })
    return list(kept)


def load_inference_samples(
    db: Session, project_id, *, field: str, scene_id=None, station_id=None,
    hours: int = 24, now: datetime | None = None,
) -> list[dict]:
    """推理结果里的数值列，按时间升序返回时间窗内最新的至多 MAX_POINTS 条（排除演示通道）。"""
    if field not in INFERENCE_FIELDS:
        raise SpcAnalysisError("SPC_INFERENCE_FIELD_INVALID（推理来源只支持预测值 / 异常分数 / 预测概率）")
    now = now or datetime.utcnow()
    column = getattr(InferenceResult, field)
    query = (
        db.query(InferenceResult)
        .filter(
            InferenceResult.project_id == project_id,
            InferenceResult.channel != "demo",
            column.isnot(None),
            InferenceResult.occurred_at >= now - timedelta(hours=int(hours)),
        )
    )
    if scene_id:
        query = query.filter(InferenceResult.scene_id == _uuid(scene_id))
    if station_id:
        query = query.filter(InferenceResult.station_id == _uuid(station_id))
    rows = query.order_by(InferenceResult.occurred_at.desc(), InferenceResult.id.asc()).limit(MAX_POINTS).all()
    return [
        {
            "value": float(getattr(row, field)), "sample_key": row.sample_key,
            "occurred_at": row.occurred_at, "row_index": None,
            "defect": bool(row.is_anomaly),
        }
        for row in reversed(rows)
    ]


def _scene_spec(db: Session, scene_id, field: str):
    """场景规格定义里该字段「值」统计量的那一条（E27 单一来源）。"""
    from app.models.quality_domain import QualitySpecLimit

    return (
        db.query(QualitySpecLimit)
        .filter(
            QualitySpecLimit.scene_id == scene_id,
            QualitySpecLimit.field == field,
            QualitySpecLimit.statistic == "value",
        )
        .first()
    )


def resolve_spec(
    db: Session, *, scene_id, field: str, usl, lsl, target, use_scene_spec: bool,
) -> dict:
    """规格限：场景规格定义优先，手工值逐项覆盖；来源在结果里标明。"""
    resolved: dict[str, Any] = {"usl": None, "lsl": None, "target": None, "source": "none"}
    if use_scene_spec and scene_id:
        spec = _scene_spec(db, scene_id, field)
        if spec is not None:
            resolved.update({"usl": spec.usl, "lsl": spec.lsl, "target": spec.target, "unit": spec.unit})
            resolved["source"] = "scene_spec"
    manual = {"usl": usl, "lsl": lsl, "target": target}
    provided = [key for key, value in manual.items() if value is not None]
    for key in provided:
        resolved[key] = float(manual[key])
    if provided:
        resolved["source"] = "manual" if resolved["source"] == "none" else "scene_spec+manual"
    return resolved


def _chunks(items: Sequence, size: int) -> list[list]:
    """按顺序切子群，丢掉末尾不完整的一组。"""
    complete = len(items) // size * size
    return [list(items[start:start + size]) for start in range(0, complete, size)]


def _chart_payload(chart, index_sample) -> dict:
    return {
        "kind": chart.kind,
        "center": round(chart.limits.center, 6),
        "ucl": round(chart.limits.ucl, 6),
        "lcl": round(chart.limits.lcl, 6),
        "sigma": round(chart.limits.sigma, 6),
        "in_control_count": chart.in_control_count,
        "in_control_rate": (
            round(chart.in_control_rate, 6) if chart.in_control_rate is not None else None
        ),
        "notes": list(chart.notes),
        "points": [
            _point_payload(point, index_sample(point.index))
            for point in chart.points
        ],
    }


def _point_payload(point, sample: Mapping) -> dict:
    occurred_at = sample["occurred_at"]
    return {
        "index": point.index,
        "value": round(point.value, 6),
        "violations": list(point.violations),
        "ucl": round(point.ucl, 6) if point.ucl is not None else None,
        "lcl": round(point.lcl, 6) if point.lcl is not None else None,
        "sample_key": sample["sample_key"],
        "occurred_at": occurred_at.isoformat() if occurred_at else None,
    }


def analyze(
    db: Session, project_id, request: Mapping, *, now: datetime | None = None,
    raise_alerts: bool = False,
) -> dict:
    """执行一次 SPC 分析。request 的键见 api/spc.py 的请求模型。"""
    kind = request.get("chart") or "i_mr"
    source = request.get("source") or "dataset"
    field = str(request.get("field") or "")
    if kind not in ALL_CHARTS:
        raise SpcAnalysisError("SPC_CHART_KIND_INVALID")
    if not field:
        raise SpcAnalysisError("SPC_FIELD_REQUIRED")
    subgroup_size = int(request.get("subgroup_size") or 5)
    if not spc.MIN_SUBGROUP <= subgroup_size <= spc.MAX_SUBGROUP:
        raise SpcAnalysisError("SPC_SUBGROUP_SIZE_INVALID（子群容量须为 2–10）")
    rules = tuple(int(rule) for rule in (request.get("rules") or range(1, 9)))
    scene_id = _uuid(request["scene_id"]) if request.get("scene_id") else None
    station_id = _uuid(request["station_id"]) if request.get("station_id") else None

    if source == "dataset":
        samples = load_dataset_samples(
            db, project_id, request.get("dataset_version_id"), field,
            defect_field=request.get("defect_field"),
            row_from=request.get("row_from"), row_to=request.get("row_to"),
        )
    elif source == "inference":
        samples = load_inference_samples(
            db, project_id, field=field, scene_id=scene_id, station_id=station_id,
            hours=int(request.get("hours") or 24), now=now,
        )
    else:
        raise SpcAnalysisError("SPC_SOURCE_INVALID")
    if not samples:
        raise SpcAnalysisError("SPC_NO_DATA（所选来源与窗口内没有可用的数值点）")

    values = [sample["value"] for sample in samples]
    groups: list[list] = []
    charts: dict[str, Any] = {}

    if kind in ("xbar_r", "xbar_s"):
        groups = _chunks(samples, subgroup_size)
        if len(groups) < 2:
            raise SpcAnalysisError("SPC_NOT_ENOUGH_SUBGROUPS（至少需要 2 个完整子群）")
        charts = spc.subgroup_charts(
            [[sample["value"] for sample in group] for group in groups], chart=kind, rules=rules,
        )
        index_sample = lambda index: groups[index][0]  # noqa: E731
    elif kind == "i_mr":
        charts = spc.i_mr_chart(values, rules=rules)
        index_sample = lambda index: samples[index]  # noqa: E731
    else:
        groups = _chunks(samples, subgroup_size)
        if len(groups) < 2:
            raise SpcAnalysisError("SPC_NOT_ENOUGH_SUBGROUPS（至少需要 2 个完整子群）")
        counts = [sum(1 for sample in group if sample["defect"]) for group in groups]
        sizes = [len(group) for group in groups]
        charts = {kind: spc.attribute_chart(kind, counts, sizes, rules=rules)}
        index_sample = lambda index: groups[index][0]  # noqa: E731

    spec = resolve_spec(
        db, scene_id=scene_id, field=field,
        usl=request.get("usl"), lsl=request.get("lsl"), target=request.get("target"),
        use_scene_spec=bool(request.get("use_scene_spec", True)),
    )

    notes: list[str] = []
    capability: dict | None = None
    if kind in VARIABLE_CHARTS:
        baseline = (
            alert_service.find_active_baseline(
                db, scene_id=scene_id, station_id=station_id, condition_value=None, field=field,
            ) if scene_id else None
        )
        capability = asdict(spc.capability(
            values, usl=spec["usl"], lsl=spec["lsl"], target=spec["target"],
            subgroups=[[sample["value"] for sample in group] for group in groups] if groups else None,
            baseline_sigma=baseline.sigma if baseline is not None else None,
        ))
        if baseline is not None:
            notes.append(
                f"组内 σ 取自冻结基线 v{int(baseline.version or 1)}（中心 {baseline.center:.6g}，σ {baseline.sigma:.6g}）"
            )
        elif capability["within_sigma_source"] == "overall":
            notes.append(
                "该字段没有冻结基线，也未按子群取数：组内 σ 由整体标准差估计，"
                "Cp / Cpk 实际等同于 Pp / Ppk，不代表过程能力"
            )
        elif capability["within_sigma_source"] == "range":
            notes.append(f"组内 σ 由子群极差估计（子群容量 {subgroup_size}）")
    if spec["usl"] is None and spec["lsl"] is None:
        notes.append("未提供规格限：能力指数留空")
    elif spec["source"].startswith("scene_spec"):
        notes.append("规格限取自场景的规格定义" + ("，其中手工值已覆盖" if "manual" in spec["source"] else ""))

    violations: list[dict] = []
    for name, chart in charts.items():
        for item in chart.violations:
            sample = index_sample(item["index"])
            violations.append({
                "chart": name, "rule": item["rule"], "index": item["index"],
                "value": round(float(item["value"]), 6),
                "sample_key": sample["sample_key"],
                "occurred_at": sample["occurred_at"].isoformat() if sample["occurred_at"] else None,
            })

    alerts_raised = 0
    if raise_alerts and violations:
        alerts_raised = _raise_alerts(
            db, project_id=project_id, kind=kind, source=source, field=field,
            scene_id=scene_id, station_id=station_id, violations=violations,
            index_sample=index_sample, spec=spec, now=now,
        )

    return {
        "chart_kind": kind, "source": source, "field": field,
        "sample_count": len(values),
        "subgroup_size": subgroup_size if groups else None,
        "subgroup_count": len(groups) if groups else None,
        "spec": spec,
        "charts": {name: _chart_payload(chart, index_sample) for name, chart in charts.items()},
        "capability": capability,
        "histogram": spc.histogram(values, bins=min(30, max(5, len(values) // 20 or 5))),
        "violations": violations,
        "violation_count": len(violations),
        "alerts_raised": alerts_raised,
        "notes": notes,
        "generated_at": (now or datetime.utcnow()).isoformat(),
    }


def _raise_alerts(
    db: Session, *, project_id, kind, source, field, scene_id, station_id,
    violations: Sequence[dict], index_sample, spec: dict, now,
) -> int:
    """把判异点登记为 spc_violation 预警：按「图 + 规则」折叠，窗口内重复分析只增计数。"""
    grouped: dict[tuple, list[dict]] = {}
    for item in violations:
        grouped.setdefault((item["chart"], item["rule"]), []).append(item)
    raised = 0
    for (chart_name, rule), items in grouped.items():
        first = items[0]
        sample = index_sample(first["index"])
        alert, was_created = alert_service.create_alert(
            db, project_id=project_id,
            merge_key=f"spc:{kind}:{field}:{chart_name}:{rule}",
            source_type="spc_violation",
            severity="high" if rule == 1 else "warning",
            title=f"SPC 判异：{field} 命中规则 {rule}（{chart_name} 图，{len(items)} 个点）",
            scene_id=scene_id, station_id=station_id,
            sample_key=sample["sample_key"],
            evidence={
                "kind": "spc_violation", "rule": f"{chart_name}:{rule}", "chart": kind,
                "chart_name": chart_name, "field": field, "source": source,
                "point_count": len(items),
                "values": [item["value"] for item in items[:10]],
                "indexes": [item["index"] for item in items[:10]],
                "first_sample_key": first["sample_key"],
                "first_occurred_at": first["occurred_at"],
                "spec": {key: spec.get(key) for key in ("usl", "lsl", "target")},
                "occurred_at": first["occurred_at"]
                or (now or datetime.utcnow()).isoformat(),
            },
            source_ref={"kind": "spc_analysis", "chart": kind, "field": field},
            now=now or datetime.utcnow(),
        )
        if was_created:
            raised += 1
    return raised
