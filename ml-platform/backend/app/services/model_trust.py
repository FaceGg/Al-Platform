"""Model trust score / CBPE / model card v2 / sample explanation (S4, B2-04)."""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from app.models.audit_qa import ModelTrustScore

# 七因子权重（B2-04；和 = 1.0）
FACTOR_WEIGHTS = {
    "evaluation_sample_size": 0.18,
    "primary_metric_level": 0.25,
    "champion_stability": 0.15,
    "leakage_check": 0.15,
    "data_freshness": 0.10,
    "release_checks_coverage": 0.09,
    "blind_coverage": 0.08,
}
GRADE_BOUNDS = {"A": 85.0, "B": 70.0, "C": 55.0}


class TrustError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _metrics_of(version) -> dict:
    return dict(getattr(version, "metrics", None) or {})


def compute_trust_score(
    db: Session, *, project_id, version, computed_by_id=None
) -> ModelTrustScore:
    """七因子加权 0–100 → A(≥85)/B(≥70)/C(≥55)/D；硬门禁=主指标缺失或
    泄漏命中 → 直接 D（B2-04）。落历史（趋势）。"""
    metrics = _metrics_of(version)
    conversion = getattr(version, "conversion_metadata", None) or {}
    task_kind = str(conversion.get("task") or metrics.get("task") or "classification")
    is_anomaly = task_kind in {"anomaly", "anomaly_detection"}
    primary_key = "synthetic_auc" if is_anomaly else "f1"

    factors: dict[str, dict] = {}
    total = 0.0
    hard_fail = False

    # 1) 评估样本量（metrics 里登记的评估行数；缺省给中性 50）
    sample_size = int(metrics.get("evaluation_rows") or metrics.get("minority_test_count") or 0)
    sample_score = 100.0 if sample_size >= 5000 else (
        80.0 if sample_size >= 1000 else (60.0 if sample_size >= 300 else (40.0 if sample_size > 0 else 0.0))
    )
    factors["evaluation_sample_size"] = {"raw": sample_size, "score": sample_score}
    total += FACTOR_WEIGHTS["evaluation_sample_size"] * sample_score

    # 2) 主指标水平
    primary = metrics.get(primary_key)
    if primary is None:
        primary_score = 0.0
        hard_fail = True
    else:
        value = float(primary)
        primary_score = min(100.0, max(0.0, value * 100.0))
    factors["primary_metric_level"] = {"key": primary_key, "value": primary, "score": primary_score}
    total += FACTOR_WEIGHTS["primary_metric_level"] * primary_score

    # 3) 冠军稳定度（topk 方差小=稳；缺省中性 60）
    variance = metrics.get("topk_variance")
    if variance is None:
        stability_score = 60.0
    else:
        stability_score = max(0.0, 100.0 - float(variance) * 5000.0)
    factors["champion_stability"] = {"variance": variance, "score": round(stability_score, 2)}
    total += FACTOR_WEIGHTS["champion_stability"] * stability_score

    # 4) 泄漏检查（metrics 登记的泄漏命中）
    leakage_hits = int(metrics.get("leakage_hits") or 0)
    leakage_score = 100.0 if leakage_hits == 0 else 0.0
    if leakage_hits > 0:
        hard_fail = True
    factors["leakage_check"] = {"hits": leakage_hits, "score": leakage_score}
    total += FACTOR_WEIGHTS["leakage_check"] * leakage_score

    # 5) 数据新鲜度（版本距今 ≤30 天满分，线性衰减到 180 天 0 分）
    created_at = getattr(version, "created_at", None)
    if created_at is None:
        freshness_score = 50.0
    else:
        age_days = max(0.0, (datetime.utcnow() - created_at).total_seconds() / 86400)
        freshness_score = max(0.0, 100.0 * (1.0 - max(0.0, age_days - 30) / 150.0))
    factors["data_freshness"] = {"age_days": round(age_days, 1) if created_at else None,
                                 "score": round(freshness_score, 2)}
    total += FACTOR_WEIGHTS["data_freshness"] * freshness_score

    # 6) 发布检查覆盖（release_checks 有记录 → 满分；无 → 40）
    from app.models.release_governance import ReleaseCheck

    checks = db.query(ReleaseCheck).limit(5).all()
    coverage_score = 100.0 if checks else 40.0
    factors["release_checks_coverage"] = {"records": len(checks), "score": coverage_score}
    total += FACTOR_WEIGHTS["release_checks_coverage"] * coverage_score

    # 7) 盲测覆盖（S2a 台账有使用 → 满分；无 → 40）
    from app.models.dataset_splitting import BlindTestUsage

    blind_usages = db.query(BlindTestUsage).limit(5).all()
    blind_score = 100.0 if blind_usages else 40.0
    factors["blind_coverage"] = {"usages": len(blind_usages), "score": blind_score}
    total += FACTOR_WEIGHTS["blind_coverage"] * blind_score

    score = round(total, 2)
    if hard_fail:
        score = min(score, 40.0)
    grade = "D"
    for grade_key, bound in ({"A": 85.0, "B": 70.0, "C": 55.0}).items():
        if score >= bound:
            grade = grade_key
            break
    row = ModelTrustScore(
        model_version_id=version.id, project_id=project_id,
        score=score, grade=grade, factors=factors,
        computed_by_id=computed_by_id,
    )
    db.add(row)
    db.flush()
    return row


