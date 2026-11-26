"""Quality monitoring aggregates (补齐路线第一批 F3, B1-03/04/05).

驾驶舱、趋势帕累托、实时监控三页**共用本模块这一个聚合口径**（实施计划 §2 F3
同阶段强约束）：KPI 数字 = 下钻列表数字 = 趋势页计数，由 test_quality_monitor 锁死。

数据来源分工（技术方案 §9B D28）：
- 产量 / 正常数：小时聚合桶（inference_result_buckets，永久保留；演示通道不进桶）；
- 预警类指标：预警表（默认排除演示预警，诚实设计⑥）；
- 已确认 NG：结论为「确认异常」的预警按**发生次数**计——同因合并后一条预警可以
  代表多个样本，按条数计会少算。
范围（工厂 / 车间 / 产线 / 工位）经工位归属字段过滤，场景单独作为筛选条件；
所有读路径只碰聚合桶、预警表与工位台账，不扫推理明细（工位卡的「最新一条」除外）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.models.compute import EdgeDevice
from app.models.inference_result import InferenceResult, InferenceResultBucket
from app.models.quality_alerts import QualityAlert
from app.models.quality_domain import QualityScene, QualityStation

OPEN_STATUSES = ("open", "acknowledged", "processing", "review_pending")
HIGH_SEVERITIES = ("high", "critical")
SPC_SOURCES = ("spc_violation", "param_exceed")

# 默认班次（班次表可在平台配置里覆盖，见 D35）
DEFAULT_SHIFTS = (
    ((8, 0), "早班"),
    ((16, 0), "中班"),
    ((0, 0), "夜班"),
)

# 驾驶舱距最后一次有产量的时间超过这个小时数即挂「陈旧数据」横幅（诚实设计①）
STALE_AFTER_HOURS = 24


@dataclass(frozen=True)
class MonitorScope:
    """四级范围（工厂 → 车间 → 产线 → 工位）+ 场景筛选。None 表示该级不限定。

    每个字段都必须带类型标注：dataclass 只把带标注的名称当作字段，漏标注的会变成
    类属性——那样按工位 / 场景筛选就会被静默忽略（测试 test_scope_narrows… 锁住）。
    """

    factory: str | None = None
    workshop: str | None = None
    production_line: str | None = None
    station_id: Any = None
    scene_id: Any = None

    def as_dict(self) -> dict:
        return {
            "factory": self.factory, "workshop": self.workshop,
            "production_line": self.production_line,
            "station_id": str(self.station_id) if self.station_id else None,
            "scene_id": str(self.scene_id) if self.scene_id else None,
        }


def bucket_scope_filters(scope: MonitorScope):
    """聚合桶的范围条件：归属字段在工位表上，场景在桶上。"""
    filters = []
    if scope.factory:
        filters.append(QualityStation.factory == scope.factory)
    if scope.workshop:
        filters.append(QualityStation.workshop == scope.workshop)
    if scope.production_line:
        filters.append(QualityStation.production_line == scope.production_line)
    if scope.station_id:
        filters.append(InferenceResultBucket.station_id == scope.station_id)
    if scope.scene_id:
        filters.append(InferenceResultBucket.scene_id == scope.scene_id)
    return filters


def alert_scope_filters(scope: MonitorScope):
    filters = []
    if scope.factory:
        filters.append(QualityStation.factory == scope.factory)
    if scope.workshop:
        filters.append(QualityStation.workshop == scope.workshop)
    if scope.production_line:
        filters.append(QualityStation.production_line == scope.production_line)
    if scope.station_id:
        filters.append(QualityAlert.station_id == scope.station_id)
    if scope.scene_id:
        filters.append(QualityAlert.scene_id == scope.scene_id)
    return filters


def scoped_buckets(db: Session, project_id, scope: MonitorScope) -> Query:
    return (
        db.query(InferenceResultBucket)
        .outerjoin(QualityStation, QualityStation.id == InferenceResultBucket.station_id)
        .filter(InferenceResultBucket.project_id == project_id, *bucket_scope_filters(scope))
    )


def scoped_alerts(db: Session, project_id, scope: MonitorScope) -> Query:
    """预警的基础查询：排除演示预警（诚实设计⑥）。"""
    return (
        db.query(QualityAlert)
        .outerjoin(QualityStation, QualityStation.id == QualityAlert.station_id)
        .filter(
            QualityAlert.project_id == project_id,
            QualityAlert.is_demo.is_(False),
            *alert_scope_filters(scope),
        )
    )


def production_totals(db: Session, project_id, scope: MonitorScope, *, since, until) -> dict:
    """时间窗内的产量 / 正常数 / 异常数（读聚合桶）。"""
    total, ok, anomaly = (
        scoped_buckets(db, project_id, scope)
        .filter(
            InferenceResultBucket.bucket_start >= since,
            InferenceResultBucket.bucket_start < until,
        )
        .with_entities(
            func.coalesce(func.sum(InferenceResultBucket.total), 0),
            func.coalesce(func.sum(InferenceResultBucket.ok_count), 0),
            func.coalesce(func.sum(InferenceResultBucket.anomaly_count), 0),
        )
        .one()
    )
    return {"total": int(total), "ok": int(ok), "anomaly": int(anomaly)}


def production_by_day(db: Session, project_id, scope: MonitorScope, *, since, until) -> dict:
    """按日的产量 / 异常数，键为 YYYY-MM-DD（读聚合桶，不扫明细）。"""
    rows = (
        scoped_buckets(db, project_id, scope)
        .filter(
            InferenceResultBucket.bucket_start >= since,
            InferenceResultBucket.bucket_start < until,
        )
        .with_entities(
            func.date(InferenceResultBucket.bucket_start),
            func.sum(InferenceResultBucket.total),
            func.sum(InferenceResultBucket.anomaly_count),
        )
        .group_by(func.date(InferenceResultBucket.bucket_start))
        .all()
    )
    return {str(day): {"total": int(total or 0), "anomaly": int(anomaly or 0)} for day, total, anomaly in rows}


def last_production_at(db: Session, project_id, scope: MonitorScope):
    """范围内最近一次有产量的时间；从未生产返回 None。"""
    return (
        scoped_buckets(db, project_id, scope)
        .filter(InferenceResultBucket.total > 0)
        .with_entities(func.max(InferenceResultBucket.bucket_start))
        .scalar()
    )


def stale_state(db: Session, project_id, scope: MonitorScope, *, now: datetime) -> dict:
    """陈旧数据横幅的判定（诚实设计①）：距最后一次有产量超过 24 小时。"""
    latest = last_production_at(db, project_id, scope)
    if latest is None:
        return {"stale": True, "last_production_at": None, "hours": None, "never_produced": True}
    hours = (now - latest).total_seconds() / 3600.0
    return {
        "stale": hours > STALE_AFTER_HOURS,
        "last_production_at": latest.isoformat(),
        "hours": round(hours, 1),
        "never_produced": False,
    }


def alert_kpis(db: Session, project_id, scope: MonitorScope, *, since, until) -> dict:
    """驾驶舱六卡里预警侧的口径与命中率。"""
    base = scoped_alerts(db, project_id, scope)
    in_window = base.filter(
        QualityAlert.created_at >= since, QualityAlert.created_at < until,
    )
    open_now = base.filter(QualityAlert.status.in_(OPEN_STATUSES))
    high_now = open_now.filter(QualityAlert.severity.in_(HIGH_SEVERITIES))
    closed_in_window = base.filter(
        QualityAlert.status == "closed",
        QualityAlert.closed_at >= since, QualityAlert.closed_at < until,
    )
    confirmed = closed_in_window.filter(QualityAlert.resolution == "confirmed_issue")
    confirmed_ng = confirmed.with_entities(
        func.coalesce(func.sum(QualityAlert.occurrence_count), 0),
    ).scalar()
    closed_count = closed_in_window.with_entities(func.count(QualityAlert.id)).scalar()
    confirmed_count = confirmed.with_entities(func.count(QualityAlert.id)).scalar()
    by_severity = dict(
        in_window.with_entities(QualityAlert.severity, func.count(QualityAlert.id))
        .group_by(QualityAlert.severity).all()
    )
    return {
        "alerts_in_window": int(in_window.with_entities(func.count(QualityAlert.id)).scalar()),
        "open": int(open_now.with_entities(func.count(QualityAlert.id)).scalar()),
        "high_risk": int(high_now.with_entities(func.count(QualityAlert.id)).scalar()),
        "sla_overdue": int(
            open_now.filter(QualityAlert.sla_due_at < datetime.utcnow())
            .with_entities(func.count(QualityAlert.id)).scalar()
        ),
        "confirmed_ng": int(confirmed_ng),
        "closed_in_window": int(closed_count),
        "by_severity": {str(key): int(value) for key, value in by_severity.items()},
        # 命中率口径（诚实设计②，页内注明）：已确认异常 ÷ 已关闭预警
        "hit_rate": (int(confirmed_count) / int(closed_count)) if closed_count else None,
    }


def disposition_ops(
    db: Session, project_id, scope: MonitorScope, *, since, until, pieces: int,
) -> dict:
    """处置运营三指标（E09）：每千件处置单数、首次处理均时、结案率。"""
    base = scoped_alerts(db, project_id, scope)
    closed_count = base.filter(
        QualityAlert.status == "closed",
        QualityAlert.closed_at >= since, QualityAlert.closed_at < until,
    ).with_entities(func.count(QualityAlert.id)).scalar()
    created = base.filter(
        QualityAlert.created_at >= since, QualityAlert.created_at < until,
    )
    created_count = created.with_entities(func.count(QualityAlert.id)).scalar()
    created_closed = created.filter(QualityAlert.status == "closed").with_entities(
        func.count(QualityAlert.id),
    ).scalar()
    # 时间差的均值在 Python 里算：两个方言的时间函数不通用
    ack_rows = base.filter(
        QualityAlert.first_ack_at.isnot(None),
        QualityAlert.first_ack_at >= since, QualityAlert.first_ack_at < until,
    ).with_entities(QualityAlert.first_ack_at, QualityAlert.created_at).all()
    ack_seconds = [
        (acked - created_at).total_seconds() for acked, created_at in ack_rows
    ]
    return {
        "per_thousand": (int(closed_count) / pieces * 1000.0) if pieces else None,
        "mean_first_ack_seconds": (
            sum(ack_seconds) / len(ack_seconds) if ack_seconds else None
        ),
        "acknowledged": len(ack_seconds),
        "closure_rate": (int(created_closed) / int(created_count)) if created_count else None,
        "closed_in_window": int(closed_count),
        "created_in_window": int(created_count),
    }


# ----------------------------------------------------------------------
# 走势与帕累托（B1-04）
# ----------------------------------------------------------------------

PARETO_DIMENSIONS = ("defect", "station", "device", "product", "batch")


def alert_series(db: Session, project_id, scope: MonitorScope, *, since, until) -> dict:
    """按日的预警与确认 NG（按发生次数）。预警按产生日归档，确认 NG 按关闭日归档。"""
    rows = (
        scoped_alerts(db, project_id, scope)
        .filter(QualityAlert.created_at >= since, QualityAlert.created_at < until)
        .with_entities(
            QualityAlert.created_at, QualityAlert.severity, QualityAlert.source_type,
            QualityAlert.resolution, QualityAlert.occurrence_count,
            QualityAlert.status, QualityAlert.closed_at,
        )
        .all()
    )
    series: dict[str, dict] = {}

    def _bucket(day: str) -> dict:
        return series.setdefault(day, {
            "alerts": 0, "high": 0, "critical": 0, "spc_exceed": 0,
            "confirmed_ng": 0, "closed": 0,
        })

    for row in rows:
        bucket = _bucket(row.created_at.strftime("%Y-%m-%d"))
        bucket["alerts"] += 1
        if row.severity in HIGH_SEVERITIES:
            bucket[row.severity] += 1
        if row.source_type in SPC_SOURCES:
            bucket["spc_exceed"] += 1
        if (
            row.status == "closed" and row.closed_at is not None
            and since <= row.closed_at < until
        ):
            bucket["closed"] += 1
            if row.resolution == "confirmed_issue":
                bucket = _bucket(row.closed_at.strftime("%Y-%m-%d"))
                bucket["confirmed_ng"] += int(row.occurrence_count or 1)
    return series


def trend_view(db: Session, project_id, scope: MonitorScope, *, since, until) -> dict:
    """按日走势：产量（聚合桶）+ 预警与确认 NG（预警表）。"""
    production = production_by_day(db, project_id, scope, since=since, until=until)
    alerts = alert_series(db, project_id, scope, since=since, until=until)
    points = []
    for day in sorted(set(production) | set(alerts)):
        produced = production.get(day, {})
        counted = alerts.get(day, {})
        total = int(produced.get("total", 0))
        confirmed_ng = int(counted.get("confirmed_ng", 0))
        points.append({
            "date": day,
            "total": total,
            "anomaly": int(produced.get("anomaly", 0)),
            "alerts": int(counted.get("alerts", 0)),
            "high": int(counted.get("high", 0)),
            "critical": int(counted.get("critical", 0)),
            "spc_exceed": int(counted.get("spc_exceed", 0)),
            "closed": int(counted.get("closed", 0)),
            "confirmed_ng": confirmed_ng,
            "ng_rate": (confirmed_ng / total) if total else None,
        })
    totals = {
        key: sum(int(point[key]) for point in points)
        for key in ("total", "anomaly", "alerts", "high", "critical", "spc_exceed",
                    "closed", "confirmed_ng")
    }
    totals["ng_rate"] = (
        totals["confirmed_ng"] / totals["total"] if totals["total"] else None
    )
    return {"points": points, "totals": totals}


def pareto(
    db: Session, project_id, scope: MonitorScope, *, since, until,
    dimension: str, vocabulary: dict | None = None,
) -> dict:
    """帕累托：按发生次数对窗内预警分组。JSON 证据的提取在 Python 里做
    （两个方言的 JSON 函数不通用），预警量远小于推理明细。
    """
    if dimension not in PARETO_DIMENSIONS:
        raise ValueError("PARETO_DIMENSION_INVALID")
    rows = (
        scoped_alerts(db, project_id, scope)
        .filter(QualityAlert.created_at >= since, QualityAlert.created_at < until)
        .with_entities(
            QualityAlert.evidence, QualityAlert.station_id, QualityAlert.device_id,
            QualityAlert.product_code, QualityAlert.batch_no,
            QualityAlert.occurrence_count,
        )
        .all()
    )
    station_names = {
        str(station_id): name
        for station_id, name in _station_names(db, project_id).items()
    } if dimension == "station" else {}
    device_names = _device_names(db) if dimension == "device" else {}
    vocabulary = vocabulary or {}
    counts: dict[tuple[str, str], int] = {}
    for evidence, station_id, device_id, product, batch, occurrences in rows:
        weight = int(occurrences or 1)
        if dimension == "defect":
            label = str((evidence or {}).get("predicted_label") or "")
            if not label:
                key, display = "__unlabeled__", "未标注预测标签"
            else:
                key = label
                display = str(vocabulary.get(label) or label)
        elif dimension == "station":
            if station_id is None:
                key, display = "__none__", "未关联工位"
            else:
                key = str(station_id)
                display = station_names.get(key) or key
        elif dimension == "device":
            if device_id is None:
                key, display = "__none__", "未关联设备"
            else:
                key = str(device_id)
                display = device_names.get(key) or key
        elif dimension == "product":
            key = str(product or "__none__")
            display = str(product) if product else "未上报产品"
        else:
            key = str(batch or "__none__")
            display = str(batch) if batch else "未上报批次"
        counts[(key, display)] = counts.get((key, display), 0) + weight
    total = sum(counts.values())
    items = []
    running = 0
    for (key, display), count in sorted(counts.items(), key=lambda item: (-item[1], item[0][0])):
        running += count
        items.append({
            "key": key, "label": display, "count": count,
            "ratio": (count / total) if total else 0.0,
            "cumulative": (running / total) if total else 0.0,
        })
    return {"dimension": dimension, "total": total, "items": items}


# ----------------------------------------------------------------------
# 驾驶舱的排名 / 分布 / 最近异常（B1-03）
# ----------------------------------------------------------------------

def station_ranking(db: Session, project_id, scope: MonitorScope, *, since, until, limit=10):
    rows = (
        scoped_alerts(db, project_id, scope)
        .filter(QualityAlert.created_at >= since, QualityAlert.created_at < until)
        .with_entities(
            QualityAlert.station_id, QualityAlert.severity, QualityAlert.status,
            QualityAlert.occurrence_count,
        )
        .all()
    )
    stats: dict = {}
    for station_id, severity, status, occurrences in rows:
        item = stats.setdefault(station_id, {
            "alerts": 0, "open": 0, "high_risk": 0, "occurrences": 0,
        })
        item["alerts"] += 1
        item["occurrences"] += int(occurrences or 1)
        if status in OPEN_STATUSES:
            item["open"] += 1
            if severity in HIGH_SEVERITIES:
                item["high_risk"] += 1
    names = _station_names(db, project_id)
    ranked = []
    for station_id, item in stats.items():
        if station_id is None:
            continue
        ranked.append({
            "station_id": str(station_id), "station": names.get(station_id, str(station_id)),
            **item,
        })
    ranked.sort(key=lambda item: (-item["high_risk"], -item["open"], -item["occurrences"]))
    return ranked[:limit]


def recent_alerts(db: Session, project_id, scope: MonitorScope, *, limit=10):
    rows = (
        scoped_alerts(db, project_id, scope)
        .order_by(QualityAlert.created_at.desc(), QualityAlert.id.asc())
        .limit(limit)
        .all()
    )
    names = _station_names(db, project_id)
    return [
        {
            "id": str(row.id), "title": row.title, "severity": row.severity,
            "source_type": row.source_type, "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "station": names.get(row.station_id) if row.station_id else None,
            "occurrence_count": int(row.occurrence_count or 1),
        }
        for row in rows
    ]


def scoped_stations(db: Session, project_id, scope: MonitorScope) -> list:
    """范围内的启用工位（按工位归属字段过滤）。"""
    return (
        db.query(QualityStation)
        .join(QualityScene, QualityScene.id == QualityStation.scene_id)
        .filter(
            QualityScene.project_id == project_id,
            QualityStation.enabled.is_(True),
            *[
                condition for condition in (
                    QualityStation.factory == scope.factory if scope.factory else None,
                    QualityStation.workshop == scope.workshop if scope.workshop else None,
                    QualityStation.production_line == scope.production_line
                    if scope.production_line else None,
                    QualityStation.id == scope.station_id if scope.station_id else None,
                    QualityStation.scene_id == scope.scene_id if scope.scene_id else None,
                ) if condition is not None
            ],
        )
        .order_by(QualityStation.code.asc())
        .all()
    )


def scope_options(db: Session, project_id) -> dict:
    """工厂 / 车间 / 产线的可选值：取自本项目工位的归属字段（去重、去空）。"""
    rows = (
        db.query(QualityStation.factory, QualityStation.workshop, QualityStation.production_line)
        .join(QualityScene, QualityScene.id == QualityStation.scene_id)
        .filter(QualityScene.project_id == project_id)
        .all()
    )
    options: dict[str, list[str]] = {"factory": [], "workshop": [], "production_line": []}
    for factory, workshop, line in rows:
        for key, value in (("factory", factory), ("workshop", workshop),
                           ("production_line", line)):
            if value and value not in options[key]:
                options[key].append(value)
    return {key: sorted(values) for key, values in options.items()}


def _station_names(db: Session, project_id) -> dict:
    rows = (
        db.query(QualityStation.id, QualityStation.name, QualityStation.code)
        .join(QualityScene, QualityScene.id == QualityStation.scene_id)
        .filter(QualityScene.project_id == project_id)
        .all()
    )
    return {station_id: f"{name}（{code}）" for station_id, name, code in rows}


def _device_names(db: Session) -> dict:
    return {
        str(device_id): name
        for device_id, name in db.query(EdgeDevice.id, EdgeDevice.name).all()
    }


# ----------------------------------------------------------------------
# 产线状态（B1-03）
# ----------------------------------------------------------------------

def line_status(db: Session, project_id, scope: MonitorScope, *, now: datetime) -> list[dict]:
    """产线状态分布：每条产线的工位数、有未关闭预警的工位数、离线设备数。"""
    from app.services.quality_alerts import _heartbeat_stale

    stations = scoped_stations(db, project_id, scope)
    devices = _devices_for(db, stations)
    open_by_station = dict(
        scoped_alerts(db, project_id, scope)
        .filter(QualityAlert.status.in_(OPEN_STATUSES))
        .with_entities(QualityAlert.station_id, func.count(QualityAlert.id))
        .group_by(QualityAlert.station_id)
        .all()
    )
    grouped: dict[str, dict] = {}
    for station in stations:
        line = station.production_line or "未归属产线"
        item = grouped.setdefault(line, {
            "line": line, "stations": 0, "stations_with_open_alerts": 0,
            "offline_devices": 0,
        })
        item["stations"] += 1
        if int(open_by_station.get(station.id, 0) or 0) > 0:
            item["stations_with_open_alerts"] += 1
        device = devices.get(station.edge_device_id) if station.edge_device_id else None
        if device is not None and _heartbeat_stale(device.last_heartbeat, now):
            item["offline_devices"] += 1
    return sorted(grouped.values(), key=lambda item: item["line"])


def _devices_for(db: Session, stations) -> dict:
    device_ids = {station.edge_device_id for station in stations if station.edge_device_id}
    if not device_ids:
        return {}
    return {
        device.id: device
        for device in db.query(EdgeDevice).filter(EdgeDevice.id.in_(device_ids)).all()
    }


def _open_alert_counts(db, project_id, scope: MonitorScope) -> dict:
    return dict(
        scoped_alerts(db, project_id, scope)
        .filter(QualityAlert.status.in_(OPEN_STATUSES))
        .with_entities(QualityAlert.station_id, func.count(QualityAlert.id))
        .group_by(QualityAlert.station_id)
        .all()
    )


# ----------------------------------------------------------------------
# 项目级配置（平台配置键里编码项目 id）与班次
# ----------------------------------------------------------------------

OPTION_NG_VOCABULARY = "quality.ng_vocabulary"
OPTION_SHIFT_SCHEDULE = "quality.shift_schedule"


def project_option_key(prefix: str, project_id) -> str:
    key = f"{prefix}:{project_id}"
    if len(key) > 64:
        raise ValueError("PROJECT_OPTION_KEY_TOO_LONG")
    return key


def load_project_option(db: Session, prefix: str, project_id, default=None):
    from app.models.platform_option import get_option

    value = get_option(db, project_option_key(prefix, project_id))
    return default if value is None else value


def store_project_option(db: Session, prefix: str, project_id, value) -> None:
    """写入平台配置。注意 set_option 内部自行 commit（与既有先例一致）。"""
    from app.models.platform_option import set_option

    set_option(db, project_option_key(prefix, project_id), value)


def normalize_shift_schedule(raw) -> list:
    """班次表归一为 [[时, 分, 名称], ...]；缺失或非法时回落默认班次。"""
    try:
        result = []
        for hour, minute, label in raw:
            hour, minute = int(hour), int(minute)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError(hour)
            result.append([hour, minute, str(label)[:16]])
        if not result:
            raise ValueError("empty")
        return result
    except (TypeError, ValueError):
        return [[hour, minute, label] for (hour, minute), label in DEFAULT_SHIFTS]


def current_shift_start(now: datetime, schedule=None) -> tuple[datetime, str]:
    """当前班次的起点与名称：取不晚于 now 的最近一个班次起点（可能是昨天）。"""
    candidates = []
    for hour, minute, label in normalize_shift_schedule(schedule):
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start > now:
            start -= timedelta(days=1)
        candidates.append((start, label))
    return max(candidates, key=lambda item: item[0])


# ----------------------------------------------------------------------
# 实时生产监控（B1-05）
# ----------------------------------------------------------------------

def _device_view(device, now: datetime) -> dict | None:
    from app.services.quality_alerts import _heartbeat_stale

    if device is None:
        return None
    return {
        "id": str(device.id), "name": device.name, "status": device.status,
        # 在线 = 心跳未过期（与设备巡检同一口径）
        "online": not _heartbeat_stale(device.last_heartbeat, now),
        "last_heartbeat": device.last_heartbeat.isoformat() if device.last_heartbeat else None,
    }


def station_cards(
    db: Session, project_id, scope: MonitorScope, *, now: datetime, shift_start: datetime,
) -> list[dict]:
    """工位卡：产品、批次、最新生产时间、OK/NG、班次产量、风险分数、设备状态。

    「最新一条」按工位逐个取推理明细（走 _110 的 (station_id, occurred_at) 索引）；
    班次产量读聚合桶；设备状态读设备台账的心跳。
    """
    stations = scoped_stations(db, project_id, scope)
    if not stations:
        return []
    names = _station_names(db, project_id)
    scene_names = dict(
        db.query(QualityScene.id, QualityScene.name)
        .filter(QualityScene.project_id == project_id).all()
    )
    devices = _devices_for(db, stations)
    shift_floor = shift_start.replace(minute=0, second=0, microsecond=0)
    shift_by_station = {
        station_id: (int(total or 0), int(anomaly or 0))
        for station_id, total, anomaly in
        scoped_buckets(db, project_id, scope)
        .filter(InferenceResultBucket.bucket_start >= shift_floor)
        .with_entities(
            InferenceResultBucket.station_id,
            func.sum(InferenceResultBucket.total),
            func.sum(InferenceResultBucket.anomaly_count),
        )
        .group_by(InferenceResultBucket.station_id)
        .all()
    }
    open_by_station = _open_alert_counts(db, project_id, scope)
    cards = []
    for station in stations:
        latest = (
            db.query(InferenceResult)
            .filter(
                InferenceResult.project_id == project_id,
                InferenceResult.station_id == station.id,
                InferenceResult.channel != "demo",
            )
            .order_by(InferenceResult.occurred_at.desc(), InferenceResult.id.asc())
            .first()
        )
        latest_alert = (
            scoped_alerts(db, project_id, scope)
            .filter(QualityAlert.station_id == station.id)
            .order_by(QualityAlert.created_at.desc(), QualityAlert.id.asc())
            .first()
        )
        shift_total, shift_anomaly = shift_by_station.get(station.id, (0, 0))
        cards.append({
            "station_id": str(station.id),
            "code": station.code,
            "name": station.name,
            "scene": scene_names.get(station.scene_id),
            "factory": station.factory,
            "workshop": station.workshop,
            "production_line": station.production_line,
            "responsible_user_id": (
                str(station.responsible_user_id) if station.responsible_user_id else None
            ),
            "product": latest.product_code if latest else None,
            "batch": latest.batch_no if latest else None,
            "shift": latest.shift if latest else None,
            "last_production_at": (
                latest.occurred_at.isoformat() if latest and latest.occurred_at else None
            ),
            "result": (
                "anomaly" if latest.is_anomaly else "ok" if latest.is_anomaly is False
                else latest.predicted_label
            ) if latest else None,
            "score": (
                latest.probability if latest.probability is not None else latest.anomaly_score
            ) if latest else None,
            "predicted_label": latest.predicted_label if latest else None,
            "shift_total": shift_total,
            "shift_anomaly": shift_anomaly,
            "open_alerts": int(open_by_station.get(station.id, 0) or 0),
            "latest_alert": ({
                "id": str(latest_alert.id), "title": latest_alert.title,
                "severity": latest_alert.severity, "status": latest_alert.status,
                "created_at": (
                    latest_alert.created_at.isoformat() if latest_alert.created_at else None
                ),
            } if latest_alert else None),
            "device": _device_view(
                devices.get(station.edge_device_id) if station.edge_device_id else None, now,
            ),
        })
    return cards


def production_tree(db: Session, project_id, scope: MonitorScope, *, now: datetime) -> list[dict]:
    """产线 / 工位 / 设备三级树：取自工位归属与设备台账（不从推理记录推导）。"""
    stations = scoped_stations(db, project_id, scope)
    names = _station_names(db, project_id)
    devices = _devices_for(db, stations)
    open_by_station = _open_alert_counts(db, project_id, scope)
    lines: dict[str, list] = {}
    for station in stations:
        line = station.production_line or "未归属产线"
        lines.setdefault(line, []).append({
            "key": str(station.id),
            "title": names.get(station.id) or station.code,
            "open_alerts": int(open_by_station.get(station.id, 0) or 0),
            "device": _device_view(
                devices.get(station.edge_device_id) if station.edge_device_id else None, now,
            ),
        })
    return [
        {"key": f"line:{line}", "title": line, "children": children}
        for line, children in sorted(lines.items())
    ]
