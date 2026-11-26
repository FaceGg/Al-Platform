"""Label consistency: Kappa rounds / arbitration / purity gate / quality gate (S3, B2-06/E15).

并行一致性通道（§12.13）：逐标注员盲标经独立通道提交（门户共享单通道零
改动）；Cohen's κ 逐对+平均；分歧自动进仲裁队列；仲裁终审写回规范通道
（经既有 save_labels，仲裁人≠盲标人强制）；整簇纯度门禁；标签质量门。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from app.models.label_quality import (
    AnnotationBlindLabel,
    ConsistencyRound,
    LabelArbitration,
)

# 标签质量门阈值（E15）：κ 平均低于该值时训练创建被停
DEFAULT_KAPPA_GATE = 0.6
# 整簇纯度门禁（B2-06）：纯度 ≥0.8 且规模 ≥10 才可整簇提交
CLUSTER_PURITY_FLOOR = 0.8
CLUSTER_SIZE_FLOOR = 10


class ConsistencyError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def cohen_kappa(a: list, b: list) -> float:
    """Cohen's κ（单列；多列按列算后平均）。"""
    if len(a) != len(b) or not a:
        raise ConsistencyError("KAPPA_LENGTH_MISMATCH")
    pairs = [(str(x), str(y)) for x, y in zip(a, b)]
    observed = sum(1 for x, y in pairs if x == y) / len(pairs)
    a_counts: dict[str, int] = {}
    b_counts: dict[str, int] = {}
    for x, y in pairs:
        a_counts[x] = a_counts.get(x, 0) + 1
        b_counts[y] = b_counts.get(y, 0 + 1)
    total = len(pairs)
    expected = sum(
        (a_counts.get(label, 0) / total) * (b_counts.get(label, 0) / total)
        for label in set(a_counts) | set(b_counts)
    )
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def open_round(
    db: Session,
    *,
    project_id,
    annotator_subject_ids: list,
    sample_ids: list,
    task_id=None,
    label_schema_id=None,
    kappa_threshold: float = DEFAULT_KAPPA_GATE,
    created_by_id=None,
) -> ConsistencyRound:
    if len(annotator_subject_ids) < 2:
        raise ConsistencyError("CONSISTENCY_ROUND_NEEDS_TWO_ANNOTATORS")
    if not sample_ids:
        raise ConsistencyError("CONSISTENCY_ROUND_SAMPLES_REQUIRED")
    round_row = ConsistencyRound(
        project_id=project_id, task_id=task_id,
        label_schema_id=label_schema_id,
        annotator_subject_ids=[str(s) for s in annotator_subject_ids],
        sample_ids=[str(s) for s in sample_ids],
        status="open", kappa_threshold=float(kappa_threshold),
        created_by_id=created_by_id,
    )
    db.add(round_row)
    db.flush()
    return round_row


def submit_blind_label(
    db: Session, *, round_id, subject_id: str, sample_id: str, values: dict,
) -> AnnotationBlindLabel:
    """盲标提交（round 成员 + 样本在轮内才可提交；每样本每标注员一票）。"""
    round_row = db.get(ConsistencyRound, round_id)
    if round_row is None:
        raise ConsistencyError("CONSISTENCY_ROUND_NOT_FOUND")
    if str(subject_id) not in [str(s) for s in round_row.annotator_subject_ids]:
        raise ConsistencyError("BLIND_LABEL_SUBJECT_NOT_IN_ROUND")
    if str(sample_id) not in [str(s) for s in round_row.sample_ids]:
        raise ConsistencyError("BLIND_LABEL_SAMPLE_NOT_IN_ROUND")
    existing = (
        db.query(AnnotationBlindLabel)
        .filter(
            AnnotationBlindLabel.round_id == round_id,
            AnnotationBlindLabel.subject_id == str(subject_id),
            AnnotationBlindLabel.sample_id == str(sample_id),
        )
        .first()
    )
    if existing is not None:
        raise ConsistencyError("BLIND_LABEL_ALREADY_SUBMITTED")
    row = AnnotationBlindLabel(
        round_id=round_id, subject_id=str(subject_id),
        sample_id=str(sample_id), values=values or {},
    )
    db.add(row)
    db.flush()
    return row


