"""Dataset split & modeling round endpoints (补齐路线第二批 S2a, B2-G1, §6.5).

划分/成员无写动词（除创建）——不可变性 API 面；轮次创建即锁定；
盲测评估记录走台账（E03 上限、E04 永不重分）。
"""

import uuid as _uuid
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.project_security import audit_service, require_project_access
from app.database import get_db
from app.models.data_version import DatasetVersion
from app.models.dataset_splitting import BlindTestUsage, ModelingRound
from app.models.user import User
from app.services.audit import AuditIntent
from app.services.dataset_splitting import (
    SplitError,
    create_split,
    load_role_indices,
)
from app.services.modeling_rounds import (
    RoundError,
    close_round,
    record_blind_evaluation,
    start_round,
)

router = APIRouter(tags=["dataset-splits"])


class SplitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version_id: UUID
    name: str = Field(min_length=1, max_length=128)
    strategy: str
    params: dict = Field(default_factory=dict)


class RoundStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    split_id: UUID
    cap: int = Field(default=2, ge=1, le=10)


class BlindEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str
    sample_count: int = Field(ge=0)
    samples_fingerprint: str = Field(min_length=8, max_length=64)
    ref: dict = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=256)


def _raise_split_error(error: SplitError) -> None:
    raise HTTPException(400, {"code": error.code, "message": error.message})


def _raise_round_error(error: RoundError) -> None:
    status = 409 if error.code in {
        "BLIND_REUSE_REJECTED",
        "BLIND_EVAL_CAP_REACHED",
        "MODELING_ROUND_STATE_CONFLICT",
    } else 404 if error.code.endswith("_NOT_FOUND") else 400
    raise HTTPException(status, {"code": error.code, "message": error.message})


@router.post("/api/projects/{project_id}/dataset-splits")
def create_dataset_split(
    project_id: UUID,
    payload_in: SplitCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建划分（E04 入库即定）：按版本工件物化 frame 出角色，成员持久化。"""
    access = require_project_access(db, project_id, current_user.id, "model.register")
    version = db.get(DatasetVersion, payload_in.dataset_version_id)
    if version is None or str(version.project_id) != str(project_id):
        raise HTTPException(404, {"code": "DATASET_VERSION_NOT_FOUND"})
    artifact_id = version.normalized_artifact_id or version.original_artifact_id
    if artifact_id is None:
        raise HTTPException(409, {"code": "DATASET_VERSION_NO_ARTIFACT"})
    from app.services.artifact_service import build_artifact_service

    artifact_service = build_artifact_service(db)
    with artifact_service.materialize(
        artifact_id, project_id, expected_type="dataset",
    ) as dataset_path:
        frame = pd.read_csv(dataset_path)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="model.register",
        intent=AuditIntent(
            project_id=project_id,
            action="dataset_split.create",
            resource_type="dataset_split",
            changes={"strategy": payload_in.strategy, "name": payload_in.name},
        ),
        allowed_changes={"strategy", "name"},
    ):
        try:
            split = create_split(
                db,
                project_id=project_id,
                dataset_version_id=payload_in.dataset_version_id,
                name=payload_in.name,
                strategy=payload_in.strategy,
                params=payload_in.params,
                frame=frame,
                created_by_id=current_user.id,
            )
        except SplitError as error:
            _raise_split_error(error)
    return _split_view(db, split)


def _split_view(db: Session, split) -> dict:
    roles = load_role_indices(db, split.id)
    return {
        "id": str(split.id),
        "project_id": str(split.project_id),
        "dataset_version_id": str(split.dataset_version_id),
        "name": split.name,
        "strategy": split.strategy,
        "params": split.params,
        "split_fingerprint": split.split_fingerprint,
        "counts": {role: len(indices) for role, indices in roles.items()},
        "created_at": split.created_at.isoformat() if split.created_at else None,
    }


@router.get("/api/projects/{project_id}/dataset-splits")
def list_dataset_splits(
    project_id: UUID,
    dataset_version_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    from app.models.dataset_splitting import DatasetSplit

    query = db.query(DatasetSplit).filter(DatasetSplit.project_id == project_id)
    if dataset_version_id is not None:
        query = query.filter(DatasetSplit.dataset_version_id == dataset_version_id)
    rows = query.order_by(DatasetSplit.created_at.desc()).limit(100).all()
    return {"items": [_split_view(db, row) for row in rows]}


def _round_view(round_row: ModelingRound) -> dict:
    return {
        "id": str(round_row.id),
        "project_id": str(round_row.project_id),
        "dataset_version_id": str(round_row.dataset_version_id),
        "split_id": str(round_row.split_id),
        "status": round_row.status,
        "blind_eval_count": round_row.blind_eval_count,
        "blind_eval_cap": round_row.blind_eval_cap,
        "blind_fingerprint": round_row.blind_fingerprint,
        "locked_at": round_row.locked_at.isoformat() if round_row.locked_at else None,
        "closed_at": round_row.closed_at.isoformat() if round_row.closed_at else None,
    }


@router.post("/api/projects/{project_id}/modeling-rounds")
def start_modeling_round(
    project_id: UUID,
    payload_in: RoundStart,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建建模轮次（创建即锁定）；旧盲测复用被拒（B2-G1 验收口径 1/3）。"""
    access = require_project_access(db, project_id, current_user.id, "model.register")
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="model.register",
        intent=AuditIntent(
            project_id=project_id,
            action="modeling_round.start",
            resource_type="modeling_round",
            changes={"split_id": str(payload_in.split_id)},
        ),
        allowed_changes={"split_id"},
    ):
        try:
            round_row = start_round(
                db, project_id=project_id, split_id=payload_in.split_id,
                actor_id=current_user.id, cap=payload_in.cap,
            )
        except RoundError as error:
            _raise_round_error(error)
    return _round_view(round_row)


