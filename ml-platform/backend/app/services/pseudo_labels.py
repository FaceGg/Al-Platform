"""Pseudo-label batches with quota / down-weight / comparison / credentials (S3, B2-G4).

红线：伪标签永不进开发验证与独立盲测（比较臂只用原始/人工确认标签）；
每类按已标真值数量限量；样本降权（weight=置信度映射）；加权结果通过开发
验证比较后才被选用；凭证（样本/生成模型/置信度/权重）可导出。
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.models.label_quality import PseudoLabelBatch


class PseudoLabelError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _fingerprint(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def generate_pseudo_batch(
    db: Session,
    *,
    project_id,
    dataset_version_id,
    model_version_id,
    bundle,
    frame: pd.DataFrame,
    feature_columns: list,
    label_column: str,
    threshold: float = 0.9,
    quota_multiplier: float = 1.0,
    labeled_counts: dict | None = None,
    created_by_id=None,
) -> PseudoLabelBatch:
    """生成伪标签候选：置信度 ≥ threshold + 每类限量（按已标真值类数×倍数）
    + 降权（weight = 置信度平方映射——高置信样本主导）。"""
    if not hasattr(bundle, "predict_proba"):
        raise PseudoLabelError("PSEUDO_REQUIRES_PROBA")
    matrix = frame[feature_columns].to_numpy()
    proba = bundle.predict_proba(matrix)
    classes = list(bundle.classes_)
    confidence = np.max(proba, axis=1)
    argmax = np.argmax(proba, axis=1)
    labeled_counts = dict(labeled_counts or {})
    per_class_quota = {
        str(label): max(1, int(int(labeled_counts.get(str(label), 0)) * float(quota_multiplier)))
        for label in classes
    }
    used_per_class: dict[str, int] = {}
    selected = []
    for row_index in np.argsort(-confidence):
        label = str(classes[argmax[row_index]])
        score = float(confidence[row_index])
        if score < float(threshold):
            break
        if used_per_class.get(label, 0) >= per_class_quota.get(label, 0):
            continue
        used_per_class[label] = used_per_class.get(label, 0) + 1
        selected.append({
            "row_index": int(row_index),
            "sample_key": str(frame.iloc[row_index].get("sample_key") or f"row-{row_index}"),
            "label": label,
            "confidence": round(score, 6),
            "weight": round(score * score, 6),
            "training_fold": "pseudo",
        })
    batch = PseudoLabelBatch(
        project_id=project_id,
        dataset_version_id=dataset_version_id,
        model_version_id=model_version_id,
        threshold=float(threshold),
        per_class_quota=per_class_quota,
        selected=selected,
        winner=0,
        credential_fingerprint=_fingerprint(selected),
        created_by_id=created_by_id,
    )
    db.add(batch)
    db.flush()
    return batch


def compare_on_dev_validation(
    db: Session, *, batch_id,
    baseline_metrics: dict, weighted_metrics: dict,
) -> PseudoLabelBatch:
    """开发验证比较：加权臂 vs 不加权臂（同验证集、只用原始/人工确认标签）。
    未胜出 → winner=0（不选用）。"""
    batch = db.get(PseudoLabelBatch, batch_id)
    if batch is None:
        raise PseudoLabelError("PSEUDO_BATCH_NOT_FOUND")
    primary = "f1"
    weighted_score = float(weighted_metrics.get(primary) or 0.0)
    baseline_score = float(baseline_metrics.get(primary) or 0.0)
    batch.dev_comparison = {
        "primary": primary,
        "baseline": baseline_metrics,
        "weighted": weighted_metrics,
        "verdict": "weighted_wins" if weighted_score > baseline_score else "baseline_wins",
    }
    batch.winner = 1 if weighted_score > baseline_score else 0
    db.flush()
    return batch


def credential_rows(batch: PseudoLabelBatch) -> list:
    """凭证行（样本/生成模型/训练折/置信度/权重——与库内一致）。"""
    return [
        {
            "sample_key": item.get("sample_key"),
            "model_version_id": str(batch.model_version_id) if batch.model_version_id else None,
            "training_fold": item.get("training_fold"),
            "confidence": item.get("confidence"),
            "weight": item.get("weight"),
            "label": item.get("label"),
        }
        for item in (batch.selected or [])
    ]


def record_pseudo_batch_from_candidates(
    db: Session,
    *,
    project_id,
    dataset_version_id=None,
    model_version_id=None,
    candidates: list,
    threshold: float = 0.9,
    quota_multiplier: float = 1.0,
    labeled_counts: dict | None = None,
    created_by_id=None,
) -> PseudoLabelBatch:
    """从调用方已打分候选直录伪标签批（阈值过滤 + 每类限量 + 降权 + 凭证）。"""
    labeled_counts = dict(labeled_counts or {})
    per_class_quota: dict[str, int] = {}
    used_per_class: dict[str, int] = {}
    selected = []
    ordered = sorted(
        [c for c in candidates if c.get("confidence") is not None],
        key=lambda c: -float(c["confidence"]),
    )
    for item in ordered:
        label = str(item.get("label"))
        confidence = float(item["confidence"])
        if confidence < float(threshold):
            break
        if label not in per_class_quota:
            per_class_quota[label] = max(
                1, int(int(labeled_counts.get(label, 0)) * float(quota_multiplier))
            )
        if used_per_class.get(label, 0) >= per_class_quota[label]:
            continue
        used_per_class[label] = used_per_class.get(label, 0) + 1
        selected.append({
            "sample_key": str(item.get("sample_key") or item.get("row_index")),
            "label": label,
            "confidence": round(confidence, 6),
            "weight": round(confidence * confidence, 6),
            "training_fold": "pseudo",
        })
    batch = PseudoLabelBatch(
        project_id=project_id,
        dataset_version_id=dataset_version_id,
        model_version_id=model_version_id,
        threshold=float(threshold),
        per_class_quota=per_class_quota,
        selected=selected,
        winner=0,
        credential_fingerprint=_fingerprint(selected),
        created_by_id=created_by_id,
    )
    db.add(batch)
    db.flush()
    return batch