def compute_kappa(db: Session, *, round_id) -> ConsistencyRound:
    """逐对 Cohen's κ + 平均；分歧样本自动进仲裁队列。"""
    round_row = db.get(ConsistencyRound, round_id)
    if round_row is None:
        raise ConsistencyError("CONSISTENCY_ROUND_NOT_FOUND")
    labels = (
        db.query(AnnotationBlindLabel)
        .filter(AnnotationBlindLabel.round_id == round_id)
        .all()
    )
    subjects = [str(s) for s in round_row.annotator_subject_ids]
    samples = [str(s) for s in round_row.sample_ids]
    lookup = {
        (row.subject_id, row.sample_id): row.values
        for row in labels
    }
    pairwise: dict[str, float] = {}
    disagreement_samples: set[str] = set()
    for i in range(len(subjects)):
        for j in range(i + 1, len(subjects)):
            a_values, b_values = [], []
            for sample in samples:
                va = (lookup.get((subjects[i], sample)) or {}).get("label")
                vb = (lookup.get((subjects[j], sample)) or {}).get("label")
                if va is None or vb is None:
                    continue
                a_values.append(va)
                b_values.append(vb)
            if len(a_values) < 2:
                pairwise[f"{subjects[i]}|{subjects[j]}"] = None
                continue
            kappa = cohen_kappa(a_values, b_values)
            pairwise[f"{subjects[i]}|{subjects[j]}"] = round(kappa, 4)
            disagreement_samples.update(
                sample for sample in samples
                if (lookup.get((subjects[i], sample)) or {}).get("label") is not None
                and (lookup.get((subjects[j], sample)) or {}).get("label") is not None
                and str((lookup.get((subjects[i], sample)) or {}).get("label"))
                != str((lookup.get((subjects[j], sample)) or {}).get("label"))
            )
    valid = [v for v in pairwise.values() if v is not None]
    average = round(sum(valid) / len(valid), 4) if valid else None
    round_row.kappa_pairwise = pairwise
    round_row.kappa_average = average
    if round_row.status == "open":
        round_row.status = "completed"
    for sample in sorted(disagreement_samples):
        existing = (
            db.query(LabelArbitration)
            .filter(
                LabelArbitration.round_id == round_id,
                LabelArbitration.sample_id == sample,
                LabelArbitration.status == "pending",
            )
            .first()
        )
        if existing is None:
            db.add(LabelArbitration(
                round_id=round_id, sample_id=sample,
                conflict={
                    str(subject): (lookup.get((str(subject), sample)) or {}).get("label")
                    for subject in subjects
                },
            ))
    db.flush()
    return round_row


def decide_arbitration(
    db: Session, *, arbitration_id, arbiter_id, decision_values: dict,
    note: str | None = None,
) -> LabelArbitration:
    """仲裁终审：终审值由调用方经既有 save_labels 写回规范通道；仲裁人≠盲标人。"""
    arbitration = db.get(LabelArbitration, arbitration_id)
    if arbitration is None:
        raise ConsistencyError("ARBITRATION_NOT_FOUND")
    if arbitration.status == "decided":
        raise ConsistencyError("ARBITRATION_STATE_CONFLICT")
    round_row = db.get(ConsistencyRound, arbitration.round_id)
    blind_subjects = {
        str(row.subject_id)
        for row in db.query(AnnotationBlindLabel)
        .filter(
            AnnotationBlindLabel.round_id == arbitration.round_id,
            AnnotationBlindLabel.sample_id == arbitration.sample_id,
        )
        .all()
    }
    if str(arbiter_id) in blind_subjects:
        raise ConsistencyError("ARBITER_SAME_AS_BLIND_ANNOTATOR")
    arbitration.decision_values = decision_values or {}
    arbitration.decision_note = (note or "")[:256] or None
    arbitration.arbiter_id = arbiter_id
    arbitration.status = "decided"
    arbitration.decided_at = datetime.utcnow()
    if round_row is not None:
        pending = (
            db.query(LabelArbitration)
            .filter(
                LabelArbitration.round_id == round_row.id,
                LabelArbitration.status == "pending",
            )
            .count()
        )
        if pending == 0:
            round_row.status = "arbitrated"
    db.flush()
    return arbitration


