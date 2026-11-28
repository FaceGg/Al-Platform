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
    from app.services.quality_aggregates import (
        MonitorScope,
        alert_series,
        production_by_day,
        scoped_alerts,
    )

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
    # 〔第三轮复审 2026-11-28 口径 9 同源〕NG 率直接复用趋势页同一对聚合函数
    # （production_by_day + alert_series）：分子=窗口关闭的确认 NG（含合并计数），
    # 分母=聚合桶产量——曾「确认异常÷已关闭预警」，与趋势页「确认 NG÷产量」
    # 分子分母皆不同；alert_total 同改走 scoped_alerts（曾无演示过滤）。
    production = production_by_day(db, project_id, scope,
                                   since=window_start, until=window_end)
    alerts_by_day = alert_series(db, project_id, scope,
                                 since=window_start, until=window_end)
    produced_total = sum(int(value.get("total", 0)) for value in production.values())
    confirmed_ng = sum(int(value.get("confirmed_ng", 0)) for value in alerts_by_day.values())
    alerts_total = sum(int(value.get("alerts", 0)) for value in alerts_by_day.values())
    ng_rate = round(confirmed_ng / produced_total, 4) if produced_total else None
    # Top 缺陷：窗口内确认异常按标题聚合 Top5（曾恒 []）
    defect_counts: dict[str, int] = {}
    for title, occurrence in period_alerts.filter(
        QualityAlert.status == "closed",
        QualityAlert.resolution == "confirmed_issue",
    ).with_entities(QualityAlert.title, QualityAlert.occurrence_count).all():
        key = (title or "").strip()[:64] or "未命名"
        defect_counts[key] = defect_counts.get(key, 0) + int(occurrence or 1)
    top_defects = [
        {"defect": name, "count": count}
        for name, count in sorted(defect_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]
    content = {
        "window": [window_start.isoformat(), window_end.isoformat()],
        "alert_total": alerts_total,
        "produced_total": produced_total,
        "confirmed_ng": confirmed_ng,
        "ng_rate": ng_rate,
        "cpk_pass_rate": None,  # Cpk 达标率随 SPC 基线评估接入（B1-06 同源），缺失如实标注
        "top_defects": top_defects,
        "ncr_open": (
            db.query(QmsNcrCapa)
            .filter(QmsNcrCapa.project_id == project_id,
                    QmsNcrCapa.stage.notin_(("closed", "rejected")))
            .count()
        ),
        "footnote": ("窗口 [起,止) UTC；NG 率=确认 NG÷产量，与趋势页共用 "
                     "quality_aggregates 的 production_by_day+alert_series 同源取数；"
                     "演示预警不入统计；top_defects 为窗口内确认异常按标题聚合 Top5"),
    }
    defects_text = "、".join(
        f"{item['defect']}×{item['count']}" for item in top_defects
    ) or "无"
    html = (
        f"<h1>质量报告 {period}/{period_key}</h1>"
        f"<p>预警总量 {content['alert_total']}；产量 {content['produced_total']}；"
        f"确认 NG {content['confirmed_ng']}；NG 率 {content['ng_rate']}；"
        f"Cpk 达标率 {content['cpk_pass_rate']}；未决 NCR {content['ncr_open']}</p>"
        f"<p>Top 缺陷：{defects_text}</p>"
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


def archive_control_plan(db: Session, *, plan_id, actor_id=None) -> QmsControlPlan:
    """归档生效计划（三批复审缺口：原实现只有「双生效拒绝」，无归档流程——
    用户永远建不出第二版，version_diff 无对象可比）。"""
    plan = db.get(QmsControlPlan, plan_id)
    if plan is None:
        raise QmsToolsError("QMS_PLAN_NOT_FOUND")
    if plan.status != "active":
        raise QmsToolsError("QMS_PLAN_ALREADY_ARCHIVED")
    plan.status = "archived"
    plan.archived_at = _now()
    db.flush()
    return plan


def evaluate_tightening(db: Session, *, plan: QmsControlPlan,
                        actor_id=None) -> dict:
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
    # 建议乘数 > 1.0 → 建 recipe_change 审批单（B3-06/D8；三批复审：曾只返回
    # 建议值，乘数永不生效）。同计划已有待批单则不重复建（幂等）。
    if decision["suggested_multiplier"] > 1.0:
        from app.models.approvals import ApprovalRequest

        pending_same_plan = [
            row for row in db.query(ApprovalRequest).filter(
                ApprovalRequest.type == "recipe_change",
                ApprovalRequest.status == "pending",
            ).all()
            if (row.payload or {}).get("plan_id") == str(plan.id)
        ]
        if not pending_same_plan:
            from app.services.approvals import create_approval

            approval = create_approval(
                db, project_id=plan.project_id, approval_type="recipe_change",
                title=(f"控制计划加严：{plan.code} v{plan.version}"
                       f" 建议乘数 {decision['suggested_multiplier']}"),
                payload={
                    "plan_id": str(plan.id),
                    "suggested_multiplier": decision["suggested_multiplier"],
                    "factors": factors,
                },
                initiator_id=actor_id,
            )
            decision["approval_id"] = str(approval.id)
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

# d2 常数表（AIAG MSA 手册，子组容量 2–15）。三批复审：原实现 EV/AV/PV 恒除
# 1.128（仅对 2 次重复成立）且 AV 缺 −EV²/(n·r) 项——按本表随子组容量取值。
_D2_TABLE = {
    2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704, 8: 2.847,
    9: 2.970, 10: 3.078, 11: 3.173, 12: 3.256, 13: 3.332, 14: 3.402, 15: 3.466,
}


def _d2(subgroup: int) -> float:
    value = _D2_TABLE.get(int(subgroup))
    if value is None:
        raise QmsToolsError("MSA_SHAPE_OUT_OF_TABLE")
    return value


def compute_grr(data: dict) -> dict:
    """均值极差法 %GRR/ndc/分级（AIAG MSA 手册通行口径；专家评审标注）。

    data = {"readings": [[操作者][零件][重复] 数值], "tolerance": TV（可缺省）}

    - EV（重复性）= R̄ / d2(重复次数)
    - AV（再现性）= sqrt((X̄diff / d2(操作者))² − EV²/(零件×重复))，根号内非负截 0
    - PV（零件间）= Rp / d2(零件数)；零件数 > 15 超出 d2 表 → 改用零件均值样本
      标准差（σp）近似并在 detail 标注
    - TV 缺省 = sqrt(GRR² + PV²)（总变异，非原实现的 PV 或 1.0）
    - %GRR = GRR/TV×100；ndc = 1.41×PV/GRR
    """
    readings = data.get("readings") or []
    tolerance = float(data.get("tolerance") or 0.0)
    if not readings:
        raise QmsToolsError("MSA_DATA_REQUIRED")
    operators = len(readings)
    parts = len(readings[0]) if readings else 0
    trials = len(readings[0][0]) if readings and readings[0] else 0
    if parts < 1 or trials < 1 or trials > 15 or operators > 15:
        raise QmsToolsError("MSA_SHAPE_OUT_OF_TABLE")
    detail_extra: dict = {}
    ev_ranges = []
    part_means = []  # part_means[操作者][零件] = 该格均值
    for operator_series in readings:
        op_part_means = []
        for part_series in operator_series:
            values = [float(v) for v in part_series]
            ev_ranges.append(max(values) - min(values))
            op_part_means.append(sum(values) / len(values))
        part_means.append(op_part_means)
    r_bar = sum(ev_ranges) / len(ev_ranges)
    ev = r_bar / _d2(trials)
    operator_means = [sum(pm) / parts for pm in part_means]
    x_diff = max(operator_means) - min(operator_means)
    av = 0.0
    if operators >= 2:
        inner = (x_diff / _d2(operators)) ** 2 - (ev * ev) / (parts * trials)
        av = inner ** 0.5 if inner > 0 else 0.0
    grr = (ev * ev + av * av) ** 0.5
    grand = [sum(part_means[o][p] for o in range(operators)) / operators
             for p in range(parts)]
    rp = max(grand) - min(grand)
    if parts <= 15:
        pv = rp / _d2(parts)
    else:
        # 零件数超 d2 表：零件均值样本标准差近似 σp（detail 标注，待专家评审）
        mean_of_grand = sum(grand) / parts
        pv = (sum((value - mean_of_grand) ** 2 for value in grand) / (parts - 1)) ** 0.5
        detail_extra["pv_method"] = "part_mean_sample_std"
    tv = tolerance if tolerance > 0 else ((grr * grr + pv * pv) ** 0.5)
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
        "r_bar": round(r_bar, 6),
        "operators": operators, "parts": parts, "trials": trials,
        **detail_extra,
        "grr_percent": grr_percent, "ndc": ndc, "grade": grade,
        "footnote": "均值极差法（AIAG MSA 手册，d2 随子组容量取值）；待质量专家评审",
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
        # D11「重触发复用同一 SCAR」（第三轮复审 2026-11-28 修复可达性）：曾按
        # **本条新记录**查 iqc_record_id——恒 None，复用分支不可达。现改为同
        # 供应商存在**未关闭** SCAR 即复用（质量问题尚在处理中不叠加新单；
        # 关闭后新不合格开新单——一检验一 SCAR 由唯一约束继续保证）。
        existing = (
            db.query(QmsScar)
            .join(QmsIqcRecord, QmsIqcRecord.id == QmsScar.iqc_record_id)
            .filter(
                QmsScar.project_id == project_id,
                QmsIqcRecord.supplier_id == supplier_id,
                QmsScar.closed_at.is_(None),
            )
            .first()
        )
        if existing is not None:
            record.scar_id = existing.id
            db.flush()
        else:
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
