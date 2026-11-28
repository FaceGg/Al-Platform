"""Release governance endpoints (补齐路线第二批 S2b, 技术方案 §7.3)."""

import csv
import io
import uuid as _uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.project_security import audit_service, require_project_access
from app.database import get_db
from app.models.model_registry import InferenceDeployment, ModelVersion
from app.models.release_governance import (
    ShadowComparison,
)
from app.models.user import User
from app.services.audit import AuditIntent
from app.services.release_governance import (
    GovernanceError,
    build_shadow_report,
    evaluate_release_gates,
    grant_preauthorization,
    record_rollout_receipt,
    register_challenger,
    revoke_preauthorization,
    retire_challenger,
    run_shadow_batch,
    shadow_window_gate,
)

router = APIRouter(tags=["release-governance"])

# 写端点审计登记（横向合同 §6-4；第三轮复审 2026-11-28 补齐）。回执端点
# （POST /rollouts/{id}/receipts）按 X-Api-Key 外部鉴权、无项目级审计，
# 不在本登记范围。
PROJECT_WRITE_ACTIONS = {
    "POST /api/projects/{project_id}/inference-deployments/{deployment_id}/challenger": "challenger.register",
    "DELETE /api/projects/{project_id}/inference-deployments/{deployment_id}/challenger": "challenger.retire",
    "POST /api/projects/{project_id}/inference-deployments/{deployment_id}/shadow/runs": "shadow.run",
    "POST /api/projects/{project_id}/release-preauthorizations": "release_preauthorization.grant",
    "DELETE /api/projects/{project_id}/release-preauthorizations/{auth_id}": "release_preauthorization.revoke",
    "POST /api/projects/{project_id}/model-versions/{version_id}/release-request": "release.request",
}


class ChallengerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version_id: UUID


class ShadowRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version_id: UUID
    sample_source: str = "random_sample"
    sample_size: int | None = Field(default=None, ge=1, le=100000)


class PreauthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment_id: UUID | None = None
    acceptance_gates_fingerprint: str = Field(min_length=8, max_length=64)
    expires_at: str
    max_releases: int = Field(default=1, ge=1, le=100)
    note: str | None = Field(default=None, max_length=256)


class ReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rollout_id: UUID
    revision_id: UUID | None = None
    effective_alias: str = Field(min_length=1, max_length=256)
    scored_count: int = Field(ge=0)
    artifact_digest: str | None = Field(default=None, max_length=64)
    routing_key: str | None = Field(default=None, max_length=256)


class ReleaseRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment_id: UUID
    model_version_id: UUID
    preauthorization_id: UUID | None = None
    strategy: str = "canary"
    force_shadow_gate: bool = False


def _governance_error(error: GovernanceError, status: int = 409) -> None:
    raise HTTPException(status, {"code": error.code, "message": error.message})


def _get_deployment(db: Session, project_id: UUID, deployment_id: UUID):
    deployment = db.get(InferenceDeployment, deployment_id)
    if deployment is None or str(deployment.project_id) != str(project_id):
        raise HTTPException(404, {"code": "DEPLOYMENT_NOT_FOUND"})
    return deployment


@router.post("/api/projects/{project_id}/inference-deployments/{deployment_id}/challenger")
def register_challenger_endpoint(
    project_id: UUID,
    deployment_id: UUID,
    payload_in: ChallengerRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """注册影子候选（B2-09）：challenger 部署目标，权重恒 0 不进生产路由。"""
    access = require_project_access(db, project_id, current_user.id, "deployment.create")
    deployment = _get_deployment(db, project_id, deployment_id)
    version = db.get(ModelVersion, payload_in.model_version_id)
    if version is None:
        raise HTTPException(404, {"code": "MODEL_VERSION_NOT_FOUND"})
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="deployment.create",
        intent=AuditIntent(
            project_id=project_id, action="challenger.register",
            resource_type="deployment_target",
            resource_id=str(payload_in.model_version_id),
            changes={"deployment_id": str(deployment_id)},
        ),
        allowed_changes={"deployment_id"},
    ):
        try:
            target = register_challenger(
                db, deployment=deployment, version=version,
                actor_id=current_user.id,
            )
        except GovernanceError as error:
            _governance_error(error)
    return {"target_id": str(target.id), "role": "challenger", "weight_bps": 0}


