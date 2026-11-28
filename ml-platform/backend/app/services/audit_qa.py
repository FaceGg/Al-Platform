"""Audit QA reports + metric-registry ask-data (补齐路线第二批 S4, B2-01).

十类模板的结构化取数+证据清单+引用编号全局唯一+生成后「引用提示与证据
清单同表」校验（竞品 E1/E2 编号跨小节重复是反面教材）；问数只走指标
注册表（LLM 只做意图识别与参数抽取、不生成 SQL；未命中注册表拒绝）。
叙述生成经网关调用自动入 B2-08 动作审计。
"""
from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.audit_qa import AuditReport, REPORT_TEMPLATES

# 指标注册表内置条目（qa.metric_registry PlatformOption 可扩展）：
# 指标名 → SQL 模板（命名占位符 :project_id）+ 口径脚注
BUILTIN_METRIC_REGISTRY = {
    "预警总量": {
        "sql": "SELECT COUNT(*) AS value FROM quality_alerts WHERE project_id = :project_id",
        "params": [],
        "footnote": "统计项目全部预警行数（含已关闭）",
    },
    "未处理预警数": {
        "sql": ("SELECT COUNT(*) AS value FROM quality_alerts "
                "WHERE project_id = :project_id AND status IN ('open','acknowledged','processing')"),
        "params": [],
        "footnote": "状态 ∈ open/acknowledged/processing",
    },
    "已关闭预警数": {
        "sql": ("SELECT COUNT(*) AS value FROM quality_alerts "
                "WHERE project_id = :project_id AND status = 'closed'"),
        "params": [],
        "footnote": "status = closed",
    },
    "推理量": {
        "sql": ("SELECT COUNT(*) AS value FROM inference_results "
                "WHERE project_id = :project_id AND channel = 'online'"),
        "params": [],
        "footnote": "保留期内的 online 推理明细行数",
    },
    "误报率": {
        "sql": ("SELECT CAST(SUM(CASE WHEN resolution = 'false_positive' THEN 1 ELSE 0 END) AS FLOAT) "
                "/ NULLIF(CAST(COUNT(*) AS FLOAT), 0) AS value FROM quality_alerts "
                "WHERE project_id = :project_id AND status = 'closed'"),
        "params": [],
        "footnote": "已关闭预警中 resolution=false_positive 占比",
    },
    "处置均时": {
        "sql": ("SELECT AVG(CAST(julianday(closed_at) - julianday(created_at) AS REAL)) AS value "
                "FROM quality_alerts WHERE project_id = :project_id AND status = 'closed' "
                "AND closed_at IS NOT NULL"),
        "params": [],
        "footnote": "closed − created 天数均值（SQLite julianday 口径；PG 由 CI 背书）",
    },
    "盲测样本量": {
        "sql": ("SELECT COUNT(*) AS value FROM dataset_split_members "
                "WHERE role = 'blind' AND split_id IN ("
                "  SELECT split_id FROM modeling_rounds WHERE project_id = :project_id)"),
        "params": [],
        "footnote": "项目全部轮次的盲测成员行数",
    },
    "最近漂移等级": {
        "sql": ("SELECT level AS value FROM drift_reports WHERE project_id = :project_id "
                "ORDER BY created_at DESC LIMIT 1"),
        "params": [],
        "footnote": "最近一份漂移报告的 level",
    },
}

_METRIC_ALIASES = {
    "预警总量": ["预警总量"],
    "未处理": ["未处理预警数"],
    "已关闭": ["已关闭预警数"],
    "推理量": ["推理量"],
    "推理次数": ["推理量"],
    "误报率": ["误报率"],
    "误报": ["误报率"],
    "处置均时": ["处置均时"],
    "盲测样本量": ["盲测样本量"],
    "盲测": ["盲测样本量"],
    "漂移等级": ["最近漂移等级"],
}


class AuditQAError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _citation_renumber(items: list[dict]) -> list[dict]:
    """引用编号全局唯一编号器：E1..En 单调，不允许跨节复用。"""
    for index, item in enumerate(items, start=1):
        item["ref"] = f"E{index}"
    return items


