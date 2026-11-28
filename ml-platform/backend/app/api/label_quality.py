"""Label quality endpoints (补齐路线第二批 S3, 技术方案 §8.3)."""

import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.project_security import audit_service, require_project_access
from app.database import get_db
from app.models.label_quality import (
    ActiveLearningSelection,
    ConsistencyRound,
    LabelArbitration,
    PseudoLabelBatch,
)
from app.models.user import User
from app.services.audit import AuditIntent
from app.services.consistency import (
    ConsistencyError,
    cluster_purity,
    cluster_view_samples,
    compute_kappa,
    decide_arbitration,
    label_quality_gate,
    open_round,
    submit_blind_label,
)

router = APIRouter(tags=["label-quality"])

# 写端点审计登记（横向合同 §6-4；第三轮复审 2026-11-28 补齐——盲标提交
# PUT labels 曾无审计，随登记同批补上 audit_service 包装）
PROJECT_WRITE_ACTIONS = {
    "POST /api/projects/{project_id}/active-learning/selections": "active_learning.selection",
    "POST /api/projects/{project_id}/consistency-rounds": "consistency_round.open",
    "PUT /api/projects/{project_id}/consistency-rounds/{round_id}/labels": "consistency_round.label_submit",
    "POST /api/projects/{project_id}/consistency-rounds/{round_id}/compute": "consistency_round.compute",
    "POST /api/projects/{project_id}/arbitrations/{arbitration_id}/decide": "arbitration.decide",
    "POST /api/projects/{project_id}/pseudo-labels/batches": "pseudo_label.batch",
}


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: dict
    budget_initial: int = Field(default=100, ge=1)
    budget_per_round: int = Field(default=50, ge=1)
    frame_rows: list[dict] = Field(default_factory=list)
    feature_columns: list[str] = Field(default_factory=list)
    bundle_payload: dict | None = None


class RoundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annotator_subject_ids: list[str] = Field(min_length=2)
    sample_ids: list[str] = Field(min_length=1)
    task_id: UUID | None = None
    kappa_threshold: float = Field(default=0.6, ge=0.0, le=1.0)


class BlindLabelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 〔第三轮复审 2026-11-28〕subject_id 不再来自请求体——一律绑定登录用户
    # （曾为自由字符串：一人可用不同 subject 替全部标注位提交，且与仲裁人
    # 的 UUID 身份空间不一致，ARBITER_SAME_AS_BLIND_ANNOTATOR 形同虚设）。
    sample_id: str
    values: dict


class ArbitrationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_values: dict
    note: str | None = Field(default=None, max_length=256)


class PseudoBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version_id: UUID | None = None
    model_version_id: UUID | None = None
    threshold: float = Field(default=0.9, ge=0.5, le=1.0)
    quota_multiplier: float = Field(default=1.0, ge=0.1, le=10.0)
    candidates: list[dict] = Field(
        description="已由调用方（模型打分服务）产出的候选行：sample_key/label/confidence"
    )


def _consistency_error(error: ConsistencyError, statuses: dict | None = None) -> None:
    mapping = statuses or {}
    status = mapping.get(error.code, 400)
    if error.code.endswith("_NOT_FOUND"):
        status = 404
    if "CONFLICT" in error.code or "DENIED" in error.code or "REJECTED" in error.code:
        status = 409
    raise HTTPException(status, {"code": error.code, "message": error.message})


@router.post("/api/projects/{project_id}/active-learning/selections")
def create_selection(
    project_id: UUID,
    payload_in: SelectionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """主动学习选样（B2-05）：frame_rows 为调用方冻结样本池（样本键+特征+可选
    簇/优先级列），九策略或混合按预算出样并落命中统计。"""
    import pandas as pd

    from app.services.active_learning import SelectionError, record_selection, select_samples

    access = require_project_access(db, project_id, current_user.id, "quality.manage")
    if not payload_in.frame_rows:
        raise HTTPException(400, {"code": "SELECTION_FRAME_REQUIRED"})
    frame = pd.DataFrame(payload_in.frame_rows)
    feature_columns = list(payload_in.feature_columns or [])
    class _StubBundle:
        classes_ = None

        def predict_proba(self, matrix):
            import numpy as np

            weights = []
            for row in payload_in.frame_rows:
                prob = row.get("probability")
                weights.append([1 - prob, prob] if prob is not None else [0.5, 0.5])
            return np.array(weights)

    try:
        selected, stats = select_samples(
            bundle=_StubBundle(), frame=frame,
            feature_columns=feature_columns,
            strategy=payload_in.strategy,
            budget_initial=payload_in.budget_initial,
            budget_per_round=payload_in.budget_per_round,
        )
    except SelectionError as error:
        raise HTTPException(400, {"code": error.code, "message": error.message}) from None
    sample_ids = [
        str(payload_in.frame_rows[index].get("sample_key") or index)
        for index in selected
    ]
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="active_learning.selection",
            resource_type="active_learning_selection",
            changes={"strategy": payload_in.strategy.get("name")},
        ),
        allowed_changes={"strategy"},
    ):
        row = record_selection(
            db, project_id=project_id, model_version_id=None,
            strategy=payload_in.strategy,
            budget_initial=payload_in.budget_initial,
            budget_per_round=payload_in.budget_per_round,
            selected_sample_ids=sample_ids, strategy_stats=stats,
            created_by_id=current_user.id,
        )
    return {
        "id": str(row.id),
        "selected_sample_ids": row.selected_sample_ids,
        "strategy_stats": row.strategy_stats,
        "fingerprint": row.fingerprint,
    }


