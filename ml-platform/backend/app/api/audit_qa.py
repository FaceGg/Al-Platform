"""S4 endpoints: audit QA + ask-data + trust/CBPE/card/explain (B2-01/B2-04)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.project_security import audit_service, require_project_access
from app.database import get_db
from app.models.audit_qa import AuditReport, ModelTrustScore
from app.models.model_registry import InferenceDeployment, ModelVersion
from app.models.user import User
from app.services.audit import AuditIntent
from app.services.audit_qa import (
    AuditQAError,
    ask_metrics,
    build_report,
    registry_metrics,
)
from app.services.model_trust import (
    TrustError,
    build_card_sections,
    compute_trust_score,
    data_fingerprint_of_version,
    estimate_cbpe,
    explain_sample,
)

router = APIRouter(tags=["audit-qa"])


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_key: str
    params: dict = Field(default_factory=dict)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=500)


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: dict
    deployment_id: UUID | None = None


def _version_or_404(db: Session, project_id: UUID, version_id: UUID) -> ModelVersion:
    """版本存在**且归属本项目**（经部署关联）方可操作。

    〔第三轮复审 2026-11-28〕曾不校验归属——对路径 pid 持有权限即可对任意
    version_id 读取指标/打可信度、甚至把他项目模型卡打回 pending（跨项目
    IDOR，#36 同族）。ModelLibrary 是 owner 级无 project_id，版本归属项目的
    唯一桥梁是 InferenceDeployment。"""
    version = db.get(ModelVersion, version_id)
    if version is None:
        raise HTTPException(404, {"code": "MODEL_VERSION_NOT_FOUND"})
    deployed = (
        db.query(InferenceDeployment.id)
        .filter(InferenceDeployment.project_id == project_id,
                InferenceDeployment.model_version_id == version_id)
        .first()
    )
    if deployed is None:
        raise HTTPException(404, {"code": "MODEL_VERSION_NOT_FOUND"})
    return version


@router.post("/api/projects/{project_id}/audit-reports")
def create_audit_report(
    project_id: UUID,
    payload_in: ReportRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """审计报告（B2-01 十类模板）：结构化证据+全局唯一引用编号+生成后校验。"""
    access = require_project_access(db, project_id, current_user.id, "audit.read")
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="audit.read",
        intent=AuditIntent(
            project_id=project_id, action="audit_report.create",
            resource_type="audit_report",
            changes={"template": payload_in.template_key},
        ),
        allowed_changes={"template"},
    ):
        try:
            report = build_report(
                db, project_id=project_id, template_key=payload_in.template_key,
                params=payload_in.params, created_by_id=current_user.id,
            )
        except AuditQAError as error:
            raise HTTPException(400, {"code": error.code, "message": error.message}) from None
    db.commit()
    return _report_view(report)


def _report_view(report: AuditReport) -> dict:
    return {
        "id": str(report.id),
        "template_key": report.template_key,
        "status": report.status,
        "content_markdown": report.content_markdown,
        "evidence": report.evidence,
        "citation_errors": report.citation_errors,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/api/projects/{project_id}/audit-reports")
def list_audit_reports(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """历史报告可重开（行永存可查）。"""
    require_project_access(db, project_id, current_user.id, "audit.read")
    rows = (
        db.query(AuditReport)
        .filter(AuditReport.project_id == project_id)
        .order_by(AuditReport.created_at.desc())
        .limit(50)
        .all()
    )
    return {"items": [_report_view(row) for row in rows]}


@router.get("/api/projects/{project_id}/audit-reports/{report_id}")
def get_audit_report(
    project_id: UUID,
    report_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """报告详情可重开（行永存可查；〔第三轮复审 2026-11-28〕补齐——此前详情
    端点缺失，历史报告只能整列表取回）。"""
    require_project_access(db, project_id, current_user.id, "audit.read")
    report = (
        db.query(AuditReport)
        .filter(AuditReport.project_id == project_id, AuditReport.id == report_id)
        .first()
    )
    if report is None:
        raise HTTPException(404, {"code": "AUDIT_REPORT_NOT_FOUND"})
    return _report_view(report)


@router.get("/api/projects/{project_id}/audit-reports/{report_id}/export.md")
def export_audit_report(
    project_id: UUID,
    report_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """markdown 导出（附件下载；接 B3 报告导出先例）。"""
    require_project_access(db, project_id, current_user.id, "audit.read")
    report = (
        db.query(AuditReport)
        .filter(AuditReport.project_id == project_id, AuditReport.id == report_id)
        .first()
    )
    if report is None:
        raise HTTPException(404, {"code": "AUDIT_REPORT_NOT_FOUND"})
    from fastapi import Response

    filename = f"audit-report-{report.template_key}-{report.id}.md"
    return Response(
        content=report.content_markdown or "",
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/projects/{project_id}/ask-metrics")
def ask_metrics_endpoint(
    project_id: UUID,
    payload_in: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """自然语言问数（只走指标注册表；LLM 不生成 SQL）。

    〔第三轮复审 2026-11-28 接线〕PlatformOption `qa.metric_registry` 的项目
    自定义指标曾不生效（override_registry 无入口）——现随请求并入；结构不
    合法（非 dict）时忽略，内置注册表兜底。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    from app.models.platform_option import get_option

    option_registry = get_option(db, "qa.metric_registry") or {}
    if not isinstance(option_registry, dict):
        option_registry = {}
    try:
        result = ask_metrics(
            db, project_id=project_id, question=payload_in.question,
            override_registry=option_registry,
        )
    except AuditQAError as error:
        raise HTTPException(400, {"code": error.code, "message": error.message}) from None
    db.commit()
    return result


