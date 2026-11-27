"""QMS core services (补齐路线第三批 T1, B3-03/04/07/09/10).

NCR 五阶段+三周期无复发门禁；8D 顺序推进+D6 门禁+LLM 草稿（自动入动作
审计）；案例自动/手工开案与状态重推；知识库筛选与症状检索（向量挂点
登记）；批次追溯四对象串联。领域口径标注待质量专家评审。
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.qms import (
    QmsCase,
    QmsCaseLink,
    QmsD8Report,
    QmsKnowledgeEntry,
    QmsNcrAction,
    QmsNcrCapa,
    QmsTraceLink,
)

NCR_FLOW = {
    "draft": {"analysis"},
    "analysis": {"action"},
    "action": {"verification"},
    "verification": {"closed"},
    "closed": set(),
    "rejected": set(),
}
VERIFICATION_CYCLE_DAYS = 7
REQUIRED_VERIFICATION_CYCLES = 3
D8_TOTAL_STEPS = 9  # D0..D8


class QmsError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _now() -> datetime:
    return datetime.utcnow()


# ---------------- NCR / CAPA（B3-04） ----------------

def create_ncr(db: Session, *, project_id, code: str, title: str,
               source_alert_id=None, scene_id=None, station_id=None,
               created_by_id=None) -> QmsNcrCapa:
    ncr = QmsNcrCapa(
        project_id=project_id, code=code, title=title,
        source_alert_id=source_alert_id, scene_id=scene_id,
        station_id=station_id, created_by_id=created_by_id,
    )
    db.add(ncr)
    db.flush()
    db.add(QmsNcrAction(ncr_id=ncr.id, phase="draft", action="登记不合格",
                        actor_id=created_by_id))
    db.flush()
    return ncr


def transition_ncr(db: Session, *, ncr_id, actor_id, note: str | None = None) -> QmsNcrCapa:
    ncr = db.get(QmsNcrCapa, ncr_id)
    if ncr is None:
        raise QmsError("NCR_NOT_FOUND")
    allowed = NCR_FLOW.get(ncr.stage, set())
    if not allowed:
        raise QmsError("NCR_STATE_FINAL")
    target = sorted(allowed)[0]
    if target == "closed":
        # 关闭门禁在 close_ncr 内（三周期无复发）；由它置 closed
        close_ncr(db, ncr=ncr, actor_id=actor_id, note=note)
        return ncr
    ncr.stage = target
    db.add(QmsNcrAction(ncr_id=ncr.id, phase=target, action=f"推进到 {target}",
                        actor_id=actor_id))
    db.flush()
    return ncr


def reject_ncr(db: Session, *, ncr_id, actor_id, reason: str) -> QmsNcrCapa:
    """早期驳回（draft/analysis 阶段；理由必填）。"""
    ncr = db.get(QmsNcrCapa, ncr_id)
    if ncr is None:
        raise QmsError("NCR_NOT_FOUND")
    if ncr.stage not in {"draft", "analysis"}:
        raise QmsError("NCR_REJECT_STAGE_INVALID")
    if not (reason or "").strip():
        raise QmsError("NCR_REJECT_REASON_REQUIRED")
    ncr.stage = "rejected"
    ncr.reject_reason = reason.strip()
    db.add(QmsNcrAction(ncr_id=ncr.id, phase="rejected", action=f"驳回：{reason[:80]}",
                        actor_id=actor_id))
    db.flush()
    return ncr


def verification_started_at(db: Session, *, ncr: QmsNcrCapa) -> datetime | None:
    """进入 verification 的时刻：轨迹里第一条 verification 行的 created_at。"""
    row = (
        db.query(QmsNcrAction)
        .filter(QmsNcrAction.ncr_id == ncr.id, QmsNcrAction.phase == "verification")
        .order_by(QmsNcrAction.created_at.asc())
        .first()
    )
    return row.created_at if row is not None else None


def evaluate_recurrence(db: Session, *, ncr: QmsNcrCapa,
                        since: datetime | None = None) -> bool:
    """复发判定：`since`（默认=进入 verification 之后）同场景+同工位有新预警。

    三批复审更正：原实现回看「近 7 天」且不含 verification 起点约束——进入
    verification 之前的旧预警也会被判成复发；现以验证期起点为窗口起点。
    """
    from app.models.quality_alerts import QualityAlert

    start = since or verification_started_at(db, ncr=ncr) or _now()
    query = db.query(QualityAlert).filter(
        QualityAlert.project_id == ncr.project_id,
        QualityAlert.created_at > start,
    )
    if ncr.scene_id is not None:
        query = query.filter(QualityAlert.scene_id == ncr.scene_id)
    if ncr.station_id is not None:
        query = query.filter(QualityAlert.station_id == ncr.station_id)
    return bool(query.first())


def close_ncr(db: Session, *, ncr: QmsNcrCapa, actor_id, note: str | None = None,
              now: datetime | None = None) -> QmsNcrCapa:
    """关闭门禁（三批复审重构）：**时间窗判定**。

    进入 verification 后须连续三个验证周期（每周期 7 天，共 21 天）同场景+
    同工位无新预警方可关闭。判定是只读的——旧实现「调用一次计数 +1，不满
    3 次抛错」在 HTTP 路径上会被 project_action 的回滚撤销（计数恒 0，永远
    关不掉，三批复审 P0-1 运行验证坐实）；时间窗判定天然免疫该问题，且
    「点三次」无法再绕过时间要求。
    """
    if ncr.stage != "verification":
        raise QmsError("NCR_CLOSE_STAGE_INVALID")
    started = verification_started_at(db, ncr=ncr)
    if started is None:
        # 理论不可达：stage=verification 必经 transition 写入轨迹；防御保留
        raise QmsError("NCR_CLOSE_STAGE_INVALID")
    reference = now or _now()
    if evaluate_recurrence(db, ncr=ncr, since=started):
        db.add(QmsNcrAction(ncr_id=ncr.id, phase="verification",
                            action="验证期检出复发，重新计数", actor_id=actor_id))
        # 复发即重置验证起点：把本条轨迹时间作为新起点不可行（新预警可能早于
        # 此刻）——直接拒绝，由处置流程解决预警后重新进入 verification
        db.flush()
        raise QmsError("NCR_CLOSE_BLOCKED")
    elapsed_days = (reference - started).total_seconds() / 86400.0
    required = REQUIRED_VERIFICATION_CYCLES * VERIFICATION_CYCLE_DAYS
    if elapsed_days < required:
        remaining = round(required - elapsed_days, 1)
        db.add(QmsNcrAction(ncr_id=ncr.id, phase="verification",
                            action=f"验证期 {elapsed_days:.1f}/{required} 天，尚需 {remaining} 天",
                            actor_id=actor_id))
        db.flush()
        raise QmsError("NCR_CLOSE_BLOCKED")
    ncr.stage = "closed"
    ncr.closed_at = reference
    ncr.verification_cycles = REQUIRED_VERIFICATION_CYCLES
    db.add(QmsNcrAction(ncr_id=ncr.id, phase="closed",
                        action=f"验证期 {required} 天无复发，关闭", actor_id=actor_id))
    db.flush()
    return ncr


# ---------------- 8D（B3-03） ----------------

def create_d8(db: Session, *, project_id, code: str, title: str,
              case_id=None, ncr_id=None, created_by_id=None) -> QmsD8Report:
    d8 = QmsD8Report(project_id=project_id, code=code, title=title,
                     case_id=case_id, ncr_id=ncr_id, created_by_id=created_by_id)
    db.add(d8)
    db.flush()
    return d8


def advance_d8(db: Session, *, d8_id, actor_id, step_content: dict | None = None,
               d6_passed: bool | None = None) -> QmsD8Report:
    """D0–D8 顺序推进（跳步被拒）；D6 步允许登记验证结论。"""
    d8 = db.get(QmsD8Report, d8_id)
    if d8 is None:
        raise QmsError("D8_NOT_FOUND")
    if d8.closed_at is not None:
        raise QmsError("D8_STATE_FINAL")
    if d8.current_step >= D8_TOTAL_STEPS:
        raise QmsError("D8_ALREADY_AT_END")
    steps = dict(d8.steps or {})
    steps[str(d8.current_step)] = {
        "content": step_content or {},
        "confirmed_at": _now().isoformat(),
        "actor_id": str(actor_id) if actor_id else None,
    }
    if d6_passed is not None:
        # D6 验证结论登记（验证结论以登记为准；步号推进独立）
        d8.d6_passed = bool(d6_passed)
    d8.current_step += 1
    d8.steps = steps
    db.flush()
    return d8


def close_d8(db: Session, *, d8_id, actor_id) -> QmsD8Report:
    """结案门禁：D6（永久对策验证）未通过不得结案。"""
    d8 = db.get(QmsD8Report, d8_id)
    if d8 is None:
        raise QmsError("D8_NOT_FOUND")
    if d8.closed_at is not None:
        raise QmsError("D8_STATE_FINAL")
    if d8.current_step < D8_TOTAL_STEPS:
        raise QmsError("D8_STEP_ORDER_ENFORCED")
    if not d8.d6_passed:
        raise QmsError("D6_GATE_NOT_PASSED")
    d8.closed_at = _now()
    db.flush()
    return d8


def draft_d8_with_llm(db: Session, *, d8_id, context: str) -> dict:
    """LLM 起草 D1–D5 初稿（经网关——自动入 B2-08 动作审计）；失败回退骨架。"""
    d8 = db.get(QmsD8Report, d8_id)
    if d8 is None:
        raise QmsError("D8_NOT_FOUND")
    try:
        from app.services.llm_gateway import chat_completion, resolve_profile

        config = resolve_profile(db, purpose="d8_draft")
        reply, _usage, _reasoning = chat_completion(
            db, config=config,
            messages=[{"role": "user", "content":
                       f"为 8D 报告《{d8.title}》起草 D1–D5 每步 1-2 句中文初稿。背景：{context[:800]}"}],
            temperature=0.3, max_tokens=600, purpose="d8_draft",
        )
        if reply and reply.strip():
            steps = dict(d8.steps or {})
            for step in range(1, 6):
                steps.setdefault(str(step), {"content": {"draft": reply.strip()[:400]},
                                             "drafted": True})
            d8.steps = steps
            db.flush()
            return {"drafted": True, "via": "llm"}
    except Exception:  # noqa: BLE001 - 网关不可用回退骨架
        pass
    steps = dict(d8.steps or {})
    for step in range(1, 6):
        steps.setdefault(str(step), {"content": {"draft": "（草稿待补）"}, "drafted": False})
    d8.steps = steps
    db.flush()
    return {"drafted": True, "via": "fallback"}


def _alert_payload(db: Session, alert_id) -> dict:
    from app.models.quality_alerts import QualityAlert

    row = db.get(QualityAlert, alert_id)
    if row is None:
        return {}
    return {
        "id": str(row.id), "title": row.title, "severity": row.severity,
        "source_type": row.source_type, "status": row.status,
        "sample_key": row.sample_key, "batch_no": row.batch_no,
        "evidence": row.evidence or {},
    }


def export_d8_evidence(db: Session, *, d8_id, storage=None):
    """8D 证据包导出（D3，接 B1-12 zip 先例）：报告全量 + NCR 轨迹 + 关联案例
    与来源预警证据，打包注册为平台工件（type=evidence_export），经既有
    /evidence-exports/{id}/download 端点取回；调用方负责 commit。"""
    import json
    import tempfile
    import zipfile
    from pathlib import Path

    from app.services.artifact_service import ArtifactService, build_artifact_service

    d8 = db.get(QmsD8Report, d8_id)
    if d8 is None:
        raise QmsError("D8_NOT_FOUND")
    payload = {
        "exported_at": _now().isoformat(),
        "note": "IATF 16949 8D 口径待质量专家评审",
        "d8_report": {
            "id": str(d8.id), "code": d8.code, "title": d8.title,
            "current_step": d8.current_step, "steps": d8.steps or {},
            "d6_passed": bool(d8.d6_passed),
            "closed_at": d8.closed_at.isoformat() if d8.closed_at else None,
        },
    }
    if d8.ncr_id is not None:
        ncr = db.get(QmsNcrCapa, d8.ncr_id)
        if ncr is not None:
            actions = (
                db.query(QmsNcrAction)
                .filter(QmsNcrAction.ncr_id == ncr.id)
                .order_by(QmsNcrAction.created_at.asc())
                .all()
            )
            payload["ncr"] = {
                "id": str(ncr.id), "code": ncr.code, "title": ncr.title,
                "stage": ncr.stage, "verification_cycles": ncr.verification_cycles,
                "actions": [
                    {"phase": item.phase, "action": item.action,
                     "created_at": item.created_at.isoformat() if item.created_at else None}
                    for item in actions
                ],
            }
            if ncr.source_alert_id is not None:
                payload["source_alert"] = _alert_payload(db, ncr.source_alert_id)
    if d8.case_id is not None:
        case = db.get(QmsCase, d8.case_id)
        if case is not None:
            payload["case"] = {
                "id": str(case.id), "code": case.code, "title": case.title,
                "severity": case.severity, "status": case.status,
                "links": [
                    {"object_type": link.object_type, "object_id": link.object_id}
                    for link in db.query(QmsCaseLink)
                    .filter(QmsCaseLink.case_id == case.id).all()
                ],
            }
            if case.source_alert_id is not None and "source_alert" not in payload:
                payload["source_alert"] = _alert_payload(db, case.source_alert_id)
    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        payload_path = root / "d8_evidence.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        digest = hashlib.sha256(payload_path.read_bytes()).hexdigest()
        manifest = root / "MANIFEST.SHA256"
        manifest.write_text(f"{digest}  d8_evidence.json\n", encoding="utf-8")
        zip_path = root / "d8-evidence.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(payload_path, arcname="d8_evidence.json")
            archive.write(manifest, arcname="MANIFEST.SHA256")
        stamp = _now().strftime("%Y%m%d-%H%M%S")
        service = ArtifactService(db, storage) if storage is not None else build_artifact_service(db)
        return service.create_from_file(
            d8.project_id, zip_path, f"d8-evidence-{d8.code}-{stamp}.zip",
            "evidence_export",
            metadata={
                "source": "generated", "kind": "evidence_export",
                "scope": "d8_report", "target_id": str(d8.id), "file_count": 1,
            },
            commit=False,
        )


# ---------------- 案例中心（B3-07） ----------------

def open_case(db: Session, *, project_id, code: str, title: str,
              severity: str = "medium", source_alert_id=None,
              keywords: str | None = None, created_by_id=None) -> QmsCase:
    case = QmsCase(project_id=project_id, code=code, title=title,
                   severity=severity, source_alert_id=source_alert_id,
                   keywords=keywords, created_by_id=created_by_id)
    db.add(case)
    db.flush()
    if source_alert_id is not None:
        db.add(QmsCaseLink(case_id=case.id, object_type="quality_alert",
                           object_id=str(source_alert_id)))
        db.flush()
    return case


def search_cases(db: Session, *, project_id, status: str | None = None,
                 severity: str | None = None, keyword: str | None = None):
    query = db.query(QmsCase).filter(QmsCase.project_id == project_id)
    if status:
        query = query.filter(QmsCase.status == status)
    if severity:
        query = query.filter(QmsCase.severity == severity)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            QmsCase.title.like(like) | QmsCase.keywords.like(like)  # noqa: - like on controlled input via ORM param binding
        )
    return query.order_by(QmsCase.created_at.desc()).limit(100).all()


def link_case_object(db: Session, *, case_id, object_type: str, object_id: str) -> QmsCaseLink:
    link = QmsCaseLink(case_id=case_id, object_type=object_type, object_id=object_id)
    db.add(link)
    db.flush()
    return link


def repush_case_status(db: Session, *, case_id) -> QmsCase:
    """状态重推：关联 NCR 全部关闭且无未决 8D → 案例关闭候选（closed）。"""
    case = db.get(QmsCase, case_id)
    if case is None:
        raise QmsError("CASE_NOT_FOUND")
    links = db.query(QmsCaseLink).filter(QmsCaseLink.case_id == case_id).all()
    ncr_ids = [link.object_id for link in links if link.object_type == "ncr_capa"]
    d8_ids = [link.object_id for link in links if link.object_type == "d8_report"]
    open_ncr = 0
    for ncr_id in ncr_ids:
        row = db.get(QmsNcrCapa, uuid.UUID(ncr_id)) if ncr_id else None
        if row is not None and row.stage not in {"closed", "rejected"}:
            open_ncr += 1
    open_d8 = 0
    for d8_id in d8_ids:
        row = db.get(QmsD8Report, uuid.UUID(d8_id)) if d8_id else None
        if row is not None and row.closed_at is None:
            open_d8 += 1
    if open_ncr == 0 and open_d8 == 0:
        case.status = "closed"
        case.closed_at = _now()
    else:
        case.status = "monitoring"
    db.flush()
    return case


# ---------------- 知识库（B3-10） ----------------

def search_knowledge(db: Session, *, project_id, defect_code: str | None = None,
                     keyword: str | None = None, device_ref: str | None = None):
    query = db.query(QmsKnowledgeEntry).filter(QmsKnowledgeEntry.project_id == project_id)
    if defect_code:
        query = query.filter(QmsKnowledgeEntry.defect_code == defect_code)
    if device_ref:
        query = query.filter(QmsKnowledgeEntry.device_ref == device_ref)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            QmsKnowledgeEntry.symptom.like(like)
            | QmsKnowledgeEntry.root_cause.like(like)
        )
    return query.order_by(QmsKnowledgeEntry.updated_at.desc()).limit(50).all()


def search_by_symptom(db: Session, *, project_id, symptom: str, top: int = 5):
    """症状查询 Top5 相似（本批关键词相关度实现；向量检索挂 RAG 基建——挂点登记）。"""
    keywords = [token for token in symptom.replace("，", " ").replace("。", " ").split() if token]
    entries = db.query(QmsKnowledgeEntry).filter(
        QmsKnowledgeEntry.project_id == project_id
    ).all()
    scored = []
    for entry in entries:
        text = " ".join(filter(None, [entry.symptom, entry.root_cause, entry.defect_code]))
        score = sum(1 for token in keywords if token and token in text)
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda pair: -pair[0])
    return [
        {"entry": entry, "match_score": score, "match_reason": f"命中 {score} 个症状关键词"}
        for score, entry in scored[:top]
    ]


# ---------------- 批次追溯（B3-09） ----------------

def trace_sample(db: Session, *, project_id, sample_key: str) -> dict:
    """单样本四对象串联：原始数据（数据集版本）→ 模型判定（推理明细）→
    预警 → NCR。"""
    from app.models.inference_result import InferenceResult
    from app.models.quality_alerts import QualityAlert

    links = (
        db.query(QmsTraceLink)
        .filter(QmsTraceLink.project_id == project_id,
                QmsTraceLink.sample_key == sample_key)
        .all()
    )
    inference_rows = (
        db.query(InferenceResult)
        .filter(InferenceResult.project_id == project_id,
                InferenceResult.sample_key == sample_key)
        .limit(10)
        .all()
    )
    alerts = (
        db.query(QualityAlert)
        .filter(QualityAlert.project_id == project_id,
                QualityAlert.sample_key == sample_key)
        .limit(10)
        .all()
    )
    return {
        "sample_key": sample_key,
        "trace_links": [
            {"dataset_version_id": str(link.dataset_version_id) if link.dataset_version_id else None,
             "batch_no": link.batch_no}
            for link in links
        ],
        "inference_results": [
            {"id": str(row.id), "predicted_label": row.predicted_label,
             "channel": row.channel,
             "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None}
            for row in inference_rows
        ],
        "alerts": [
            {"id": str(row.id), "title": row.title, "severity": row.severity,
             "status": row.status}
            for row in alerts
        ],
        "ncr_ids": [str(link.ncr_id) for link in links if link.ncr_id],
    }


def trace_batch(db: Session, *, project_id, batch_no: str) -> dict:
    """批次概览（D6）：按批次键聚合样本键 / 推理明细 / 预警 / NCR / 数据集版本。"""
    from app.models.inference_result import InferenceResult
    from app.models.quality_alerts import QualityAlert

    links = (
        db.query(QmsTraceLink)
        .filter(QmsTraceLink.project_id == project_id,
                QmsTraceLink.batch_no == batch_no)
        .all()
    )
    sample_keys = sorted({link.sample_key for link in links if link.sample_key})
    inference_rows = (
        db.query(InferenceResult)
        .filter(InferenceResult.project_id == project_id,
                InferenceResult.batch_no == batch_no)
        .limit(20)
        .all()
    )
    alerts = (
        db.query(QualityAlert)
        .filter(QualityAlert.project_id == project_id,
                QualityAlert.batch_no == batch_no)
        .limit(20)
        .all()
    )
    return {
        "batch_no": batch_no,
        "sample_count": len(sample_keys),
        "sample_keys": sample_keys[:20],
        "dataset_version_ids": sorted(
            {str(link.dataset_version_id) for link in links if link.dataset_version_id}
        ),
        "inference_results": [
            {"id": str(row.id), "predicted_label": row.predicted_label,
             "sample_key": row.sample_key, "channel": row.channel}
            for row in inference_rows
        ],
        "alerts": [
            {"id": str(row.id), "title": row.title, "severity": row.severity,
             "status": row.status}
            for row in alerts
        ],
        "ncr_ids": sorted(
            {str(link.ncr_id) for link in links if link.ncr_id}
        ),
    }