@router.get("/api/projects/{project_id}/active-learning/selections")
def list_selections(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = (
        db.query(ActiveLearningSelection)
        .filter(ActiveLearningSelection.project_id == project_id)
        .order_by(ActiveLearningSelection.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "strategy": row.strategy,
                "budget_per_round": row.budget_per_round,
                "selected_count": len(row.selected_sample_ids or []),
                "strategy_stats": row.strategy_stats,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.post("/api/projects/{project_id}/consistency-rounds")
def open_consistency_round(
    project_id: UUID,
    payload_in: RoundRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """开一致性轮（B2-06）：≥2 标注员盲标同一批样本。"""
    access = require_project_access(db, project_id, current_user.id, "quality.manage")
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="consistency_round.open",
            resource_type="consistency_round",
            changes={"annotators": len(payload_in.annotator_subject_ids),
                     "samples": len(payload_in.sample_ids)},
        ),
        allowed_changes={"annotators", "samples"},
    ):
        try:
            round_row = open_round(
                db, project_id=project_id,
                annotator_subject_ids=payload_in.annotator_subject_ids,
                sample_ids=payload_in.sample_ids,
                task_id=payload_in.task_id,
                kappa_threshold=payload_in.kappa_threshold,
                created_by_id=current_user.id,
            )
        except ConsistencyError as error:
            _consistency_error(error)
    return {"id": str(round_row.id), "status": round_row.status}


@router.put("/api/projects/{project_id}/consistency-rounds/{round_id}/labels")
def submit_blind_label_endpoint(
    project_id: UUID,
    round_id: UUID,
    payload_in: BlindLabelRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """盲标提交（round 成员；每样本每标注员一票；subject=登录用户 id）。"""
    access = require_project_access(db, project_id, current_user.id, "quality.label")
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.label",
        intent=AuditIntent(
            project_id=project_id, action="consistency_round.label_submit",
            resource_type="consistency_round", resource_id=str(round_id),
            changes={"sample_id": payload_in.sample_id},
        ),
        allowed_changes={"sample_id"},
    ):
        try:
            row = submit_blind_label(
                db, round_id=round_id, subject_id=str(current_user.id),
                sample_id=payload_in.sample_id, values=payload_in.values,
            )
        except ConsistencyError as error:
            _consistency_error(error)
    db.commit()
    return {"id": str(row.id)}


@router.post("/api/projects/{project_id}/consistency-rounds/{round_id}/compute")
def compute_round_kappa(
    project_id: UUID,
    round_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """κ 计算 + 分歧自动进仲裁队列。"""
    access = require_project_access(db, project_id, current_user.id, "quality.manage")
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="consistency_round.compute",
            resource_type="consistency_round", resource_id=str(round_id),
            changes={},
        ),
        allowed_changes=set(),
    ):
        try:
            round_row = compute_kappa(db, round_id=round_id)
        except ConsistencyError as error:
            _consistency_error(error)
    db.commit()
    return {
        "kappa_pairwise": round_row.kappa_pairwise,
        "kappa_average": round_row.kappa_average,
        "status": round_row.status,
    }


@router.get("/api/projects/{project_id}/arbitrations")
def list_arbitrations(
    project_id: UUID,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    query = (
        db.query(LabelArbitration)
        .join(ConsistencyRound, LabelArbitration.round_id == ConsistencyRound.id)
        .filter(ConsistencyRound.project_id == project_id)
    )
    if status:
        query = query.filter(LabelArbitration.status == status)
    rows = query.order_by(LabelArbitration.status.desc()).limit(200).all()
    return {
        "items": [
            {
                "id": str(row.id),
                "round_id": str(row.round_id),
                "sample_id": row.sample_id,
                "conflict": row.conflict,
                "status": row.status,
                "decision_values": row.decision_values,
                "arbiter_id": str(row.arbiter_id) if row.arbiter_id else None,
            }
            for row in rows
        ]
    }


@router.post("/api/projects/{project_id}/arbitrations/{arbitration_id}/decide")
def decide_arbitration_endpoint(
    project_id: UUID,
    arbitration_id: UUID,
    payload_in: ArbitrationDecision,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """仲裁终审（quality.review；仲裁人≠盲标人）；终审值由调用方写回规范通道。"""
    access = require_project_access(db, project_id, current_user.id, "quality.review")
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.review",
        intent=AuditIntent(
            project_id=project_id, action="arbitration.decide",
            resource_type="label_arbitration", resource_id=str(arbitration_id),
            changes={},
        ),
        allowed_changes=set(),
    ):
        try:
            arbitration = decide_arbitration(
                db, arbitration_id=arbitration_id, arbiter_id=current_user.id,
                decision_values=payload_in.decision_values, note=payload_in.note,
            )
        except ConsistencyError as error:
            _consistency_error(error)
    db.commit()
    return {"id": str(arbitration.id), "status": arbitration.status}


@router.get("/api/projects/{project_id}/label-quality/gate")
def label_quality_gate_endpoint(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """E15 质量门状态（训练创建前调用）。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    return label_quality_gate(db, project_id=project_id)


@router.get("/api/projects/{project_id}/clusters/{strategy_artifact_id}/{cluster_id}/purity")
def cluster_purity_endpoint(
    project_id: UUID,
    strategy_artifact_id: UUID,
    cluster_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    return cluster_purity(
        db, strategy_artifact_id=strategy_artifact_id, cluster_id=cluster_id
    )


@router.get("/api/projects/{project_id}/clusters/{strategy_artifact_id}/{cluster_id}/views")
def cluster_views_endpoint(
    project_id: UUID,
    strategy_artifact_id: UUID,
    cluster_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    return cluster_view_samples(
        db, strategy_artifact_id=strategy_artifact_id, cluster_id=cluster_id
    )


@router.post("/api/projects/{project_id}/pseudo-labels/batches")
def create_pseudo_batch(
    project_id: UUID,
    payload_in: PseudoBatchRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """伪标签批（B2-G4）：调用方传入已打分候选（模型打分由推理侧完成），
    平台做阈值过滤/每类限量/降权/凭证落库。"""
    from app.services.pseudo_labels import (
        PseudoLabelError,
        record_pseudo_batch_from_candidates,
    )

    access = require_project_access(db, project_id, current_user.id, "quality.manage")
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="quality.manage",
        intent=AuditIntent(
            project_id=project_id, action="pseudo_label.batch",
            resource_type="pseudo_label_batch",
            changes={"threshold": payload_in.threshold},
        ),
        allowed_changes={"threshold"},
    ):
        try:
            batch = record_pseudo_batch_from_candidates(
                db, project_id=project_id,
                dataset_version_id=payload_in.dataset_version_id,
                model_version_id=payload_in.model_version_id,
                candidates=payload_in.candidates,
                threshold=payload_in.threshold,
                quota_multiplier=payload_in.quota_multiplier,
                labeled_counts={},
                created_by_id=current_user.id,
            )
        except PseudoLabelError as error:
            raise HTTPException(400, {"code": error.code, "message": error.message}) from None
    return {"id": str(batch.id), "selected_count": len(batch.selected)}


@router.get("/api/projects/{project_id}/pseudo-labels/batches/{batch_id}/credential.csv")
def export_pseudo_credential(
    project_id: UUID,
    batch_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """凭证导出（样本/生成模型/训练折/置信度/权重——与库内一致）。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    batch = db.get(PseudoLabelBatch, batch_id)
    if batch is None or str(batch.project_id) != str(project_id):
        raise HTTPException(404, {"code": "PSEUDO_BATCH_NOT_FOUND"})
    from app.services.pseudo_labels import credential_rows

    rows = credential_rows(batch)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["sample_key", "model_version_id", "training_fold",
                     "confidence", "weight", "label"])
    for row in rows:
        writer.writerow([row.get("sample_key"), row.get("model_version_id"),
                         row.get("training_fold"), row.get("confidence"),
                         row.get("weight"), row.get("label")])
    buffer.seek(0)
    return StreamingResponse(
        iter(["\ufeff", buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=pseudo-label-credential.csv"},
    )
