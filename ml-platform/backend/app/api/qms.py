"""QMS endpoints (补齐路线第三批, 技术方案 §3; B3-01~B3-10)."""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.project_security import audit_service, require_project_access
from app.database import get_db
from app.services.approvals import ApprovalError
from app.models.qms import (
    QmsCase,
    QmsCaseLink,
    QmsControlPlan,
    QmsD8Report,
    QmsFmea,
    QmsIqcRecord,
    QmsKnowledgeEntry,
    QmsMsaStudy,
    QmsNcrCapa,
    QmsQualityReport,
    QmsScar,
    QmsSupplier,
)
from app.models.user import User
from app.services.audit import AuditIntent
from app.services.qms_core import (
    QmsError,
    advance_d8,
    close_d8,
    create_d8,
    create_ncr,
    draft_d8_with_llm,
    export_d8_evidence,
    link_case_object,
    open_case,
    reject_ncr,
    repush_case_status,
    search_by_symptom,
    search_cases,
    search_knowledge,
    trace_batch,
    trace_sample,
    transition_ncr,
)
from app.services.qms_tools import (
    QmsToolsError,
    archive_control_plan,
    compute_grr,
    create_or_replace_plan,
    disable_supplier,
    evaluate_tightening,
    generate_report,
    normalize_fmea_items,
    plan_version_diff,
    record_iqc,
    sync_fmea_to_control_plan,
)

router = APIRouter(prefix="/api/projects/{project_id}/qms", tags=["qms"])

# 写端点 → 审计动作映射（合同 §6-4：新增写接口纳入既有项目访问权限测试矩阵）
PROJECT_WRITE_ACTIONS = {
    "POST /api/projects/{project_id}/qms/ncr-capa": "qms.ncr.create",
    "POST /api/projects/{project_id}/qms/ncr-capa/{ncr_id}/transition": "qms.ncr.transition",
    "POST /api/projects/{project_id}/qms/ncr-capa/{ncr_id}/reject": "qms.ncr.reject",
    "POST /api/projects/{project_id}/qms/d8": "qms.d8.create",
    "POST /api/projects/{project_id}/qms/d8/{d8_id}/advance": "qms.d8.advance",
    "POST /api/projects/{project_id}/qms/d8/{d8_id}/draft-llm": "qms.d8.draft",
    "POST /api/projects/{project_id}/qms/d8/{d8_id}/close": "qms.d8.close",
    "POST /api/projects/{project_id}/qms/d8/{d8_id}/evidence": "qms.d8.evidence_export",
    "POST /api/projects/{project_id}/qms/cases": "qms.case.create",
    "POST /api/projects/{project_id}/qms/cases/{case_id}/links": "qms.case.link",
    "POST /api/projects/{project_id}/qms/cases/{case_id}/repush": "qms.case.repush",
    "POST /api/projects/{project_id}/qms/knowledge": "qms.knowledge.create",
    "POST /api/projects/{project_id}/qms/quality-reports": "qms.report.create",
    "POST /api/projects/{project_id}/qms/control-plans": "qms.plan.create",
    "POST /api/projects/{project_id}/qms/control-plans/{plan_id}/archive": "qms.plan.archive",
    "POST /api/projects/{project_id}/qms/control-plans/{plan_id}/tightening-evaluation": "qms.plan.tightening",
    "POST /api/projects/{project_id}/qms/msa-studies": "qms.msa.create",
    "POST /api/projects/{project_id}/qms/fmeas": "qms.fmea.create",
    "POST /api/projects/{project_id}/qms/fmeas/{fmea_id}/sync-control-plan": "qms.fmea.sync",
    "POST /api/projects/{project_id}/qms/scars/{scar_id}": "qms.scar.update",
    "POST /api/projects/{project_id}/qms/suppliers": "qms.supplier.create",
    "POST /api/projects/{project_id}/qms/suppliers/{supplier_id}/disable": "qms.supplier.disable",
    "POST /api/projects/{project_id}/qms/iqc-records": "qms.iqc.create",
}



class NcrCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)
    title: str = Field(max_length=256)
    source_alert_id: UUID | None = None
    scene_id: UUID | None = None
    station_id: UUID | None = None


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class D8Create(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)
    title: str = Field(max_length=256)
    case_id: UUID | None = None
    ncr_id: UUID | None = None


class D8Advance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_content: dict = Field(default_factory=dict)
    d6_passed: bool | None = None


class D8Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: str = Field(min_length=1, max_length=2000)


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)
    title: str = Field(max_length=256)
    severity: str = "medium"
    source_alert_id: UUID | None = None
    keywords: str | None = Field(default=None, max_length=256)


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_type: str
    object_id: str = Field(max_length=64)


class KnowledgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    defect_code: str = Field(max_length=64)
    symptom: str
    root_cause: str | None = None
    action: str | None = None
    effectiveness: str | None = None
    device_ref: str | None = Field(default=None, max_length=128)


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str
    period_key: str = Field(max_length=16)


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)
    quality_points: list = Field(default_factory=list)


class MsaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=128)
    part_count: int = Field(ge=1)
    operator_count: int = Field(ge=1)
    replicates: int = Field(ge=2)
    data: dict
    tolerance: float = Field(default=0.0, ge=0)


class FmeaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=128)
    items: list


class SupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)
    name: str = Field(max_length=128)


class IqcCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_id: UUID
    arrival_count: int = Field(ge=0)
    inspected_count: int = Field(ge=0)
    defect_count: int = Field(ge=0)


def _qms_error(error: QmsError) -> None:
    status = 404 if error.code.endswith("_NOT_FOUND") else 409 if any(
        key in error.code for key in ("BLOCKED", "CONFLICT", "INVALID", "ENFORCED", "DUAL", "DISABLED")
    ) else 400
    raise HTTPException(status, {"code": error.code, "message": error.message})


def _tools_error(error: QmsToolsError) -> None:
    status = 404 if error.code.endswith("_NOT_FOUND") else 409 if error.code in {
        "QMS_PLAN_DUAL_ACTIVE", "SUPPLIER_DISABLED", "IQC_COUNT_CONSTRAINT",
        "QMS_PLAN_ALREADY_ARCHIVED",
    } else 400
    raise HTTPException(status, {"code": error.code, "message": error.message})


def _manage(db: Session, project_id: UUID, current_user: User):
    return require_project_access(db, project_id, current_user.id, "quality.manage")


# ---------------- NCR（B3-04） ----------------

@router.post("/ncr-capa")
def create_ncr_endpoint(
    project_id: UUID, payload_in: NcrCreate, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.ncr.create",
                           resource_type="qms_ncr", changes={"code": payload_in.code}),
        allowed_changes={"code"},
    ):
        try:
            ncr = create_ncr(
                db, project_id=project_id, code=payload_in.code,
                title=payload_in.title,
                source_alert_id=payload_in.source_alert_id,
                scene_id=payload_in.scene_id, station_id=payload_in.station_id,
                created_by_id=current_user.id,
            )
        except QmsError as error:
            _qms_error(error)
    return {"id": str(ncr.id), "stage": ncr.stage}


@router.post("/ncr-capa/{ncr_id}/transition")
def transition_ncr_endpoint(
    project_id: UUID, ncr_id: UUID, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.ncr.transition",
                           resource_type="qms_ncr", resource_id=str(ncr_id), changes={}),
        allowed_changes=set(),
    ):
        try:
            ncr = transition_ncr(db, ncr_id=ncr_id, actor_id=current_user.id)
        except QmsError as error:
            _qms_error(error)
    db.commit()
    return {"id": str(ncr.id), "stage": ncr.stage}


@router.post("/ncr-capa/{ncr_id}/reject")
def reject_ncr_endpoint(
    project_id: UUID, ncr_id: UUID, payload_in: RejectRequest, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.ncr.reject",
                           resource_type="qms_ncr", resource_id=str(ncr_id), changes={}),
        allowed_changes=set(),
    ):
        try:
            ncr = reject_ncr(db, ncr_id=ncr_id, actor_id=current_user.id,
                             reason=payload_in.reason)
        except QmsError as error:
            _qms_error(error)
    db.commit()
    return {"id": str(ncr.id), "stage": ncr.stage}