def estimate_cbpe(db: Session, *, deployment) -> dict:
    """CBPE（置信度法性能估计）：近窗 online 推理明细的概率列估计 accuracy
    与类平衡加权指标 + 正态近似置信区间。脚注强制（口径诚实）。"""
    from sqlalchemy import func, select

    from app.models.inference_result import InferenceResult

    rows = (
        db.query(InferenceResult)
        .filter(
            InferenceResult.deployment_id == deployment.id,
            InferenceResult.channel == "online",
            InferenceResult.probability.isnot(None),
        )
        .order_by(InferenceResult.occurred_at.desc())
        .limit(2000)
        .all()
    )
    if len(rows) < 30:
        return {
            "estimated": False,
            "reason": "insufficient_probability_rows",
            "rows": len(rows),
            "footnote": "CBPE 为估计口径非实测；概率校准是前提（竞品脚注照抄）",
        }
    probabilities = np.array([float(row.probability) for row in rows])
    estimated_accuracy = float(np.mean(probabilities))
    std = float(np.std(probabilities) / math.sqrt(len(probabilities)))
    ci_low = max(0.0, estimated_accuracy - 1.96 * std)
    ci_high = min(1.0, estimated_accuracy + 1.96 * std)
    positive_rate = float(np.mean([p >= 0.5 for p in probabilities]))
    return {
        "estimated": True,
        "rows": len(rows),
        "estimated_accuracy": round(estimated_accuracy, 4),
        "accuracy_ci": [round(ci_low, 4), round(ci_high, 4)],
        "estimated_positive_rate": round(positive_rate, 4),
        "footnote": "CBPE 为估计口径非实测（由预测概率估计）；概率校准是前提",
    }


CARD_SECTIONS = (
    "概述", "训练数据", "评估", "预期用途", "局限", "运维指引",
    "公平性与偏差", "可解释性", "已知失效模式", "变更记录", "签署",
)


def build_card_sections(db: Session, *, version) -> dict:
    """模型卡 11 章节（C6 在 ModelCard 骨架上扩展）：由血缘+metrics+
    release_checks+盲测台账填充；缺失=「未提供」如实标注。"""
    metrics = _metrics_of(version)
    conversion = getattr(version, "conversion_metadata", None) or {}
    primary_key = "synthetic_auc" if str(conversion.get("task") or metrics.get("task") or "classification") in {"anomaly", "anomaly_detection"} else "f1"
    sections = {
        "概述": f"模型版本 v{version.version_number}（{conversion.get('task') or 'classification'}）",
        "训练数据": (
            f"数据集版本 {conversion.get('dataset_version_id') or '未提供'}；"
            f"特征数 {len(version.feature_schema or [])}"
        ),
        "评估": json_metrics_summary(metrics, primary_key),
        "预期用途": getattr(version, "intended_use", None) or "未提供（建议在模型卡运维指导中补充）",
        "局限": getattr(version, "limitations", None) or "未提供",
        "运维指引": getattr(version, "ops_guidance", None) or "未提供",
        "公平性与偏差": "未提供（评估集类分布与少数类召回见评估章节）",
        "可解释性": (
            "特征重要性见评估产物（importance 键）"
            if metrics.get("importance") else "未提供"
        ),
        "已知失效模式": "未提供",
        "变更记录": f"卡构建于 {datetime.utcnow().isoformat(timespec='seconds')}Z",
        "签署": (
            f"审批状态 {version.approval_status}（审批历史见版本记录）"
        ),
    }
    return {key: sections[key] for key in CARD_SECTIONS}


def json_metrics_summary(metrics: dict, primary_key: str) -> str:
    parts = []
    primary = metrics.get(primary_key)
    if primary is not None:
        parts.append(f"{primary_key}={float(primary):.4f}")
    for key in ("recall_minority", "auc", "accuracy", "normal_fpr", "stability"):
        value = metrics.get(key)
        if value is not None:
            parts.append(f"{key}={value if isinstance(value, str) else round(float(value), 4)}")
    return "；".join(parts) or "未提供"


def data_fingerprint_of_version(version) -> str:
    conversion = getattr(version, "conversion_metadata", None) or {}
    import hashlib
    import json as _json

    return hashlib.sha256(
        _json.dumps({
            "dataset_version_id": conversion.get("dataset_version_id"),
            "feature_schema": list(getattr(version, "feature_schema", None) or []),
        }, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def explain_sample(db: Session, *, version, project_id=None, row: dict, feature_columns: list) -> dict:
    """单样本解释：feature_importances_ × 标准化值方向（口径脚注：重要性×
    偏离近似，非 SHAP）。

    三批复审同族修复：曾用 `version.registered_model_id`（registered_models.id
    外键）查 ModelLibrary——键型错配致真实链路恒 EXPLAIN_BUNDLE_MISSING；
    工件解析统一走 `_load_candidate_bundle`（source_model_library_id + 按项目）。"""
    from app.services.release_governance import _load_candidate_bundle

    bundle = _load_candidate_bundle(db, version.id, project_id=project_id)
    importances = getattr(bundle, "feature_importances_", None)
    if importances is None and hasattr(bundle, "coef_"):
        importances = np.abs(np.array(bundle.coef_).ravel())
    if importances is None:
        raise TrustError("EXPLAIN_NO_IMPORTANCE")
    importances = np.array(importances, dtype=float)
    width = min(len(importances), len(feature_columns))
    contributions = []
    for index in range(width):
        column = feature_columns[index]
        raw_value = row.get(column)
        if raw_value is None:
            continue
        value = float(raw_value)
        magnitude = float(importances[index]) * abs(value)
        contributions.append({
            "feature": column,
            "value": value,
            "importance": round(float(importances[index]), 6),
            "direction": "up" if value >= 0 else "down",
            "magnitude": round(magnitude, 6),
        })
    contributions.sort(key=lambda item: -item["magnitude"])
    return {
        "contributions": contributions[:10],
        "footnote": "解释口径：特征重要性 × 特征值绝对值（近似贡献方向与大小，非 SHAP）",
    }