def validate_citations(content_markdown: str, evidence: list[dict]) -> list[str]:
    """生成后校验：正文引用编号 ⊆ 证据清单（竞品反面教材防线）。"""
    cited = set(re.findall(r"\[(E\d+)\]", content_markdown or ""))
    known = {item.get("ref") for item in evidence}
    errors = [f"引用 {ref} 不在证据清单" for ref in sorted(cited - known)]
    unused = sorted(known - cited)
    if unused:
        errors.append(f"证据未被引用: {','.join(sorted(unused))}")
    return errors


def build_report(
    db: Session,
    *,
    project_id,
    template_key: str,
    params: dict | None = None,
    created_by_id=None,
) -> AuditReport:
    """十类模板：结构化取数 → 证据清单（全局唯一编号）→ 叙述（LLM 经网关，
    失败回退纯数据版）→ 生成后校验。"""
    if template_key not in REPORT_TEMPLATES:
        raise AuditQAError("AUDIT_TEMPLATE_INVALID")
    params = dict(params or {})
    evidence = _citation_renumber(_collect_evidence(
        db, project_id=project_id, template_key=template_key, params=params,
    ))
    narrative = _narrative(
        db, project_id=project_id, template_key=template_key, evidence=evidence,
    )
    content = _render_markdown(template_key, evidence, narrative)
    citation_errors = validate_citations(content, evidence)
    report = AuditReport(
        project_id=project_id, template_key=template_key,
        params=params, content_markdown=content,
        evidence=evidence, citation_errors=citation_errors,
        status="final" if not citation_errors else "draft",
        created_by_id=created_by_id,
    )
    db.add(report)
    db.flush()
    return report


def _collect_evidence(db: Session, *, project_id, template_key: str, params: dict) -> list[dict]:
    """按模板聚合证据行（引用清单：表名+记录 id+摘要）。"""
    from app.models.agent_audit import AgentActionAudit
    from app.models.approvals import ApprovalRequest
    from app.models.quality_alerts import QualityAlert
    from app.models.release_governance import ReleaseCheck

    items: list[dict] = []
    if template_key in {"quality", "alerts", "disposition", "root_cause"}:
        alerts = (
            db.query(QualityAlert)
            .filter(QualityAlert.project_id == project_id)
            .order_by(QualityAlert.created_at.desc())
            .limit(10)
            .all()
        )
        for alert in alerts:
            items.append({
                "table": "quality_alerts", "record_id": str(alert.id),
                "summary": f"[{alert.severity}] {alert.title}（{alert.status}）",
            })
    if template_key in {"agent_actions"}:
        # 按项目过滤（三批复审：曾全表查询把他项目动作写进本项目报告）
        rows = (
            db.query(AgentActionAudit)
            .filter(AgentActionAudit.project_id == project_id)
            .order_by(AgentActionAudit.created_at.desc())
            .limit(10)
            .all()
        )
        for row in rows:
            items.append({
                "table": "agent_action_audits", "record_id": str(row.id),
                "summary": f"{row.agent_type}/{row.tool_name} {row.status} {row.duration_ms}ms",
            })
    if template_key in {"model"}:
        # 按项目过滤（ModelLibrary 无 project_id，经本项目的 model_release
        # 审批单关联——与 S1 存量投影口径一致）
        checks = (
            db.query(ReleaseCheck)
            .filter(ReleaseCheck.approval_id.in_(
                db.query(ApprovalRequest.id).filter(
                    ApprovalRequest.project_id == project_id,
                    ApprovalRequest.type == "model_release",
                )
            ))
            .limit(10)
            .all()
        )
        for check in checks:
            items.append({
                "table": "release_checks", "record_id": str(check.id),
                "summary": f"{check.check_key}={check.verdict}",
            })
    if template_key in {"spc", "drift", "labeling", "process_window"}:
        from app.models.drift import DriftReport

        rows = (
            db.query(DriftReport)
            .filter(DriftReport.project_id == project_id)
            .order_by(DriftReport.created_at.desc())
            .limit(10)
            .all()
        )
        for row in rows:
            items.append({
                "table": "drift_reports", "record_id": str(row.id),
                "summary": f"漂移 {row.level}（样本 {row.sample_count}）",
            })
    if not items:
        items.append({
            "table": "none", "record_id": None,
            "summary": "窗口内无记录（空态如实呈现）",
        })
    return items