@router.get("/api/projects/{project_id}/modeling-rounds")
def list_modeling_rounds(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = (
        db.query(ModelingRound)
        .filter(ModelingRound.project_id == project_id)
        .order_by(ModelingRound.created_at.desc())
        .limit(100)
        .all()
    )
    return {"items": [_round_view(row) for row in rows]}


@router.post("/api/projects/{project_id}/modeling-rounds/{round_id}/blind-evaluations")
def record_blind_evaluation_endpoint(
    project_id: UUID,
    round_id: UUID,
    payload_in: BlindEvaluation,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录一次盲测评估（E03 上限内）：自动进历史台账。"""
    access = require_project_access(db, project_id, current_user.id, "model.register")
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="model.register",
        intent=AuditIntent(
            project_id=project_id,
            action="modeling_round.blind_evaluation",
            resource_type="modeling_round",
            resource_id=str(round_id),
            changes={"purpose": payload_in.purpose},
        ),
        allowed_changes={"purpose"},
    ):
        try:
            usage = record_blind_evaluation(
                db, round_id=round_id, purpose=payload_in.purpose,
                used_by_id=current_user.id,
                sample_count=payload_in.sample_count,
                samples_fingerprint=payload_in.samples_fingerprint,
                ref=payload_in.ref, note=payload_in.note,
            )
        except RoundError as error:
            _raise_round_error(error)
    return {
        "id": str(usage.id),
        "round_id": str(usage.round_id),
        "purpose": usage.purpose,
        "sample_count": usage.sample_count,
        "used_at": usage.used_at.isoformat() if usage.used_at else None,
    }


@router.get("/api/projects/{project_id}/blind-usages")
def list_blind_usages(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """盲测历史台账（三级样本量看板数据源）。"""
    require_project_access(db, project_id, current_user.id, "project.read")
    rows = (
        db.query(BlindTestUsage)
        .filter(BlindTestUsage.project_id == project_id)
        .order_by(BlindTestUsage.used_at.desc())
        .limit(200)
        .all()
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "round_id": str(row.round_id),
                "split_id": str(row.split_id),
                "purpose": row.purpose,
                "sample_count": row.sample_count,
                "samples_fingerprint": row.samples_fingerprint,
                "note": row.note,
                "used_at": row.used_at.isoformat() if row.used_at else None,
            }
            for row in rows
        ]
    }


@router.post("/api/projects/{project_id}/modeling-rounds/{round_id}/close")
def close_modeling_round(
    project_id: UUID,
    round_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    access = require_project_access(db, project_id, current_user.id, "model.register")
    try:
        round_row = close_round(db, round_id=round_id, actor_id=current_user.id)
    except RoundError as error:
        _raise_round_error(error)
    return _round_view(round_row)