@router.delete("/api/projects/{project_id}/inference-deployments/{deployment_id}/challenger")
def retire_challenger_endpoint(
    project_id: UUID,
    deployment_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = require_project_access(db, project_id, current_user.id, "deployment.create")
    _get_deployment(db, project_id, deployment_id)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="deployment.create",
        intent=AuditIntent(
            project_id=project_id, action="challenger.retire",
            resource_type="deployment_target", resource_id=str(deployment_id),
            changes={},
        ),
        allowed_changes=set(),
    ):
        try:
            result = retire_challenger(
                db, deployment_id=deployment_id, actor_id=current_user.id
            )
        except GovernanceError as error:
            _governance_error(error)
    return result


@router.post("/api/projects/{project_id}/inference-deployments/{deployment_id}/shadow/runs")
def run_shadow_endpoint(
    project_id: UUID,
    deployment_id: UUID,
    payload_in: ShadowRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """影子打分（B2-02）：候选对样本批打分落 channel=shadow 明细，不写预警表。"""
    access = require_project_access(db, project_id, current_user.id, "deployment.create")
    deployment = _get_deployment(db, project_id, deployment_id)
    version = db.get(ModelVersion, payload_in.model_version_id)
    if version is None:
        raise HTTPException(404, {"code": "MODEL_VERSION_NOT_FOUND"})
    # 影子数据源：部署绑定数据集的 development 行（合成样本池）
    from app.services.dataset_splitting import SplitError
    from app.services.release_governance import GovernanceError

    try:
        frame, feature_columns = _shadow_frame(db, project_id, deployment)
    except (SplitError, GovernanceError) as error:
        code = getattr(error, "code", None) or "SHADOW_NO_SAMPLE_POOL"
        message = getattr(error, "message", None) or str(error)
        raise HTTPException(409, {"code": code, "message": message}) from None
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="deployment.create",
        intent=AuditIntent(
            project_id=project_id, action="shadow.run",
            resource_type="deployment", resource_id=str(deployment_id),
            changes={"source": payload_in.sample_source},
        ),
        allowed_changes={"source"},
    ):
        try:
            scored = run_shadow_batch(
                db, deployment=deployment, challenger_version=version,
                frame=frame, feature_columns=feature_columns,
                sample_source=payload_in.sample_source,
                sample_size=payload_in.sample_size,
                actor_id=current_user.id,
            )
        except GovernanceError as error:
            _governance_error(error)
    report = build_shadow_report(
        db, deployment=deployment,
        challenger_version_id=version.id, actor_id=current_user.id,
    )
    db.commit()
    return {
        "scored": scored,
        "report_id": str(report.id),
        "agreement_rate": report.agreement_rate,
        "sample_count": report.sample_count,
    }


def _shadow_frame(db: Session, project_id: UUID, deployment):
    """影子样本池：最近划分的 development 行；无划分则回退版本工件全量前 500 行。"""
    from app.services.dataset_splitting import (
        filter_frame_by_roles,
        load_role_indices,
    )
    from app.services.modeling_rounds import RoundError
    from app.services.release_governance import GovernanceError as _GE

    from app.models.dataset_splitting import ModelingRound

    round_row = (
        db.query(ModelingRound)
        .filter(
            ModelingRound.project_id == project_id,
            ModelingRound.status == "locked",
        )
        .order_by(ModelingRound.created_at.desc())
        .first()
    )
    feature_columns = _deployment_feature_columns(db, deployment)
    if round_row is not None:
        roles = load_role_indices(db, round_row.split_id)
        frame = _materialize_version_frame(db, project_id, round_row.dataset_version_id)
        return filter_frame_by_roles(frame, roles, "development"), feature_columns
    raise _GE("SHADOW_NO_SAMPLE_POOL")


def _deployment_feature_columns(db: Session, deployment) -> list:
    # 单一来源：实现已移入 service 层（终验/不回退的盲测打分共用）
    from app.services.release_governance import deployment_feature_columns

    return deployment_feature_columns(db, deployment)


