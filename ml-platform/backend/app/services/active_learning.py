"""Active learning sample selection (补齐路线第二批 S3, B2-05).

九策略：entropy / margin / least_confidence（不确定性族，读 predict_proba）、
cluster_diversity（聚类感知配额）、boundary（簇内边界带）、rarity（特征密度
尾部）、diversity（core-set 贪心最远点）、business_priority（业务优先级字段）、
random（基线）；hybrid 按权重混合出样（预算截断）+ 命中统计。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.models.label_quality import ACTIVE_LEARNING_STRATEGIES, ActiveLearningSelection


class SelectionError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _probabilities(bundle, frame: pd.DataFrame, feature_columns: list[str]) -> np.ndarray:
    matrix = frame[feature_columns].to_numpy()
    if hasattr(bundle, "predict_proba"):
        return bundle.predict_proba(matrix)
    raise SelectionError("SELECTION_REQUIRES_PROBA")


def _score_entropy(proba: np.ndarray) -> np.ndarray:
    eps = 1e-12
    return -np.sum(proba * np.log(proba + eps), axis=1)


def _score_margin(proba: np.ndarray) -> np.ndarray:
    part = np.sort(proba, axis=1)
    return 1.0 - (part[:, -1] - part[:, -2] if proba.shape[1] >= 2 else part[:, -1])


def _score_least_confidence(proba: np.ndarray) -> np.ndarray:
    return 1.0 - np.max(proba, axis=1)


def _rank_take(scores: np.ndarray, budget: int) -> list[int]:
    order = np.argsort(-scores)[: max(0, int(budget))]
    return [int(index) for index in order]


def _cluster_diversity_indices(frame: pd.DataFrame, cluster_column: str, budget: int) -> list[int]:
    if cluster_column not in frame.columns:
        raise SelectionError("SELECTION_CLUSTER_COLUMN_REQUIRED")
    per_cluster = max(1, budget // max(1, frame[cluster_column].nunique()))
    chosen: list[int] = []
    for _, group in frame.groupby(cluster_column, sort=False):
        chosen.extend(group.index.tolist()[:per_cluster])
        if len(chosen) >= budget:
            break
    return chosen[:budget]


def _boundary_indices(frame: pd.DataFrame, cluster_column: str, budget: int) -> list[int]:
    """簇内边界带：样本到本簇规模的归一秩中位带（零新基建，用簇内序次近似）。"""
    if cluster_column not in frame.columns:
        raise SelectionError("SELECTION_CLUSTER_COLUMN_REQUIRED")
    chosen: list[int] = []
    per_band = max(1, budget // max(1, frame[cluster_column].nunique()))
    for _, group in frame.groupby(cluster_column, sort=False):
        start = len(group) // 4
        band = group.index[start:start + per_band]
        chosen.extend(band.tolist())
    return chosen[:budget]


def _rarity_indices(frame: pd.DataFrame, feature_columns: list[str], budget: int) -> list[int]:
    matrix = frame[feature_columns].to_numpy(dtype=float)
    density_order = np.argsort(np.linalg.norm(matrix - matrix.mean(axis=0), axis=1))
    return [int(density_order[-i]) for i in range(1, min(budget, len(frame)) + 1)][::-1]


def _diversity_indices(frame: pd.DataFrame, feature_columns: list[str], budget: int) -> list[int]:
    """core-set 贪心最远点。"""
    matrix = frame[feature_columns].to_numpy(dtype=float)
    if len(matrix) == 0:
        return []
    chosen = [int(np.argmax(np.linalg.norm(matrix - matrix.mean(axis=0), axis=1)))]
    while len(chosen) < min(budget, len(matrix)):
        distances = np.min(
            np.linalg.norm(matrix[:, None, :] - matrix[None, chosen, :], axis=2), axis=1
        )
        chosen.append(int(np.argmax(distances)))
    return chosen


def _business_indices(frame: pd.DataFrame, priority_column: str, budget: int) -> list[int]:
    if priority_column not in frame.columns:
        raise SelectionError("SELECTION_PRIORITY_COLUMN_REQUIRED")
    ordered = frame[priority_column].sort_values(ascending=False).index.tolist()
    return [int(index) for index in ordered[:budget]]


def select_samples(
    *,
    bundle,
    frame: pd.DataFrame,
    feature_columns: list[str],
    strategy: dict,
    budget_initial: int,
    budget_per_round: int,
) -> tuple[list[int], dict]:
    """按策略出选样行号 + 命中统计。strategy 形如
    {"name": "entropy"} 或 {"name": "hybrid", "weights": {"entropy": 0.6, ...}}
    + 可选 cluster_column / priority_column。"""
    name = str(strategy.get("name") or "entropy")
    if name not in ACTIVE_LEARNING_STRATEGIES:
        raise SelectionError("SELECTION_STRATEGY_INVALID")
    budget = int(budget_per_round or budget_initial)
    if budget <= 0:
        raise SelectionError("SELECTION_BUDGET_INVALID")
    stats: dict[str, list[int]] = {}
    if name == "hybrid":
        weights = dict(strategy.get("weights") or {})
        if not weights:
            raise SelectionError("SELECTION_HYBRID_WEIGHTS_REQUIRED")
        proba = _probabilities(bundle, frame, feature_columns)
        scorers = {
            "entropy": lambda: _score_entropy(proba),
            "margin": lambda: _score_margin(proba),
            "least_confidence": lambda: _score_least_confidence(proba),
            "random": lambda: np.random.RandomState(42).rand(len(frame)),
        }
        quota_total = 0
        per_strategy_quota: dict[str, int] = {}
        for key, weight in weights.items():
            share = int(round(budget * float(weight)))
            per_strategy_quota[key] = share
            quota_total += share
        picked: set[int] = set()
        for key, share in per_strategy_quota.items():
            if key in scorers:
                picks = _rank_take(scorers[key](), share)
            elif key == "cluster_diversity":
                picks = _cluster_diversity_indices(
                    frame, str(strategy.get("cluster_column") or "cluster"), share
                )
            elif key == "diversity":
                picks = _diversity_indices(frame, feature_columns, share)
            else:
                raise SelectionError("SELECTION_HYBRID_STRATEGY_UNKNOWN")
            fresh = [p for p in picks if p not in picked]
            picked.update(fresh)
            stats[key] = fresh
        selected = list(picked)[:budget]
        return selected, {key: len(value) for key, value in stats.items()}

    if name in {"entropy", "margin", "least_confidence"}:
        proba = _probabilities(bundle, frame, feature_columns)
        scorer = {"entropy": _score_entropy, "margin": _score_margin,
                  "least_confidence": _score_least_confidence}[name]
        selected = _rank_take(scorer(proba), budget)
        stats = {name: len(selected)}
    elif name == "cluster_diversity":
        selected = _cluster_diversity_indices(
            frame, str(strategy.get("cluster_column") or "cluster"), budget
        )
        stats = {name: len(selected)}
    elif name == "boundary":
        selected = _boundary_indices(
            frame, str(strategy.get("cluster_column") or "cluster"), budget
        )
        stats = {name: len(selected)}
    elif name == "rarity":
        selected = _rarity_indices(frame, feature_columns, budget)
        stats = {name: len(selected)}
    elif name == "diversity":
        selected = _diversity_indices(frame, feature_columns, budget)
        stats = {name: len(selected)}
    elif name == "business_priority":
        selected = _business_indices(
            frame, str(strategy.get("priority_column") or "priority"), budget
        )
        stats = {name: len(selected)}
    else:  # random
        rng = np.random.RandomState(int(strategy.get("seed") or 42))
        selected = [int(i) for i in rng.choice(len(frame), size=min(budget, len(frame)), replace=False)]
        stats = {name: len(selected)}
    return selected, stats


def record_selection(
    db: Session,
    *,
    project_id,
    model_version_id,
    strategy: dict,
    budget_initial: int,
    budget_per_round: int,
    selected_sample_ids: list,
    strategy_stats: dict,
    created_by_id=None,
) -> ActiveLearningSelection:
    fingerprint = hashlib.sha256(
        json.dumps({"selected": selected_sample_ids, "strategy": strategy},
                   sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    row = ActiveLearningSelection(
        project_id=project_id,
        model_version_id=model_version_id,
        strategy=strategy,
        budget_initial=int(budget_initial),
        budget_per_round=int(budget_per_round),
        selected_sample_ids=selected_sample_ids,
        strategy_stats=strategy_stats,
        fingerprint=fingerprint,
        created_by_id=created_by_id,
    )
    db.add(row)
    db.flush()
    return row