def _narrative(db: Session, *, project_id, template_key: str, evidence: list[dict]) -> str:
    """叙述生成（三批复审补实现——曾恒返回回退文案，「LLM 叙述 not_run」实为
    未实现）：LLM 经网关（自动入 B2-08 动作审计，purpose=audit_report）；
    不可用回退纯数据版。"""
    summary_lines = [
        f"- [{item.get('table')}] {item.get('summary')}"
        for item in evidence[:10]
    ]
    fallback = (
        f"（LLM 叙述不可用，以下为结构化要点）模板 {template_key} 共 "
        f"{len(evidence)} 条证据：\n" + "\n".join(summary_lines)
    )
    try:
        from app.services.llm_gateway import chat_completion, resolve_profile

        config = resolve_profile(db, purpose="audit_report")
        prompt = (
            f"你是质量审计助手。基于以下结构化证据，为「{template_key}」审计报告"
            f"写 3–5 句中文概述（先结论后依据；引用证据时使用 [E编号] 格式；"
            f"不要编造证据清单之外的数字）：\n" + "\n".join(summary_lines)
        )
        reply, _usage, _reasoning = chat_completion(
            db, config=config,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=400, purpose="audit_report",
        )
        if reply and reply.strip():
            return reply.strip()
    except Exception:  # noqa: BLE001 - 网关不可用回退结构化要点
        pass
    return fallback


def _render_markdown(template_key: str, evidence: list, narrative: str) -> str:
    lines = [f"# 审计报告：{template_key}", "", narrative, "", "## 证据清单", ""]
    for item in evidence:
        lines.append(
            f"- [{item['ref']}] {item['table']}#{item['record_id'] or '-'}：{item['summary']}"
        )
    return "\n".join(lines)


def ask_metrics(db: Session, *, project_id, question: str, override_registry: dict | None = None):
    """问数：只走指标注册表（SQL 模板 + 命名绑定参数，不拼接、不生成）。
    返回 status ∈ answered/clarify/denied。"""
    registry = dict(BUILTIN_METRIC_REGISTRY)
    registry.update(dict(override_registry or {}))
    question_text = (question or "").strip()
    if not question_text:
        raise AuditQAError("ASK_QUESTION_REQUIRED")
    candidates: list[str] = []
    for alias, metric_names in _METRIC_ALIASES.items():
        if alias in question_text:
            candidates.extend(metric_names)
    candidates = [name for name in candidates if name in registry]
    if not candidates:
        return {
            "status": "denied",
            "code": "METRIC_NOT_IN_REGISTRY",
            "message": "未命中指标注册表（问数只走注册表，不生成 SQL）",
            "known_metrics": sorted(registry),
        }
    if len(set(candidates)) > 1:
        return {
            "status": "clarify",
            "message": "问题指代多个指标，请明确要问哪一个",
            "candidates": sorted(set(candidates)),
        }
    metric_name = candidates[0]
    entry = registry[metric_name]
    result = db.execute(
        text(entry["sql"]),
        {"project_id": str(project_id)},
    )
    row = result.first()
    value = getattr(row, "value", None) if row is not None else None
    return {
        "status": "answered",
        "metric": metric_name,
        "value": value,
        "footnote": entry["footnote"],
    }


def registry_metrics(override_registry: dict | None = None) -> list[dict]:
    registry = dict(BUILTIN_METRIC_REGISTRY)
    registry.update(dict(override_registry or {}))
    return [
        {"name": name, "footnote": entry["footnote"], "params": entry["params"]}
        for name, entry in sorted(registry.items())
    ]