@router.get("/ncr-capa")
def list_ncr(
    project_id: UUID, stage: str | None = Query(default=None),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    query = db.query(QmsNcrCapa).filter(QmsNcrCapa.project_id == project_id)
    if stage:
        query = query.filter(QmsNcrCapa.stage == stage)
    rows = query.order_by(QmsNcrCapa.created_at.desc()).limit(100).all()
    return {"items": [{"id": str(r.id), "code": r.code, "title": r.title,
                       "stage": r.stage,
                       "verification_cycles": r.verification_cycles} for r in rows]}


@router.get("/ncr-capa/{ncr_id}")
def get_ncr(
    project_id: UUID, ncr_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    row = db.get(QmsNcrCapa, ncr_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, {"code": "NCR_NOT_FOUND"})
    from app.models.qms import QmsNcrAction

    actions = (
        db.query(QmsNcrAction)
        .filter(QmsNcrAction.ncr_id == row.id)
        .order_by(QmsNcrAction.created_at.asc())
        .all()
    )
    return {
        "id": str(row.id), "code": row.code, "title": row.title,
        "stage": row.stage, "verification_cycles": row.verification_cycles,
        "reject_reason": row.reject_reason,
        "source_alert_id": str(row.source_alert_id) if row.source_alert_id else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "actions": [
            {"phase": item.phase, "action": item.action,
             "created_at": item.created_at.isoformat() if item.created_at else None}
            for item in actions
        ],
    }


# ---------------- 8D（B3-03） ----------------

@router.get("/d8")
def list_d8(
    project_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = (
        db.query(QmsD8Report)
        .filter(QmsD8Report.project_id == project_id)
        .order_by(QmsD8Report.created_at.desc())
        .limit(100)
        .all()
    )
    return {"items": [{"id": str(r.id), "code": r.code, "title": r.title,
                       "current_step": r.current_step, "d6_passed": r.d6_passed,
                       "closed_at": r.closed_at.isoformat() if r.closed_at else None}
                      for r in rows]}


@router.get("/d8/{d8_id}")
def get_d8(
    project_id: UUID, d8_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    row = db.get(QmsD8Report, d8_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, {"code": "D8_NOT_FOUND"})
    return {"id": str(row.id), "code": row.code, "title": row.title,
            "current_step": row.current_step, "steps": row.steps or {},
            "d6_passed": row.d6_passed,
            "ncr_id": str(row.ncr_id) if row.ncr_id else None,
            "case_id": str(row.case_id) if row.case_id else None,
            "closed_at": row.closed_at.isoformat() if row.closed_at else None}


@router.post("/d8")
def create_d8_endpoint(
    project_id: UUID, payload_in: D8Create, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.d8.create",
                           resource_type="qms_d8", changes={"code": payload_in.code}),
        allowed_changes={"code"},
    ):
        d8 = create_d8(db, project_id=project_id, code=payload_in.code,
                       title=payload_in.title, case_id=payload_in.case_id,
                       ncr_id=payload_in.ncr_id, created_by_id=current_user.id)
    return {"id": str(d8.id), "current_step": d8.current_step}


@router.post("/d8/{d8_id}/advance")
def advance_d8_endpoint(
    project_id: UUID, d8_id: UUID, payload_in: D8Advance, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.d8.advance",
                           resource_type="qms_d8", resource_id=str(d8_id), changes={}),
        allowed_changes=set(),
    ):
        try:
            d8 = advance_d8(db, d8_id=d8_id, actor_id=current_user.id,
                            step_content=payload_in.step_content,
                            d6_passed=payload_in.d6_passed)
        except QmsError as error:
            _qms_error(error)
    db.commit()
    return {"id": str(d8.id), "current_step": d8.current_step,
            "d6_passed": d8.d6_passed}


@router.post("/d8/{d8_id}/draft-llm")
def draft_d8_endpoint(
    project_id: UUID, d8_id: UUID, payload_in: D8Draft, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.d8.draft",
                           resource_type="qms_d8", resource_id=str(d8_id), changes={}),
        allowed_changes=set(),
    ):
        result = draft_d8_with_llm(db, d8_id=d8_id, context=payload_in.context,
                                   actor_id=current_user.id)
    db.commit()
    return result


@router.post("/d8/{d8_id}/close")
def close_d8_endpoint(
    project_id: UUID, d8_id: UUID, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.d8.close",
                           resource_type="qms_d8", resource_id=str(d8_id), changes={}),
        allowed_changes=set(),
    ):
        try:
            d8 = close_d8(db, d8_id=d8_id, actor_id=current_user.id)
        except QmsError as error:
            _qms_error(error)
    db.commit()
    return {"id": str(d8.id), "closed": True}