def _materialize_version_frame(db: Session, project_id: UUID, dataset_version_id):
    # 单一来源：实现已移入 service 层；原 HTTPException 换为 GovernanceError
    #（影子端点的调用方已有 GovernanceError 映射，SHADOW_NO_SAMPLE_POOL 不再 500）
    from app.services.release_governance import (
        GovernanceError,
        materialize_version_frame as _materialize,
    )

    try:
        return _materialize(db, project_id, dataset_version_id)
    except GovernanceError as error:
        raise HTTPException(409, {"code": error.code, "message": error.message}) from None


@router.get("/api/projects/{project_id}/inference-deployments/{deployment_id}/shadow/reports")
def list_shadow_reports(
    project_id: UUID,
    deployment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    _get_deployment(db, project_id, deployment_id)
    rows = (
        db.query(ShadowComparison)
        .filter(ShadowComparison.deployment_id == deployment_id)
        .order_by(ShadowComparison.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "champion_version_id": str(row.champion_version_id) if row.champion_version_id else None,
                "challenger_version_id": str(row.challenger_version_id) if row.challenger_version_id else None,
                "sample_source": row.sample_source,
                "sample_count": row.sample_count,
                "agreement_rate": row.agreement_rate,
                "detail": row.detail,
                "report_fingerprint": row.report_fingerprint,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.get("/api/projects/{project_id}/inference-deployments/{deployment_id}/shadow/reports/{report_id}/export.csv")
def export_shadow_report(
    project_id: UUID,
    deployment_id: UUID,
    report_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    report = db.get(ShadowComparison, report_id)
    if report is None:
        raise HTTPException(404, {"code": "SHADOW_REPORT_NOT_FOUND"})
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["metric", "value"])
    writer.writerow(["sample_count", report.sample_count])
    writer.writerow(["agreement_rate", report.agreement_rate])
    writer.writerow(["sample_source", report.sample_source])
    writer.writerow(["report_fingerprint", report.report_fingerprint])
    for group, stats in sorted(((row.detail or {}).get("grouped") or {}).items()):
        writer.writerow([f"group:{group}:count", stats.get("count")])
        writer.writerow([f"group:{group}:agreed", stats.get("agreed")])
    buffer.seek(0)
    return StreamingResponse(
        iter(["\ufeff", buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=shadow-report.csv"},
    )


@router.post("/api/projects/{project_id}/release-preauthorizations")
def grant_preauthorization_endpoint(
    project_id: UUID,
    payload_in: PreauthRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """授予发布预授权（G2）：授权人须 approval.approve；申请人≠授权人在使用时强制。"""
    from datetime import datetime

    access = require_project_access(db, project_id, current_user.id, "approval.approve")
    try:
        expires_at = datetime.fromisoformat(payload_in.expires_at)
    except ValueError:
        raise HTTPException(400, {"code": "PREAUTH_EXPIRES_INVALID"}) from None
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="approval.approve",
        intent=AuditIntent(
            project_id=project_id, action="release_preauthorization.grant",
            resource_type="release_preauthorization", changes={"max_releases": payload_in.max_releases},
        ),
        allowed_changes={"max_releases"},
    ):
        auth = grant_preauthorization(
            db, project_id=project_id,
            deployment_id=payload_in.deployment_id,
            gates_fingerprint=payload_in.acceptance_gates_fingerprint,
            expires_at=expires_at,
            max_releases=payload_in.max_releases,
            granted_by_id=current_user.id,
            note=payload_in.note,
        )
    return {"id": str(auth.id), "status": auth.status, "max_releases": auth.max_releases}


@router.delete("/api/projects/{project_id}/release-preauthorizations/{auth_id}")
def revoke_preauthorization_endpoint(
    project_id: UUID,
    auth_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = require_project_access(db, project_id, current_user.id, "approval.approve")
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="approval.approve",
        intent=AuditIntent(
            project_id=project_id, action="release_preauthorization.revoke",
            resource_type="release_preauthorization", resource_id=str(auth_id),
            changes={},
        ),
        allowed_changes=set(),
    ):
        result = revoke_preauthorization(db, auth_id=auth_id, actor_id=current_user.id)
    return result


@router.post("/api/inference-deployments/{deployment_id}/rollouts/{rollout_id}/receipts")
def record_rollout_receipt_endpoint(
    deployment_id: UUID,
    rollout_id: UUID,
    payload_in: ReceiptRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """服务端回执（G3）：契约四要素；产物摘要不符 → digest_mismatch。"""
    deployment = db.get(InferenceDeployment, deployment_id)
    if deployment is None:
        raise HTTPException(404, {"code": "DEPLOYMENT_NOT_FOUND"})
    require_project_access(db, deployment.project_id, current_user.id, "inference.operate")
    receipt = record_rollout_receipt(
        db, project_id=deployment.project_id,
        rollout_id=payload_in.rollout_id, revision_id=payload_in.revision_id,
        effective_alias=payload_in.effective_alias,
        scored_count=payload_in.scored_count,
        artifact_digest=payload_in.artifact_digest,
        routing_key=payload_in.routing_key,
        reported_by_id=current_user.id,
    )
    db.commit()
    return {"id": str(receipt.id), "status": receipt.status}


@router.post("/api/projects/{project_id}/model-versions/{version_id}/release-request")
def create_release_request(
    project_id: UUID,
    version_id: UUID,
    payload_in: ReleaseRequestBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建 model_release 审批（B2-03）：门禁评估先行、checks 随单落档。"""
    from app.services.approvals import ApprovalError, create_approval
    from app.services.release_governance import evaluate_release_gates

    access = require_project_access(db, project_id, current_user.id, "quality.manage")
    deployment = _get_deployment(db, project_id, payload_in.deployment_id)
    version = db.get(ModelVersion, version_id)
    if version is None:
        raise HTTPException(404, {"code": "MODEL_VERSION_NOT_FOUND"})
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="release.request",
            resource_type="model_version", resource_id=str(version_id),
            changes={"deployment_id": str(payload_in.deployment_id)},
        ),
        allowed_changes={"deployment_id"},
    ):
        release_payload = {
            "deployment_id": str(payload_in.deployment_id),
            "model_version_id": str(version_id),
            "preauthorization_id": (
                str(payload_in.preauthorization_id) if payload_in.preauthorization_id else None
            ),
            "strategy": payload_in.strategy,
            "force_shadow_gate": payload_in.force_shadow_gate,
        }
        try:
            approval = create_approval(
                db, project_id=project_id, approval_type="model_release",
                title=f"发布申请：部署 {str(payload_in.deployment_id)[:8]} 版本 {str(version_id)[:8]}",
                payload=release_payload,
                initiator_id=current_user.id,
            )
        except ApprovalError as error:
            # E01 豁免依据落档（第三轮复审 2026-11-28）：审计上下文的回滚已
            # 撤销探测产物——此处重评估一次并把 failed checks 落档为 rejected
            # 存档单（豁免单 payload.release_approval_id 指向它；盲测记账经
            # 幂等保护不重复消耗 cap）。曾即造即删——门禁失败的发布单建不出
            # 来，豁免永远 EXEMPTION_NO_RELEASE_CHECKS，链路不可达。
            from datetime import datetime as _dt

            from app.models.approvals import ApprovalRequest
            from app.services.release_governance import evaluate_release_gates

            db.rollback()
            archived = ApprovalRequest(
                project_id=project_id, type="model_release",
                title=(f"发布申请存档（门禁未过）：部署 {str(payload_in.deployment_id)[:8]}"
                       f" 版本 {str(version_id)[:8]}"),
                payload={"deployment_id": str(payload_in.deployment_id),
                         "model_version_id": str(version_id), "probe": True},
                payload_fingerprint="0" * 64, status="rejected",
                created_by_id=current_user.id, expires_at=_dt.utcnow(),
            )
            db.add(archived)
            db.flush()
            evaluate_release_gates(db, deployment=deployment, version=version,
                                   approval=archived)
            db.commit()
            raise HTTPException(
                409, {"code": error.code, "message": error.message,
                      "rejected_request_id": str(archived.id)}
            ) from None
        checks = evaluate_release_gates(
            db, deployment=deployment, version=version, approval=approval
        )
        db.flush()
    return {
        "approval_id": str(approval.id),
        "checks": [
            {
                "check_key": check.check_key,
                "verdict": check.verdict,
                "threshold": check.threshold,
                "observed": check.observed,
            }
            for check in checks
        ],
    }