@router.get("/api/projects/{project_id}/metric-registry")
def list_metric_registry(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    from app.models.platform_option import get_option

    option_registry = get_option(db, "qa.metric_registry") or {}
    if not isinstance(option_registry, dict):
        option_registry = {}
    items = registry_metrics()
    known = {row.get("name") for row in items}
    for name, spec in option_registry.items():
        if not isinstance(spec, dict) or not spec.get("sql"):
            continue
        items.append({
            "name": str(name),
            "footnote": str(spec.get("footnote") or ""),
            "source": "option",
        })
    return {"items": items, "custom_names": [
        str(name) for name in option_registry if name not in known]}



@router.get("/api/projects/{project_id}/model-versions/{version_id}/trust-score")
def compute_trust_score_endpoint(
    project_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """七因子可信度评分 + A–D 档（落历史）。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    version = _version_or_404(db, project_id, version_id)
    row = compute_trust_score(
        db, project_id=project_id, version=version, computed_by_id=current_user.id
    )
    db.commit()
    return {
        "score": row.score,
        "grade": row.grade,
        "factors": row.factors,
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
    }


@router.get("/api/projects/{project_id}/model-versions/{version_id}/trust-scores")
def list_trust_scores(
    project_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    _version_or_404(db, project_id, version_id)
    rows = (
        db.query(ModelTrustScore)
        .filter(ModelTrustScore.model_version_id == version_id)
        .order_by(ModelTrustScore.computed_at.desc())
        .limit(50)
        .all()
    )
    return {
        "items": [
            {"score": row.score, "grade": row.grade,
             "computed_at": row.computed_at.isoformat() if row.computed_at else None}
            for row in rows
        ]
    }


@router.get("/api/projects/{project_id}/model-versions/{version_id}/cbpe-estimate")
def cbpe_estimate_endpoint(
    project_id: UUID,
    version_id: UUID,
    deployment_id: UUID = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CBPE（估计口径 + 强制脚注）。

    〔第三轮复审 2026-11-28 修复〕路径 version_id 曾被完全忽略、deployment_id
    传入时不校验归属——跨项目部署可被估 CBPE。现统一校验：版本须归属本项目；
    deployment_id 缺省取本项目部署该版本的部署，显式传入时校验归属与版本一致。
    """
    require_project_access(db, project_id, current_user.id, "project.read")
    _version_or_404(db, project_id, version_id)
    if deployment_id is None:
        deployment = (
            db.query(InferenceDeployment)
            .filter(InferenceDeployment.project_id == project_id,
                    InferenceDeployment.model_version_id == version_id)
            .first()
        )
    else:
        deployment = db.get(InferenceDeployment, deployment_id)
        if (
            deployment is not None
            and (deployment.project_id != project_id
                 or deployment.model_version_id != version_id)
        ):
            raise HTTPException(404, {"code": "DEPLOYMENT_NOT_FOUND"})
    if deployment is None:
        raise HTTPException(404, {"code": "DEPLOYMENT_NOT_FOUND"})
    return estimate_cbpe(db, deployment=deployment)


@router.post("/api/projects/{project_id}/model-versions/{version_id}/model-card/refresh")
def refresh_model_card(
    project_id: UUID,
    version_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """模型卡 11 章节重建（C6 骨架扩展）；数据指纹变化 → 审批回 pending（重签）。"""
    access = require_project_access(db, project_id, current_user.id, "model.approve")
    version = _version_or_404(db, project_id, version_id)
    from app.services.model_cards import ModelCardService

    sections = build_card_sections(db, version=version)
    fingerprint = data_fingerprint_of_version(version)
    card = ModelCardService().ensure_for_version(db, version)
    previous = dict(getattr(card, "sections_v2", None) or {})
    previous_fingerprint = (getattr(card, "data_fingerprint", None)
                            or previous.get("_data_fingerprint"))
    data_changed = (
        previous_fingerprint is not None and previous_fingerprint != fingerprint
    )
    card.data_fingerprint = fingerprint
    card.sections_v2 = {**sections, "_data_fingerprint": fingerprint}
    if data_changed:
        version.approval_status = "pending"
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="model.approve",
        intent=AuditIntent(
            project_id=project_id, action="model_card.refresh",
            resource_type="model_card", resource_id=str(card.id),
            changes={"data_changed": data_changed},
        ),
        allowed_changes={"data_changed"},
    ):
        db.commit()
    return {
        "card_id": str(card.id),
        "sections": sections,
        "data_fingerprint_changed": data_changed,
        "approval_status": version.approval_status,
    }


@router.get("/api/projects/{project_id}/model-versions/{version_id}/explain-sample")
def explain_sample_endpoint(
    project_id: UUID,
    version_id: UUID,
    row: str = Query(default="{}"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """单样本解释（重要性×偏离近似 + 口径脚注）。"""
    import json as _json

    require_project_access(db, project_id, current_user.id, "project.read")
    version = _version_or_404(db, project_id, version_id)
    try:
        row_data = _json.loads(row or "{}")
    except ValueError:
        raise HTTPException(400, {"code": "EXPLAIN_ROW_INVALID"}) from None
    feature_columns = [str(c) for c in (version.feature_schema or [])]
    try:
        return explain_sample(
            db, version=version, project_id=project_id,
            row=row_data, feature_columns=feature_columns,
        )
    except TrustError as error:
        raise HTTPException(409, {"code": error.code, "message": error.message}) from None