@router.post("/d8/{d8_id}/evidence")
def export_d8_evidence_endpoint(
    project_id: UUID, d8_id: UUID, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """8D 证据包导出（D3）：注册 evidence_export 工件，走既有 download 端点取回。"""
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.d8.evidence_export",
                           resource_type="qms_d8", resource_id=str(d8_id), changes={}),
        allowed_changes=set(),
    ):
        try:
            artifact = export_d8_evidence(db, d8_id=d8_id)
        except QmsError as error:
            _qms_error(error)
    db.commit()
    return {
        "artifact_id": str(artifact.id),
        "download": f"/api/projects/{project_id}/evidence-exports/{artifact.id}/download",
    }


# ---------------- 案例（B3-07） ----------------

@router.post("/cases")
def create_case_endpoint(
    project_id: UUID, payload_in: CaseCreate, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.case.create",
                           resource_type="qms_case", changes={"code": payload_in.code}),
        allowed_changes={"code"},
    ):
        case = open_case(db, project_id=project_id, code=payload_in.code,
                         title=payload_in.title, severity=payload_in.severity,
                         source_alert_id=payload_in.source_alert_id,
                         keywords=payload_in.keywords,
                         created_by_id=current_user.id)
    return {"id": str(case.id), "status": case.status}


@router.get("/cases")
def search_cases_endpoint(
    project_id: UUID, status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = search_cases(db, project_id=project_id, status=status,
                        severity=severity, keyword=keyword)
    return {"items": [{"id": str(r.id), "code": r.code, "title": r.title,
                       "severity": r.severity, "status": r.status} for r in rows]}


@router.post("/cases/{case_id}/links")
def link_case_endpoint(
    project_id: UUID, case_id: UUID, payload_in: LinkRequest, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.case.link",
                           resource_type="qms_case", resource_id=str(case_id),
                           changes={"object_type": payload_in.object_type}),
        allowed_changes={"object_type"},
    ):
        link = link_case_object(db, case_id=case_id,
                                object_type=payload_in.object_type,
                                object_id=payload_in.object_id)
    return {"id": str(link.id)}


@router.get("/cases/{case_id}")
def get_case(
    project_id: UUID, case_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    row = db.get(QmsCase, case_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, {"code": "CASE_NOT_FOUND"})
    links = (
        db.query(QmsCaseLink).filter(QmsCaseLink.case_id == row.id).all()
    )
    return {"id": str(row.id), "code": row.code, "title": row.title,
            "severity": row.severity, "status": row.status,
            "keywords": row.keywords,
            "source_alert_id": str(row.source_alert_id) if row.source_alert_id else None,
            "closed_at": row.closed_at.isoformat() if row.closed_at else None,
            "links": [{"object_type": item.object_type,
                       "object_id": item.object_id} for item in links]}


@router.post("/cases/{case_id}/repush")
def repush_case_endpoint(
    project_id: UUID, case_id: UUID, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.case.repush",
                           resource_type="qms_case", resource_id=str(case_id), changes={}),
        allowed_changes=set(),
    ):
        try:
            case = repush_case_status(db, case_id=case_id)
        except QmsError as error:
            _qms_error(error)
    db.commit()
    return {"id": str(case.id), "status": case.status}