def cluster_purity(db: Session, *, strategy_artifact_id, cluster_id) -> dict:
    """簇纯度与规模（B2-06 整簇门禁）：主标签占比。"""
    from app.models.labeling import AnnotationStrategyDecision

    rows = (
        db.query(AnnotationStrategyDecision)
        .filter(AnnotationStrategyDecision.strategy_artifact_id == strategy_artifact_id)
        .all()
    )
    cluster_rows = [
        row for row in rows
        if str(getattr(row, "cluster_id", "")) == str(cluster_id)
        and getattr(row, "values", None)
    ]
    labeled = [
        row for row in cluster_rows
        if any(bool(v) or str(v).strip() for v in (row.values or {}).values())
    ]
    if not labeled:
        return {"cluster_id": str(cluster_id), "size": len(cluster_rows),
                "purity": None, "dominant": None}
    counts: dict[str, int] = {}
    for row in labeled:
        first_key = sorted((row.values or {}).items(), key=lambda kv: str(kv[0]))[0]
        counts[str(first_key[1])] = counts.get(str(first_key[1]), 0) + 1
    dominant, dominant_count = max(counts.items(), key=lambda kv: kv[1])
    return {
        "cluster_id": str(cluster_id), "size": len(cluster_rows),
        "purity": dominant_count / len(labeled), "dominant": dominant,
    }


def validate_cluster_submission(db: Session, *, strategy_artifact_id, cluster_id) -> dict:
    """整簇提交门禁：纯度 ≥0.8 且规模 ≥10；不满足 → CLUSTER_PURITY_BELOW_GATE。"""
    stats = cluster_purity(
        db, strategy_artifact_id=strategy_artifact_id, cluster_id=cluster_id
    )
    if (stats.get("purity") or 0) < CLUSTER_PURITY_FLOOR or (
        stats.get("size") or 0
    ) < CLUSTER_SIZE_FLOOR:
        raise ConsistencyError("CLUSTER_PURITY_BELOW_GATE")
    return stats


def cluster_view_samples(db: Session, *, strategy_artifact_id, cluster_id,
                         representatives: int = 5, boundary: int = 5,
                         deviants: int = 5) -> dict:
    """分群三类视图（代表/边界/偏离）：按簇内行序分段（零新计算基建）。"""
    from app.models.labeling import AnnotationStrategyDecision

    rows = (
        db.query(AnnotationStrategyDecision)
        .filter(AnnotationStrategyDecision.strategy_artifact_id == strategy_artifact_id)
        .all()
    )
    member_rows = [
        row for row in rows
        if str(getattr(row, "cluster_id", "")) == str(cluster_id)
    ]
    ordered = [str(row.sample_id) for row in member_rows]
    quarter = len(ordered) // 4
    return {
        "representatives": ordered[: max(1, representatives)],
        "boundary": ordered[quarter:quarter + max(1, boundary)],
        "deviants": ordered[-min(len(ordered), max(1, deviants)):],
    }


def label_quality_gate(db: Session, *, project_id) -> dict:
    """E15 质量门：最近一致性轮 κ 平均 < 阈值 → 训练创建被停并给出疑似数量。"""
    round_row = (
        db.query(ConsistencyRound)
        .filter(
            ConsistencyRound.project_id == project_id,
            ConsistencyRound.status.in_(("completed", "arbitrated")),
        )
        .order_by(ConsistencyRound.created_at.desc())
        .first()
    )
    if round_row is None or round_row.kappa_average is None:
        return {"stopped": False}
    if round_row.kappa_average < round_row.kappa_threshold:
        return {
            "stopped": True,
            "kappa_average": round_row.kappa_average,
            "kappa_threshold": round_row.kappa_threshold,
            "round_id": str(round_row.id),
            "pending_arbitrations": (
                db.query(LabelArbitration)
                .filter(
                    LabelArbitration.round_id == round_row.id,
                    LabelArbitration.status == "pending",
                )
                .count()
            ),
        }
    return {"stopped": False, "kappa_average": round_row.kappa_average}