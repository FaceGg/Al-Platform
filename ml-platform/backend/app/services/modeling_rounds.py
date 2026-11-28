"""Modeling rounds + blind-test ledger (补齐路线第二批 S2a, B2-G1/E03).

轮次创建即锁定（路线「建模轮次开始时锁定独立测试划分」）；已使用的盲测
样本自动进历史台账（blind_test_usages）；新轮次/新评估无法复用旧盲测
（blind 样本指纹与台账比对，交集即拒）；每轮盲测评估次数上限默认 2（E03）。
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.dataset_splitting import (
    BLIND_PURPOSES,
    BlindTestUsage,
    DatasetSplit,
    DatasetSplitMember,
    ModelingRound,
)
from app.models.access import AuditEvent
from app.services.dataset_splitting import SplitError

BLIND_REUSE = "BLIND_REUSE_REJECTED"
CAP_REACHED = "BLIND_EVAL_CAP_REACHED"
NOT_FOUND = "MODELING_ROUND_NOT_FOUND"
STATE_CONFLICT = "MODELING_ROUND_STATE_CONFLICT"


class RoundError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _blind_fingerprint(split_id, member_rows) -> str:
    """本轮 blind 样本集指纹（台账比对键）。

    有业务样本键：只哈希有序键集（跨数据集版本可比——同一批样本换版本后
    仍能撞出台账，堵「旧盲测复用」）；无键（行号回退）：按划分身份哈希
    （行号空间跨版本不可比，复用检测退化为登记身份——诚实限制，登记于
    技术方案 §12.9）。"""
    keys = sorted(str(row.sample_key) for row in member_rows if row.sample_key)
    if keys:
        body = "\n".join(keys)
    else:
        body = f"split:{split_id}|rows:" + ",".join(
            str(row.row_index) for row in sorted(member_rows, key=lambda r: r.row_index)
        )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _ledger_fingerprints(db: Session, dataset_version_id) -> set[str]:
    from app.models.dataset_splitting import BlindTestUsage as Usage

    rows = (
        db.query(Usage.samples_fingerprint)
        .filter(Usage.project_id.isnot(None))
        .all()
    )
    # 台账按轮次回链 split → 版本；这里取同版本全部轮次的台账指纹
    round_ids = [
        str(row[0])
        for row in db.query(ModelingRound.id)
        .filter(ModelingRound.dataset_version_id == dataset_version_id)
        .all()
    ]
    if not round_ids:
        return set()
    usages = (
        db.query(Usage)
        .filter(Usage.round_id.in_([uuid.UUID(value) for value in round_ids]))
        .all()
    )
    return {usage.samples_fingerprint for usage in usages}


def start_round(
    db: Session,
    *,
    project_id,
    split_id,
    actor_id,
    cap: int = 2,
    request_id=None,
) -> ModelingRound:
    """创建轮次（创建即锁定）；旧盲测复用被拒（BLIND_REUSE_REJECTED）。"""
    split = db.get(DatasetSplit, split_id)
    if split is None:
        raise RoundError("DATASET_SPLIT_NOT_FOUND")
    if cap < 1:
        raise RoundError("BLIND_EVAL_CAP_INVALID")
    member_rows = (
        db.query(DatasetSplitMember)
        .filter(DatasetSplitMember.split_id == split_id)
        .all()
    )
    blind_rows = [row for row in member_rows if row.role == "blind"]
    if not blind_rows:
        raise RoundError("BLIND_SET_EMPTY")
    blind_fingerprint = _blind_fingerprint(split_id, blind_rows)
    ledger = _ledger_fingerprints(db, split.dataset_version_id)
    if blind_fingerprint in ledger:
        raise RoundError(BLIND_REUSE)
    round_row = ModelingRound(
        project_id=project_id,
        dataset_version_id=split.dataset_version_id,
        split_id=split_id,
        status="locked",
        blind_eval_cap=int(cap),
        blind_fingerprint=blind_fingerprint,
        created_by_id=actor_id,
    )
    db.add(round_row)
    db.flush()
    _audit_round(db, action="modeling_round.start", round_row=round_row,
                 request_id=request_id, changes={"split_id": str(split_id), "cap": int(cap)})
    return round_row


def _audit_round(db: Session, *, action: str, round_row: ModelingRound,
                 request_id=None, changes: dict | None = None) -> None:
    import uuid as _uuid

    event = AuditEvent(
        project_id=round_row.project_id,
        actor_id=round_row.created_by_id,
        actor_username="system",
        action=action,
        resource_type="modeling_round",
        resource_id=str(round_row.id),
        result="success",
        request_id=request_id or _uuid.uuid4(),
        changes=changes or {},
    )
    from app.services.audit_chain import append as append_chain

    append_chain(db, "audit_events", event)
    db.add(event)


def record_blind_evaluation(
    db: Session,
    *,
    round_id,
    purpose: str,
    used_by_id,
    sample_count: int,
    samples_fingerprint: str,
    ref: dict | None = None,
    note: str | None = None,
) -> BlindTestUsage:
    """记录一次盲测评估：先判上限（E03）后落账 + 轮次计数。

    〔第三轮复审 2026-11-28 幂等化〕同轮次+同样本指纹+同用途的重复评估
    （发布探测评估与端点正式评估双跑）返回既有台账行、不再消耗 cap——
    曾双重记账致默认 cap=2 下发布门禁必 blind_eval_cap_reached（S2b #16：
    探测 2 次 + 正式 2 次 ≥ cap）。"""
    if purpose not in BLIND_PURPOSES:
        raise RoundError("BLIND_PURPOSE_INVALID")
    round_row = db.get(ModelingRound, round_id)
    if round_row is None:
        raise RoundError(NOT_FOUND)
    if round_row.status != "locked":
        raise RoundError(STATE_CONFLICT)
    existing = (
        db.query(BlindTestUsage)
        .filter(
            BlindTestUsage.round_id == round_row.id,
            BlindTestUsage.purpose == purpose,
            BlindTestUsage.samples_fingerprint == samples_fingerprint,
        )
        .first()
    )
    if existing is not None:
        return existing
    if round_row.blind_eval_count >= round_row.blind_eval_cap:
        raise RoundError(CAP_REACHED)
    round_row.blind_eval_count += 1
    usage = BlindTestUsage(
        project_id=round_row.project_id,
        round_id=round_row.id,
        split_id=round_row.split_id,
        purpose=purpose,
        sample_count=int(sample_count),
        samples_fingerprint=samples_fingerprint,
        ref=ref or {},
        note=(note or "")[:256] or None,
        used_by_id=used_by_id,
    )
    db.add(usage)
    db.flush()
    _audit_round(db, action="modeling_round.blind_evaluation",
                 round_row=round_row,
                 changes={"purpose": purpose, "sample_count": int(sample_count),
                          "count": round_row.blind_eval_count,
                          "cap": round_row.blind_eval_cap})
    return usage


def close_round(db: Session, *, round_id, actor_id) -> ModelingRound:
    round_row = db.get(ModelingRound, round_id)
    if round_row is None:
        raise RoundError(NOT_FOUND)
    if round_row.status != "locked":
        raise RoundError(STATE_CONFLICT)
    round_row.status = "closed"
    round_row.closed_at = datetime.utcnow()
    _audit_round(db, action="modeling_round.close", round_row=round_row,
                 changes={"closed_by": str(actor_id)})
    return round_row
