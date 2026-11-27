"""QMS reports / control plan / MSA / FMEA / IQC-SCAR services (第三批 T2+T3)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.qms import (
    QmsControlPlan,
    QmsFmea,
    QmsIqcRecord,
    QmsMsaStudy,
    QmsNcrCapa,
    QmsQualityReport,
    QmsScar,
    QmsSupplier,
)


class QmsToolsError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _now() -> datetime:
    return datetime.utcnow()


def _period_window(period: str, period_key: str) -> tuple[datetime, datetime]:
    """周期键 → [起, 止) UTC 窗口。

    daily=YYYYMMDD、weekly=YYYYWww（ISO 周，周一为首）、monthly=YYYYMM；
    不可解析的键拒绝（REPORT_PERIOD_KEY_INVALID），不静默按全量出报告。
    """
    try:
        if period == "daily":
            start = datetime.strptime(period_key, "%Y%m%d")
            return start, start + timedelta(days=1)
        if period == "weekly":
            match = re.fullmatch(r"(\d{4})W(\d{2})", period_key)
            if match is None:
                raise ValueError(period_key)
            start = datetime.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
            return start, start + timedelta(days=7)
        if period == "monthly":
            start = datetime.strptime(period_key, "%Y%m")
            end_year = start.year + (1 if start.month == 12 else 0)
            end_month = 1 if start.month == 12 else start.month + 1
            return start, datetime(end_year, end_month, 1)
    except ValueError as error:
        raise QmsToolsError("REPORT_PERIOD_KEY_INVALID") from error
    raise QmsToolsError("REPORT_PERIOD_KEY_INVALID")


def _daily_key(reference: datetime) -> str:
    return (reference.date() - timedelta(days=1)).strftime("%Y%m%d")


def _weekly_key(reference: datetime) -> str:
    last_monday = reference.date() - timedelta(days=reference.date().weekday() + 7)
    iso = last_monday.isocalendar()
    return f"{iso.year}W{iso.week:02d}"


def _monthly_key(reference: datetime) -> str:
    first_of_month = reference.date().replace(day=1)
    return (first_of_month - timedelta(days=1)).strftime("%Y%m")


# ---------------- 质量报告（B3-08；NG 率/Cpk 从聚合模块同源） ----------------

def generate_report(db: Session, *, project_id, period: str, period_key: str,
                    generated_by: str = "manual", created_by_id=None) -> QmsQualityReport:
    from app.models.quality_alerts import QualityAlert
    from app.services.quality_aggregates import MonitorScope, scoped_alerts

    if period not in {"daily", "weekly", "monthly"}:
        raise QmsToolsError("REPORT_PERIOD_INVALID")
    window_start, window_end = _period_window(period, period_key)
    existing = (
        db.query(QmsQualityReport)
        .filter(
            QmsQualityReport.project_id == project_id,
            QmsQualityReport.period == period,
            QmsQualityReport.period_key == period_key,
            QmsQualityReport.generated_by == generated_by,
        )
        .first()
    )
    if existing is not None:
        return existing  # 唯一键幂等（同窗口重生成返回既有行）
    scope = MonitorScope()

    def in_window(query):
        return query.filter(QualityAlert.created_at >= window_start,
                            QualityAlert.created_at < window_end)

    period_alerts = in_window(scoped_alerts(db, project_id, scope))
    closed_alerts = period_alerts.filter(QualityAlert.status == "closed").count()
    confirmed = period_alerts.filter(QualityAlert.status == "closed",
                                     QualityAlert.resolution == "confirmed_issue").count()
    ng_rate = round(confirmed / closed_alerts, 4) if closed_alerts else None
    alerts_total = in_window(
        db.query(QualityAlert).filter(QualityAlert.project_id == project_id)
    ).count()
    content = {
        "window": [window_start.isoformat(), window_end.isoformat()],
        "alert_total": alerts_total,
        "ng_rate": ng_rate,
        "cpk_pass_rate": None,  # Cpk 达标率随 SPC 基线评估接入（B1-06 同源），缺失如实标注
        "top_defects": [],
        "ncr_open": (
            db.query(QmsNcrCapa)
            .filter(QmsNcrCapa.project_id == project_id,
                    QmsNcrCapa.stage.notin_(("closed", "rejected")))
            .count()
        ),
        "footnote": ("窗口 [起,止) UTC；NG 率从 quality_aggregates.scoped_alerts "
                     "单一聚合口径取数（与趋势页同源）；已确认异常÷已关闭"),
    }
    html = (
        f"<h1>质量报告 {period}/{period_key}</h1>"
        f"<p>预警总量 {content['alert_total']}；NG 率 {content['ng_rate']}；"
        f"Cpk 达标率 {content['cpk_pass_rate']}；未决 NCR {content['ncr_open']}</p>"
    )
    report = QmsQualityReport(
        project_id=project_id, period=period, period_key=period_key,
        content=content, html=html, generated_by=generated_by,
        created_by_id=created_by_id,
    )
    db.add(report)
    db.flush()
    return report


def scheduled_due_reports(db: Session, *, now: datetime | None = None) -> dict:
    """beat `qms-report-scheduler`（600s 巡检，D7）：对上一已完结周期补齐
    日报 / 周报 / 月报（generated_by=scheduler）。

    只为有质量活动（预警或 NCR）的项目生成——无活动项目不出空报告；
    generate_report 唯一键幂等，重复巡检不重复出报告。
    """
    from app.models.quality_alerts import QualityAlert

    reference = now or _now()
    periods = {
        "daily": _daily_key(reference),
        "weekly": _weekly_key(reference),
        "monthly": _monthly_key(reference),
    }
    project_ids = {
        row[0] for row in db.query(QualityAlert.project_id).distinct().all()
    } | {
        row[0] for row in db.query(QmsNcrCapa.project_id).distinct().all()
    }
    before = db.query(QmsQualityReport).count()
    # 保持 uuid 对象绑定（sa.Uuid 列不接受 str）；仅排序用 str 键保证确定性
    for project_id in sorted(project_ids, key=str):
        for period, period_key in periods.items():
            generate_report(db, project_id=project_id, period=period,
                            period_key=period_key, generated_by="scheduler")
    created = db.query(QmsQualityReport).count() - before
    return {"projects": len(project_ids), "periods": periods, "created": created}


# ---------------- 动态控制计划（B3-06） ----------------

def create_or_replace_plan(db: Session, *, project_id, code: str,
                           quality_points: list, created_by_id=None) -> QmsControlPlan:
    """新版生效+旧版归档；双生效拒绝（服务层强校验）。"""
    active = (
        db.query(QmsControlPlan)
        .filter(QmsControlPlan.project_id == project_id,
                QmsControlPlan.status == "active")
        .all()
    )
    if active:
        raise QmsToolsError("QMS_PLAN_DUAL_ACTIVE")
    max_version = (
        db.query(QmsControlPlan.version)
        .filter(QmsControlPlan.project_id == project_id)
        .order_by(QmsControlPlan.version.desc())
        .first()
    )
    plan = QmsControlPlan(
        project_id=project_id, code=code,
        version=(max_version[0] if max_version else 0) + 1,
        status="active", quality_points=quality_points,
        created_by_id=created_by_id,
    )
    db.add(plan)
    db.flush()
    return plan


def evaluate_tightening(db: Session, *, plan: QmsControlPlan) -> dict:
    """四因子评估抽样加严：漂移/预警/过程能力/复发 → 建议乘数 + 决策流水
    （可复算）；建议乘数经 recipe_change 审批类型进 S1 审批队列。"""
    from app.models.drift import DriftReport
    from app.models.quality_alerts import QualityAlert

    factors = {}
    recent_severe = (
        db.query(DriftReport)
        .filter(DriftReport.project_id == plan.project_id,
                DriftReport.level == "severe",
                DriftReport.created_at >= _now() - timedelta(days=7))
        .count()
    )
    factors["drift"] = {"severe_reports_7d": recent_severe,
                        "contribution": 0.25 if recent_severe else 0.0}
    open_alerts = (
        db.query(QualityAlert)
        .filter(QualityAlert.project_id == plan.project_id,
                QualityAlert.status.in_(("open", "acknowledged", "processing")))
        .count()
    )
    factors["alerts"] = {"open_count": open_alerts,
                         "contribution": 0.15 if open_alerts >= 10 else 0.0}
    factors["process_capability"] = {"cpk_available": False, "contribution": 0.0}
    open_ncr = (
        db.query(QmsNcrCapa)
        .filter(QmsNcrCapa.project_id == plan.project_id,
                QmsNcrCapa.stage.in_(("action", "verification")))
        .count()
    )
    factors["recurrence"] = {"open_ncr": open_ncr,
                             "contribution": 0.2 if open_ncr else 0.0}
    suggested = 1.0 + sum(item["contribution"] for item in factors.values())
    decision = {
        "evaluated_at": _now().isoformat(),
        "factors": factors,
        "suggested_multiplier": round(min(suggested, 3.0), 2),
        "note": "乘数变更须经审批（recipe_change 进 S1 审批队列）",
    }
    log = list(plan.decision_log or [])
    log.append(decision)
    plan.decision_log = log
    db.flush()
    return decision


def plan_version_diff(db: Session, *, plan_id) -> dict:
    """相邻版本 diff（E24）：与上一归档版逐项对比（质量点/抽样量/乘数）。"""
    plan = db.get(QmsControlPlan, plan_id)
    if plan is None:
        raise QmsToolsError("QMS_PLAN_NOT_FOUND")
    previous = (
        db.query(QmsControlPlan)
        .filter(QmsControlPlan.project_id == plan.project_id,
                QmsControlPlan.version < plan.version)
        .order_by(QmsControlPlan.version.desc())
        .first()
    )
    if previous is None:
        return {"diff": None, "reason": "no_previous_version"}
    old_points = {point.get("name"): point for point in (previous.quality_points or [])}
    new_points = {point.get("name"): point for point in (plan.quality_points or [])}
    changes = []
    for name in sorted(set(old_points) | set(new_points)):
        old = old_points.get(name)
        new = new_points.get(name)
        if old != new:
            changes.append({"quality_point": name, "before": old, "after": new})
    return {
        "from_version": previous.version,
        "to_version": plan.version,
        "multiplier_before": previous.tightening_multiplier,
        "multiplier_after": plan.tightening_multiplier,
        "quality_point_changes": changes,
    }


# ---------------- MSA（B3-01；均值极差法，标注待专家评审） ----------------

def compute_grr(data: dict) -> dict:
    """均值极差法 %GRR/ndc/分级（AIAG 通行口径；专家评审标注）。

    data = {"parts": n, "operators": k, "trials": r,
            "readings": [[操作者][零件][重复] 数值], "tolerance": TV}
    """
    readings = data.get("readings") or []
    tolerance = float(data.get("tolerance") or 0.0)
    if not readings:
        raise QmsToolsError("MSA_DATA_REQUIRED")
    ev_ranges = []
    part_means = []
    operator_means = []
    for operator_series in readings:
        operator_part_means = []
        for part_series in operator_series:
            values = [float(v) for v in part_series]
            ev_ranges.append(max(values) - min(values))
            operator_part_means.append(sum(values) / len(values))
        operator_means.append(sum(operator_part_means) / len(operator_part_means))
        part_means.append(operator_part_means)
    parts = len(readings[0])
    reps = len(readings[0][0]) if readings[0] else 1
    ev = (sum(r * r for r in ev_ranges) / len(ev_ranges)) ** 0.5 / 1.128 if ev_ranges else 0.0
    range_of_means = max(operator_means) - min(operator_means) if operator_means else 0.0
    av = range_of_means / 1.128 if reps else 0.0
    grr = (ev * ev + av * av) ** 0.5
    grand = [sum(part_means[o][p] for o in range(len(readings))) / len(readings)
             for p in range(parts)]
    pv = (max(grand) - min(grand)) / 1.128 if parts else 0.0
    tv = tolerance if tolerance > 0 else (pv if pv > 0 else 1.0)
    grr_percent = round(grr / tv * 100.0, 2) if tv else None
    ndc = int(1.41 * pv / grr) if grr > 0 else None
    if grr_percent is None:
        grade = None
    elif grr_percent < 10:
        grade = "acceptable"
    elif grr_percent <= 30:
        grade = "conditional"
    else:
        grade = "unacceptable"
    return {
        "ev": round(ev, 6), "av": round(av, 6), "grr": round(grr, 6),
        "pv": round(pv, 6), "tv": round(tv, 6),
        "grr_percent": grr_percent, "ndc": ndc, "grade": grade,
        "footnote": "均值极差法（AIAG 通行口径）；待质量专家评审",
    }


# ---------------- FMEA（B3-02；RPN 服务端计算） ----------------

def normalize_fmea_items(items: list) -> list:
    normalized = []
    for item in items or []:
        severity = min(10, max(1, int(item.get("severity") or 1)))
        occurrence = min(10, max(1, int(item.get("occurrence") or 1)))
        detection = min(10, max(1, int(item.get("detection") or 1)))
        normalized.append({
            "failure_mode": str(item.get("failure_mode") or ""),
            "effect": str(item.get("effect") or ""),
            "severity": severity, "occurrence": occurrence, "detection": detection,
            "prevention": str(item.get("prevention") or ""),
            "rpn": severity * occurrence * detection,
        })
    return normalized


def sync_fmea_to_control_plan(db: Session, *, fmea_id, plan_id, actor_id) -> dict:
    """纠正措施一键同步控制计划质量点（生成待审批变更——recipe_change 进 S1）。"""
    fmea = db.get(QmsFmea, fmea_id)
    plan = db.get(QmsControlPlan, plan_id)
    if fmea is None or plan is None:
        raise QmsToolsError("QMS_SYNC_TARGET_NOT_FOUND")
    high_rpn = [item for item in (fmea.items or []) if item.get("rpn", 0) >= 100]
    from app.services.approvals import create_approval

    approval = create_approval(
        db, project_id=fmea.project_id, approval_type="recipe_change",
        title=f"FMEA 同步控制计划：{fmea.name}",
        payload={
            "fmea_id": str(fmea.id), "plan_id": str(plan.id),
            "items": [
                {"failure_mode": item.get("failure_mode"), "rpn": item.get("rpn"),
                 "prevention": item.get("prevention")}
                for item in high_rpn
            ],
        },
        initiator_id=actor_id,
    )
    return {"approval_id": str(approval.id), "high_rpn_items": len(high_rpn)}


# ---------------- IQC → SCAR（B3-05） ----------------

def record_iqc(db: Session, *, project_id, supplier_id, arrival_count: int,
               inspected_count: int, defect_count: int, created_by_id=None):
    """数量约束校验（检验数≤来料数、不良数≤检验数）；不合格自动生成唯一 SCAR
    （一检验一 SCAR；重触发复用同一 SCAR）。"""
    supplier = db.get(QmsSupplier, supplier_id)
    if supplier is None:
        raise QmsToolsError("SUPPLIER_NOT_FOUND")
    if supplier.status == "disabled":
        raise QmsToolsError("SUPPLIER_DISABLED")
    if inspected_count > arrival_count or defect_count > inspected_count:
        raise QmsToolsError("IQC_COUNT_CONSTRAINT")
    record = QmsIqcRecord(
        project_id=project_id, supplier_id=supplier_id,
        arrival_count=int(arrival_count), inspected_count=int(inspected_count),
        defect_count=int(defect_count), created_by_id=created_by_id,
    )
    db.add(record)
    db.flush()
    if defect_count > 0:
        existing = (
            db.query(QmsScar)
            .filter(QmsScar.iqc_record_id == record.id)
            .first()
        )
        if existing is None:
            scar = QmsScar(project_id=project_id, iqc_record_id=record.id)
            db.add(scar)
            db.flush()
            record.scar_id = scar.id
            db.flush()
    return record


def disable_supplier(db: Session, *, supplier_id, actor_id=None) -> QmsSupplier:
    supplier = db.get(QmsSupplier, supplier_id)
    if supplier is None:
        raise QmsToolsError("SUPPLIER_NOT_FOUND")
    supplier.status = "disabled"
    db.flush()
    return supplier