# ---------------- 知识库（B3-10） ----------------

@router.post("/knowledge")
def create_knowledge_endpoint(
    project_id: UUID, payload_in: KnowledgeCreate, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.knowledge.create",
                           resource_type="qms_knowledge",
                           changes={"defect_code": payload_in.defect_code}),
        allowed_changes={"defect_code"},
    ):
        entry = QmsKnowledgeEntry(
            project_id=project_id, defect_code=payload_in.defect_code,
            symptom=payload_in.symptom, root_cause=payload_in.root_cause,
            action=payload_in.action, effectiveness=payload_in.effectiveness,
            device_ref=payload_in.device_ref, created_by_id=current_user.id,
        )
        db.add(entry)
        db.flush()
    return {"id": str(entry.id)}


@router.get("/knowledge")
def search_knowledge_endpoint(
    project_id: UUID, defect_code: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    device_ref: str | None = Query(default=None),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = search_knowledge(db, project_id=project_id, defect_code=defect_code,
                            keyword=keyword, device_ref=device_ref)
    return {"items": [{"id": str(r.id), "defect_code": r.defect_code,
                       "symptom": r.symptom, "root_cause": r.root_cause} for r in rows]}


@router.get("/knowledge/symptom-search")
def symptom_search_endpoint(
    project_id: UUID, symptom: str = Query(min_length=1),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    results = search_by_symptom(db, project_id=project_id, symptom=symptom)
    return {"items": [
        {"match_score": item["match_score"], "match_reason": item["match_reason"],
         "defect_code": item["entry"].defect_code, "root_cause": item["entry"].root_cause}
        for item in results
    ]}


# ---------------- 追溯（B3-09） ----------------

@router.get("/trace/{sample_key}")
def trace_endpoint(
    project_id: UUID, sample_key: str,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    return trace_sample(db, project_id=project_id, sample_key=sample_key)


@router.get("/trace-batch/{batch_no}")
def trace_batch_endpoint(
    project_id: UUID, batch_no: str,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    return trace_batch(db, project_id=project_id, batch_no=batch_no)


# ---------------- 报告（B3-08） ----------------

@router.post("/quality-reports")
def create_report_endpoint(
    project_id: UUID, payload_in: ReportCreate, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.report.create",
                           resource_type="qms_report",
                           changes={"period": payload_in.period}),
        allowed_changes={"period"},
    ):
        try:
            report = generate_report(db, project_id=project_id,
                                     period=payload_in.period,
                                     period_key=payload_in.period_key,
                                     generated_by="manual",
                                     created_by_id=current_user.id)
        except QmsToolsError as error:
            _tools_error(error)
    db.commit()
    return {"id": str(report.id), "content": report.content}


@router.get("/quality-reports")
def list_reports(
    project_id: UUID, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = (
        db.query(QmsQualityReport)
        .filter(QmsQualityReport.project_id == project_id)
        .order_by(QmsQualityReport.created_at.desc())
        .limit(50)
        .all()
    )
    return {"items": [{"id": str(r.id), "period": r.period,
                       "period_key": r.period_key,
                       "generated_by": r.generated_by,
                       "content": r.content} for r in rows]}


def _load_report(db: Session, project_id: UUID, report_id: UUID) -> QmsQualityReport:
    report = db.get(QmsQualityReport, report_id)
    if report is None or report.project_id != project_id:
        raise HTTPException(404, {"code": "QMS_REPORT_NOT_FOUND"})
    return report


@router.get("/quality-reports/{report_id}/export.html")
def export_report_html_endpoint(
    project_id: UUID, report_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    report = _load_report(db, project_id, report_id)
    filename = f"quality-report-{report.period}-{report.period_key}.html"
    return Response(
        content=report.html or "",
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/quality-reports/{report_id}/export.json")
def export_report_json_endpoint(
    project_id: UUID, report_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    report = _load_report(db, project_id, report_id)
    filename = f"quality-report-{report.period}-{report.period_key}.json"
    payload = {
        "id": str(report.id), "project_id": str(report.project_id),
        "period": report.period, "period_key": report.period_key,
        "generated_by": report.generated_by, "content": report.content,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------- 控制计划（B3-06） ----------------

@router.get("/control-plans")
def list_control_plans(
    project_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = (
        db.query(QmsControlPlan)
        .filter(QmsControlPlan.project_id == project_id)
        .order_by(QmsControlPlan.version.desc())
        .limit(50)
        .all()
    )
    return {"items": [_plan_view(r) for r in rows]}


def _plan_view(plan: QmsControlPlan) -> dict:
    """控制计划视图：质量点附**生效抽样量**（基础抽样量 × 加严乘数）——
    〔第三轮复审 2026-11-28 补乘数执行层〕乘数曾只存得进、看得见，无任何
    执行消费方（B3 口径 12「乘数生效」止步于字段写回）。sample 为空的质量
    点 effective_sample 同为 null。"""
    multiplier = float(plan.tightening_multiplier or 1.0)
    points = []
    for point in plan.quality_points or []:
        row = dict(point) if isinstance(point, dict) else {"name": str(point)}
        sample = row.get("sample")
        row["effective_sample"] = (
            round(float(sample) * multiplier, 2)
            if isinstance(sample, (int, float)) else None
        )
        points.append(row)
    return {"id": str(plan.id), "code": plan.code, "version": plan.version,
            "status": plan.status,
            "tightening_multiplier": plan.tightening_multiplier,
            "quality_points": points}


@router.post("/control-plans")
def create_plan_endpoint(
    project_id: UUID, payload_in: PlanCreate, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.plan.create",
                           resource_type="qms_control_plan",
                           changes={"code": payload_in.code}),
        allowed_changes={"code"},
    ):
        try:
            plan = create_or_replace_plan(db, project_id=project_id,
                                          code=payload_in.code,
                                          quality_points=payload_in.quality_points,
                                          created_by_id=current_user.id)
        except QmsToolsError as error:
            _tools_error(error)
    db.commit()
    return {"id": str(plan.id), "version": plan.version, "status": plan.status}


@router.post("/control-plans/{plan_id}/archive")
def archive_plan_endpoint(
    project_id: UUID, plan_id: UUID, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """归档生效计划（三批复审缺口：无归档流程则第二版永远建不出来）。"""
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.plan.archive",
                           resource_type="qms_control_plan", resource_id=str(plan_id),
                           changes={}),
        allowed_changes=set(),
    ):
        try:
            plan = archive_control_plan(db, plan_id=plan_id, actor_id=current_user.id)
        except QmsToolsError as error:
            _tools_error(error)
    db.commit()
    return {"id": str(plan.id), "status": plan.status,
            "archived_at": plan.archived_at.isoformat() if plan.archived_at else None}


@router.post("/control-plans/{plan_id}/tightening-evaluation")
def tightening_endpoint(
    project_id: UUID, plan_id: UUID, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.plan.tightening",
                           resource_type="qms_control_plan", resource_id=str(plan_id),
                           changes={}),
        allowed_changes=set(),
    ):
        plan = db.get(QmsControlPlan, plan_id)
        if plan is None:
            raise HTTPException(404, {"code": "QMS_PLAN_NOT_FOUND"})
        # 〔第三轮复审 2026-11-28〕归档计划不再评估加严（评估服务于下一步
        # 加严，归档计划无下一步）；执行器校验抛 ApprovalError 映射 409——
        # 曾无捕获直接 500。
        if plan.status != "active":
            raise HTTPException(409, {"code": "QMS_PLAN_NOT_ACTIVE"})
        try:
            decision = evaluate_tightening(db, plan=plan, actor_id=current_user.id)
        except ApprovalError as exc:
            raise HTTPException(409, {"code": str(exc)}) from exc
    db.commit()
    return decision


@router.get("/control-plans/{plan_id}/diff")
def plan_diff_endpoint(
    project_id: UUID, plan_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    try:
        return plan_version_diff(db, plan_id=plan_id)
    except QmsToolsError as error:
        _tools_error(error)


# ---------------- MSA（B3-01） ----------------

@router.get("/msa-studies")
def list_msa_studies(
    project_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = (
        db.query(QmsMsaStudy)
        .filter(QmsMsaStudy.project_id == project_id)
        .order_by(QmsMsaStudy.created_at.desc())
        .limit(50)
        .all()
    )
    return {"items": [{"id": str(r.id), "name": r.name,
                       "part_count": r.part_count, "operator_count": r.operator_count,
                       "replicates": r.replicates, "grr_percent": r.grr_percent,
                       "ndc": r.ndc, "grade": r.grade} for r in rows]}


@router.post("/msa-studies")
def create_msa_endpoint(
    project_id: UUID, payload_in: MsaCreate, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.msa.create",
                           resource_type="qms_msa", changes={"name": payload_in.name}),
        allowed_changes={"name"},
    ):
        grr = compute_grr({**payload_in.data, "tolerance": payload_in.tolerance})
        study = QmsMsaStudy(
            project_id=project_id, name=payload_in.name,
            part_count=payload_in.part_count,
            operator_count=payload_in.operator_count,
            replicates=payload_in.replicates, data=payload_in.data,
            grr_percent=grr["grr_percent"], ndc=grr["ndc"], grade=grr["grade"],
            created_by_id=current_user.id,
        )
        db.add(study)
        db.flush()
    return {"id": str(study.id), "grr_percent": study.grr_percent,
            "ndc": study.ndc, "grade": study.grade}


# ---------------- FMEA（B3-02） ----------------

@router.get("/fmeas")
def list_fmeas(
    project_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = (
        db.query(QmsFmea)
        .filter(QmsFmea.project_id == project_id)
        .order_by(QmsFmea.created_at.desc())
        .limit(50)
        .all()
    )
    return {"items": [{"id": str(r.id), "name": r.name,
                       "items": r.items or []} for r in rows]}


@router.post("/fmeas")
def create_fmea_endpoint(
    project_id: UUID, payload_in: FmeaCreate, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.fmea.create",
                           resource_type="qms_fmea", changes={"name": payload_in.name}),
        allowed_changes={"name"},
    ):
        fmea = QmsFmea(project_id=project_id, name=payload_in.name,
                       items=normalize_fmea_items(payload_in.items),
                       created_by_id=current_user.id)
        db.add(fmea)
        db.flush()
    return {"id": str(fmea.id), "items": fmea.items}


@router.post("/fmeas/{fmea_id}/sync-control-plan")
def sync_fmea_endpoint(
    request: Request,
    project_id: UUID, fmea_id: UUID, plan_id: UUID = Query(...),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.fmea.sync",
                           resource_type="qms_fmea", resource_id=str(fmea_id), changes={}),
        allowed_changes=set(),
    ):
        result = sync_fmea_to_control_plan(db, fmea_id=fmea_id, plan_id=plan_id,
                                           actor_id=current_user.id)
    db.commit()
    return result


# ---------------- IQC → SCAR（B3-05） ----------------

@router.get("/suppliers")
def list_suppliers(
    project_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = (
        db.query(QmsSupplier)
        .filter(QmsSupplier.project_id == project_id)
        .order_by(QmsSupplier.created_at.desc())
        .limit(100)
        .all()
    )
    return {"items": [{"id": str(r.id), "code": r.code, "name": r.name,
                       "status": r.status} for r in rows]}


@router.get("/iqc-records")
def list_iqc_records(
    project_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = (
        db.query(QmsIqcRecord)
        .filter(QmsIqcRecord.project_id == project_id)
        .order_by(QmsIqcRecord.created_at.desc())
        .limit(100)
        .all()
    )
    return {"items": [{"id": str(r.id), "supplier_id": str(r.supplier_id),
                       "arrival_count": r.arrival_count,
                       "inspected_count": r.inspected_count,
                       "defect_count": r.defect_count,
                       "scar_id": str(r.scar_id) if r.scar_id else None} for r in rows]}


@router.get("/scars")
def list_scars(
    project_id: UUID,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = (
        db.query(QmsScar)
        .filter(QmsScar.project_id == project_id)
        .order_by(QmsScar.created_at.desc())
        .limit(100)
        .all()
    )
    return {"items": [{"id": str(r.id), "iqc_record_id": str(r.iqc_record_id),
                       "cause": r.cause,
                       "closed_at": r.closed_at.isoformat() if r.closed_at else None}
                      for r in rows]}


class ScarUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cause: str | None = Field(default=None, max_length=2000)
    correction: str | None = Field(default=None, max_length=2000)
    verification: str | None = Field(default=None, max_length=2000)
    close: bool = False


@router.post("/scars/{scar_id}")
def update_scar_endpoint(
    project_id: UUID, scar_id: UUID, payload_in: ScarUpdate, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """SCAR 整改登记与关闭（三批复审缺口：SCAR 曾只能自动生成、无法处理）。"""
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.scar.update",
                           resource_type="qms_scar", resource_id=str(scar_id),
                           changes={"close": payload_in.close}),
        allowed_changes={"close"},
    ):
        scar = db.get(QmsScar, scar_id)
        if scar is None or str(scar.project_id) != str(project_id):
            raise HTTPException(404, {"code": "QMS_SCAR_NOT_FOUND"})
        if payload_in.cause is not None:
            scar.cause = payload_in.cause
        if payload_in.correction is not None:
            scar.correction = payload_in.correction
        if payload_in.verification is not None:
            scar.verification = payload_in.verification
        if payload_in.close:
            if scar.closed_at is not None:
                raise HTTPException(409, {"code": "QMS_SCAR_ALREADY_CLOSED"})
            if not (scar.correction and scar.verification):
                raise HTTPException(409, {
                    "code": "QMS_SCAR_CLOSE_INCOMPLETE",
                    "message": "关闭前须登记纠正措施（correction）与验证（verification）",
                })
            scar.closed_at = func.now()
        db.flush()
    db.commit()
    return {"id": str(scar.id), "cause": scar.cause,
            "correction": scar.correction, "verification": scar.verification,
            "closed_at": scar.closed_at.isoformat() if scar.closed_at else None}


@router.post("/suppliers")
def create_supplier_endpoint(
    project_id: UUID, payload_in: SupplierCreate, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.supplier.create",
                           resource_type="qms_supplier",
                           changes={"code": payload_in.code}),
        allowed_changes={"code"},
    ):
        supplier = QmsSupplier(project_id=project_id, code=payload_in.code,
                               name=payload_in.name, created_by_id=current_user.id)
        db.add(supplier)
        db.flush()
    return {"id": str(supplier.id), "status": supplier.status}


@router.post("/suppliers/{supplier_id}/disable")
def disable_supplier_endpoint(
    project_id: UUID, supplier_id: UUID, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.supplier.disable",
                           resource_type="qms_supplier", resource_id=str(supplier_id),
                           changes={}),
        allowed_changes=set(),
    ):
        try:
            supplier = disable_supplier(db, supplier_id=supplier_id,
                                        actor_id=current_user.id)
        except QmsToolsError as error:
            _tools_error(error)
    db.commit()
    return {"id": str(supplier.id), "status": supplier.status}


@router.post("/iqc-records")
def create_iqc_endpoint(
    project_id: UUID, payload_in: IqcCreate, request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    access = _manage(db, project_id, current_user)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(project_id=project_id, action="qms.iqc.create",
                           resource_type="qms_iqc",
                           changes={"arrival": payload_in.arrival_count}),
        allowed_changes={"arrival"},
    ):
        try:
            record = record_iqc(
                db, project_id=project_id, supplier_id=payload_in.supplier_id,
                arrival_count=payload_in.arrival_count,
                inspected_count=payload_in.inspected_count,
                defect_count=payload_in.defect_count,
                created_by_id=current_user.id,
            )
        except QmsToolsError as error:
            _tools_error(error)
    db.commit()
    return {"id": str(record.id), "scar_id": str(record.scar_id) if record.scar_id else None}
