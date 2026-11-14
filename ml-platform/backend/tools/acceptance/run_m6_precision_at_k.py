"""M6 半监督精调档 1 验收证据（技术方案 §6.4 二期总验收 判据② / §6.2 验收）。

判据②三项（方案 §6.2 验收行原文）：
1. precision@k（k=报警预算）较一期标定提升；
2. 合成基准重跑必须仍全过门禁（防精调过拟合确认样本）；
3. false_alarm 样本分数分布显著下移。

机制复用（只读引用，不改实现）：
- ``optimal_threshold_from_labels``（标签阈值重标定，漏报罚 2×误报）
- ``meets_m6_gate`` / ``confirmed_morphology_clusters`` / ``false_alarm_morphology_report``
- ``build_synthetic_benchmark`` / ``AnomalyScoreCalibrator`` / ``evaluate_anomaly_candidate``
  / ``evaluate_anomaly_gates`` / ``pipeline_anomaly_scores``

**诚实边界**：默认使用确定性合成发生器造数（confirmed_fault / false_alarm /
正常背景三类），此时运行模式为 ``mechanism-verification``——**只证明机制在
合成标签上成立**，**§6.2 真实门槛（confirmed_fault ≥50 条真实确认故障且覆盖
≥2 种真实异常形态）不予解锁**（平台当前真实标签数 0，见 DEVELOPMENT_PLAN
「2026-11-12 二期开工」M6 顺延登记）。``--data`` 指向带 ``feedback`` 列的
回流标签集（feedback=confirmed_fault/false_alarm，其余行按正常背景）时，
模式升级为 ``real-labels``；此时 §6.2 门槛判定按该标签集给出，但数据来源
仍由调用方用 ``--data-provenance`` 声明（脚本不校验来源，默认 unknown）。

用法（在 ml-platform/backend 下）::

    .venv/Scripts/python.exe tools/acceptance/run_m6_precision_at_k.py \
        --output ../docs/验收-M6-precision@k.json \
        --markdown ../docs/验收-M6-precision@k.md

    # 真实标签回流集（real-labels 模式）
    .venv/Scripts/python.exe tools/acceptance/run_m6_precision_at_k.py \
        --data "C:/path/reflow_labeled.csv" --label-column feedback \
        --data-provenance production-real
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.anomaly_threshold_recalibration import (  # noqa: E402
    confirmed_morphology_clusters,
    false_alarm_morphology_report,
    meets_m6_gate,
    optimal_threshold_from_labels,
)
from app.services.automl_anomaly import (  # noqa: E402
    ANOMALY_HOLDOUT_RATIO,
    AnomalyScoreCalibrator,
    build_synthetic_benchmark,
    evaluate_anomaly_candidate,
    evaluate_anomaly_gates,
    pipeline_anomaly_scores,
)
from app.services.automl_catalog import get_algorithm_family  # noqa: E402
from app.console_encoding import force_utf8_stdio  # noqa: E402

# 产物落**可跟踪**目录：仓库根 docs/ 被 .gitignore 排除（/docs/），证据不入库
# 会让已提交的验收文档链接失效——2026-11-13 审计同款问题。
DEFAULT_JSON_OUTPUT = BACKEND_ROOT.parent / "docs" / "验收-M6-precision@k.json"
DEFAULT_MD_OUTPUT = BACKEND_ROOT.parent / "docs" / "验收-M6-precision@k.md"

MODE_MECHANISM = "mechanism-verification"
MODE_REAL = "real-labels"

PRECISION_AT_K_DEFINITION = (
    "报警预算口径 precision@k：报警集合 A(t)={score≥t}；操作员处置预算 k 条，"
    "按到达（时间）序取前 k 条处置，超预算部分被丢弃；"
    "precision = 处置批次中真故障（confirmed_fault）占比。"
    "该口径含阈值——阈值重标定可直接改善；"
    "纯排序口径（runner.py S4：混合池取分数前 k 名）阈值不变，另作对照列出。"
)


# --------------------------------------------------------------------------
# 数值小工具
# --------------------------------------------------------------------------
def _quantiles(values) -> dict:
    array = np.asarray(values, dtype=float)
    if array.size == 0:
        return {"count": 0}
    return {
        "count": int(array.size),
        "min": round(float(array.min()), 6),
        "q25": round(float(np.quantile(array, 0.25)), 6),
        "median": round(float(np.median(array)), 6),
        "q75": round(float(np.quantile(array, 0.75)), 6),
        "max": round(float(array.max()), 6),
        "mean": round(float(array.mean()), 6),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 6)


# --------------------------------------------------------------------------
# 合成发生器（默认自包含，无需外部 CSV）
# --------------------------------------------------------------------------
def _normal_rows(rng, n_rows: int, n_features: int, rho: float = 0.35) -> np.ndarray:
    """AR(1) 弱相关结构的正常样本（工业多参数弱共线工况的简化形态）。"""
    if n_rows <= 0:
        return np.empty((0, n_features), dtype=float)
    noise = rng.normal(size=(n_rows, n_features))
    matrix = np.empty_like(noise)
    matrix[:, 0] = noise[:, 0]
    scale = float(np.sqrt(1.0 - rho ** 2))
    for column in range(1, n_features):
        matrix[:, column] = rho * matrix[:, column - 1] + scale * noise[:, column]
    return matrix


def _fault_rows(
    fault_benchmark,
    model,
    confirmed_count: int,
    baseline_threshold: float,
) -> tuple[np.ndarray, dict[str, int]]:
    """确认故障类：**分数超基线阈值**的异常样本（现场口径一致）。

    只有触发过报警的样本才可能被现场确认/标注为 confirmed_fault，因此本类
    只取分数 ≥ 基线阈值的异常。形态优先级：uniform_outlier（完全越界，最强）
    → local_perturbation（轻微劣化，最难检出）→ combinatorial_anomaly（组合
    异常）；某形态供给不足时按优先级回补，仍不足则用低于基线阈值的异常按
    分数从高到低回补并**留痕**（below_baseline_threshold_backfill）。

    异常样本取自 **另一组随机种子**（seed+1000）的合成基准，与门禁评估所用
    的基准（seed）不是同一批样本——避免「在同一批确认样本上自证不破门禁」。
    """
    pools = [
        ("uniform_outlier", fault_benchmark.uniform_outliers, 0.40),
        ("local_perturbation", fault_benchmark.perturbations, 0.35),
        ("combinatorial_anomaly", fault_benchmark.combinatorial, 0.25),
    ]
    eligible: list[dict] = []
    for name, pool, weight in pools:
        scores = pipeline_anomaly_scores(model, pool)
        mask = scores >= baseline_threshold
        eligible.append({
            "name": name,
            "weight": weight,
            "rows": pool[mask],
            "below": pool[~mask],
            "below_scores": scores[~mask],
        })

    chosen: list[np.ndarray] = []
    counts: dict[str, int] = {}
    remaining = int(confirmed_count)
    for item in eligible:
        target = int(round(confirmed_count * item["weight"]))
        take = min(target, len(item["rows"]), remaining)
        if take > 0:
            chosen.append(item["rows"][:take])
            counts[item["name"]] = take
            remaining -= take
    for item in eligible:
        if remaining <= 0:
            break
        used = counts.get(item["name"], 0)
        extra = min(len(item["rows"]) - used, remaining)
        if extra > 0:
            chosen.append(item["rows"][used:used + extra])
            counts[item["name"]] = used + extra
            remaining -= extra
    if remaining > 0:
        below_pool = np.vstack([item["below"] for item in eligible])
        below_scores = np.concatenate([item["below_scores"] for item in eligible])
        order = np.argsort(-below_scores)
        take = int(min(remaining, len(order)))
        chosen.append(below_pool[order[:take]])
        counts["below_baseline_threshold_backfill"] = take
        remaining -= take
    return np.vstack(chosen), counts


def _collect_false_alarms(
    rng,
    model,
    baseline_threshold: float,
    count: int,
    n_features: int,
    *,
    chunk_rows: int = 2000,
    max_chunks: int = 30,
) -> np.ndarray:
    """收集「正常样本但分数超基线阈值」的样本（现场误报口径）。

    这些样本本身是**真正常样本**（与正常背景同一分布），只是落在正常域的
    极端尾部因而触发基线阈值——正是 §6.2 档 1 要压下去的对象。
    """
    if count <= 0:
        return np.empty((0, n_features), dtype=float)
    collected: list[np.ndarray] = []
    for _ in range(max_chunks):
        chunk = _normal_rows(rng, chunk_rows, n_features)
        scores = pipeline_anomaly_scores(model, chunk)
        above = chunk[scores >= baseline_threshold]
        if len(above):
            collected.append(above)
        if sum(len(item) for item in collected) >= count:
            break
    if not collected:
        return np.empty((0, n_features), dtype=float)
    pooled = np.vstack(collected)
    return pooled[:count]


# --------------------------------------------------------------------------
# 口径计算
# --------------------------------------------------------------------------
def precision_at_k(
    scores: np.ndarray,
    is_confirmed: np.ndarray,
    threshold: float,
    k: int,
) -> dict:
    """报警预算口径 precision@k（阈值敏感口径，见 PRECISION_AT_K_DEFINITION）。

    ``scores``/``is_confirmed`` 按到达（时间）序排列；报警集合 = score≥t；
    处置预算 k 条 → 取到达序前 k 条；precision = 其中真故障占比。
    """
    alarm_mask = np.asarray(scores, dtype=float) >= float(threshold)
    alarm_indexes = np.flatnonzero(alarm_mask)  # 升序 = 到达序
    processed = alarm_indexes[: max(int(k), 0)]
    confirmed = np.asarray(is_confirmed, dtype=bool)
    true_processed = int(confirmed[processed].sum()) if len(processed) else 0
    return {
        "threshold": round(float(threshold), 6),
        "alarm_count": int(len(alarm_indexes)),
        "alarm_budget_k": int(k),
        "budget_exceeded": bool(len(alarm_indexes) > k),
        "dropped_over_budget": int(max(len(alarm_indexes) - k, 0)),
        "processed_count": int(len(processed)),
        "true_fault_in_processed": true_processed,
        "precision": round(float(true_processed / len(processed)), 6) if len(processed) else None,
    }


def precision_at_k_ranking(scores: np.ndarray, is_confirmed: np.ndarray, k: int) -> dict:
    """纯排序口径对照（runner.py S4 定义）：混合池按分数降序取前 k。

    该口径**与阈值无关**（AUC/排序类指标），因此重标定前后必然相同——
    列出以证明「precision@k 提升」来自运行点（阈值）而非排序变化。
    """
    scores = np.asarray(scores, dtype=float)
    confirmed = np.asarray(is_confirmed, dtype=bool)
    order = np.argsort(-scores)
    top = order[: max(int(k), 0)]
    true_top = int(confirmed[top].sum()) if len(top) else 0
    return {
        "k": int(k),
        "top_count": int(len(top)),
        "true_fault_in_top": true_top,
        "precision": round(float(true_top / len(top)), 6) if len(top) else None,
        "threshold_invariant": True,
    }


# 门禁判定方向（方案 §3.3 第二层原文）：synthetic_auc / stability 为下限，
# normal_fpr 为上限。用于在平台实现出现 falsy-zero 误判时按真实值复算。
GATE_DIRECTION = {"synthetic_auc": "ge", "normal_fpr": "le", "stability": "ge"}


def _correct_gates(metrics: dict, gates: dict) -> tuple[dict, bool, dict | None]:
    """按真实指标值复核门禁，修正平台实现的 falsy-zero 误判。

    ``app/services/automl_anomaly.py::evaluate_anomaly_gates`` 用
    ``float(metrics.get("normal_fpr") or 1.0)`` 读取 normal_fpr——0.0 是
    falsy，会被读成 1.0（最差），于是「零误报」被误判成「门禁未过」。
    本函数只修正这一处读数（阈值仍取平台实现给出的阈值），并把差异留痕。
    """
    corrected: dict[str, dict] = {}
    defect: dict | None = None
    for name, item in ((gates.get("acceptance_gates") or {})).items():
        actual = metrics.get(name)
        if actual is not None and float(actual) != float(item["value"]):
            defect = {
                "gate": name,
                "platform_reported_value": item["value"],
                "actual_value": float(actual),
                "detail": (
                    "evaluate_anomaly_gates 用 `float(metrics.get('normal_fpr') or 1.0)` "
                    "读数——normal_fpr=0.0（falsy，零误报）被读成 1.0（最差），"
                    "导致该项门禁被误判为未过"
                ),
                "reference": "app/services/automl_anomaly.py::evaluate_anomaly_gates",
                "note": "平台既有实现缺陷，本次未修改该文件（不在本任务改动范围）",
            }
        if actual is None:
            corrected[name] = {
                "value": item["value"],
                "threshold": item["threshold"],
                "passed": bool(item["passed"]),
            }
            continue
        direction = GATE_DIRECTION.get(name)
        if direction == "ge":
            passed = float(actual) >= float(item["threshold"])
        elif direction == "le":
            passed = float(actual) <= float(item["threshold"])
        else:
            passed = bool(item["passed"])
        corrected[name] = {
            "value": float(actual),
            "threshold": item["threshold"],
            "passed": bool(passed),
        }
    return corrected, all(item["passed"] for item in corrected.values()), defect


def _metrics_at_threshold(
    *,
    threshold: float,
    contamination: float,
    holdout_scores: np.ndarray,
    uniform_scores: np.ndarray,
    perturbation_scores: np.ndarray,
    combinatorial_scores: np.ndarray,
    baseline_metrics: dict,
) -> dict:
    """在给定阈值下重算阈值相关指标（synthetic_auc / stability 与阈值无关，沿用基线值）。

    synthetic_auc = ROC AUC（分数序）、stability = Spearman（分数序）——二者由
    分数分布决定，与判定阈值无关，故重标定后取值不变（这正是「合成基准不破」
    的结构原因：档 1 不动检测器主体，方案 §6.2 硬约束）。
    """
    threshold = float(threshold)
    metrics = {
        "threshold_score": round(threshold, 6),
        "synthetic_auc": baseline_metrics.get("synthetic_auc"),
        "normal_fpr": round(float(np.mean(holdout_scores >= threshold)), 6),
        "perturbation_recall": round(float(np.mean(perturbation_scores >= threshold)), 6),
        "holdout_size": int(len(holdout_scores)),
        "stability": baseline_metrics.get("stability"),
        "detection_recall_per_class": {
            "uniform_outlier": (
                round(float(np.mean(uniform_scores >= threshold)), 6)
                if len(uniform_scores) else None
            ),
            "local_perturbation": (
                round(float(np.mean(perturbation_scores >= threshold)), 6)
                if len(perturbation_scores) else None
            ),
            "combinatorial_anomaly": (
                round(float(np.mean(combinatorial_scores >= threshold)), 6)
                if len(combinatorial_scores) else None
            ),
        },
    }
    gates = evaluate_anomaly_gates(metrics, contamination=contamination)
    metrics.update(gates)
    corrected, corrected_passed, defect = _correct_gates(metrics, gates)
    metrics["acceptance_gates_corrected"] = corrected
    metrics["gates_passed_corrected"] = corrected_passed
    metrics["platform_gate_defect"] = defect
    return metrics


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def run_acceptance(
    *,
    data_path: str | None = None,
    label_column: str = "feedback",
    feature_names: list[str] | None = None,
    data_provenance: str = "unknown",
    family_id: str = "iforest",
    model_params: dict | None = None,
    contamination: float = 0.01,
    seed: int = 42,
    train_rows: int = 800,
    confirmed_count: int = 60,
    false_alarm_count: int = 40,
    normal_count: int = 200,
    n_features: int = 6,
    alarm_budget: int | None = None,
    compute_stability: bool = True,
) -> dict:
    """跑一遍 M6 档 1 验收闭环，返回可直接落 JSON 的结果字典。

    只依赖只读机制（阈值搜索/门槛/合成基准/门禁均调用平台既有实现）。
    """
    np.random.seed(seed)
    rng = np.random.default_rng(seed)

    family = get_algorithm_family(family_id)
    params = dict(model_params) if model_params is not None else dict(family.default_params)
    # 同一估计器贯穿全程（预标定 → 误报样本收集 → 正式评估）：模型对象唯一，
    # 保证「误报样本是按同一基线阈值挑出来的」与「门禁重跑用同一模型」成立。
    model = family.build("anomaly_detection", params)

    # ---- 1. 数据装配 -----------------------------------------------------
    mode = MODE_MECHANISM
    data_note = ""
    if data_path:
        frame, columns, mode, data_note = _load_labeled_frame(
            data_path,
            label_column=label_column,
            feature_names=feature_names,
        )
        normal_pool = frame["normal"]
        confirmed_matrix = frame["confirmed"]
        false_alarm_matrix = frame["false_alarm"]
        names = columns
    else:
        total_rows = int(train_rows)
        holdout_size = max(1, int(total_rows * ANOMALY_HOLDOUT_RATIO))
        normal_matrix = _normal_rows(rng, total_rows, n_features)
        train_matrix = normal_matrix[:-holdout_size]
        holdout_matrix = normal_matrix[-holdout_size:]
        names = [f"f{index}" for index in range(n_features)]

        model.fit(train_matrix)
        prelim_holdout_scores = pipeline_anomaly_scores(model, holdout_matrix)
        prelim_threshold = float(
            AnomalyScoreCalibrator.fit(prelim_holdout_scores, contamination=contamination).threshold_score
        )
        # 门禁评估基准（seed）与确认故障类取样基准（seed+1000）分离：避免在
        # 同一批确认样本上自证「合成基准不破门禁」。
        gate_benchmark = build_synthetic_benchmark(
            train_matrix, holdout_matrix, random_seed=seed
        )
        fault_benchmark = build_synthetic_benchmark(
            train_matrix, holdout_matrix, random_seed=seed + 1000
        )
        confirmed_matrix, shape_counts = _fault_rows(
            fault_benchmark, model, confirmed_count, prelim_threshold
        )
        false_alarm_matrix = _collect_false_alarms(
            rng, model, prelim_threshold, false_alarm_count, n_features
        )
        background_matrix = _normal_rows(rng, normal_count, n_features)
        data_note = (
            "确定性合成发生器：AR(1) 弱相关正常样本；确认故障类取自独立随机种子"
            "（seed+1000）合成基准中**分数超基线阈值**的异常（现场口径：只有触发过"
            "报警的样本才可能被确认）；false_alarm 类为正常样本中分数超基线阈值者"
        )

    # ---- 2. 训练/保留集切分 ---------------------------------------------
    if data_path:
        normal_pool = np.asarray(normal_pool, dtype=float)
        if len(normal_pool) < 200:
            raise ValueError("AUTOML_ANOMALY_LABELED_NORMAL_POOL_TOO_SMALL")
        # 三段互斥切分：正常背景（评估用）/ 保留集（标定用）/ 训练集——
        # 背景行不得进训练集，否则背景误报率会被训练内样本压低。
        background_size = max(1, len(normal_pool) // 5)
        holdout_size = max(1, int(len(normal_pool) * ANOMALY_HOLDOUT_RATIO))
        background_matrix = normal_pool[:background_size]
        holdout_matrix = normal_pool[background_size:background_size + holdout_size]
        train_matrix = normal_pool[background_size + holdout_size:]
        if len(train_matrix) < 50:
            raise ValueError("AUTOML_ANOMALY_LABELED_TRAIN_ROWS_TOO_SMALL")
        shape_counts = {"from_labeled_dataset": int(len(confirmed_matrix))}

    confirmed_matrix = np.asarray(confirmed_matrix, dtype=float)
    false_alarm_matrix = np.asarray(false_alarm_matrix, dtype=float)
    background_matrix = np.asarray(background_matrix, dtype=float)

    # ---- 3. 拟合模型 + 一期基线标定 + 合成基准 --------------------------
    benchmark = gate_benchmark if not data_path else build_synthetic_benchmark(
        train_matrix, holdout_matrix, random_seed=seed
    )
    baseline_metrics = evaluate_anomaly_candidate(
        model,
        train_matrix,
        holdout_matrix,
        benchmark,
        contamination=contamination,
        random_seed=seed,
        compute_stability=compute_stability,
    )
    baseline_threshold = float(baseline_metrics["threshold_score"])

    holdout_scores = pipeline_anomaly_scores(model, holdout_matrix)
    uniform_scores = pipeline_anomaly_scores(model, benchmark.uniform_outliers)
    perturbation_scores = pipeline_anomaly_scores(model, benchmark.perturbations)
    combinatorial_scores = pipeline_anomaly_scores(model, benchmark.combinatorial)

    # ---- 4. 标签阈值重标定（档 1 核心，只动阈值） ----------------------
    confirmed_scores = pipeline_anomaly_scores(model, confirmed_matrix)
    false_alarm_scores = pipeline_anomaly_scores(model, false_alarm_matrix)
    recalibration = optimal_threshold_from_labels(confirmed_scores, false_alarm_scores)
    recalibrated_threshold = float(recalibration["threshold"])

    # ---- 5. 评估集打分（三类 + 到达序） --------------------------------
    evaluation_matrix = np.vstack([confirmed_matrix, false_alarm_matrix, background_matrix])
    confirmed_count_actual = len(confirmed_matrix)
    false_alarm_count_actual = len(false_alarm_matrix)
    background_count_actual = len(background_matrix)
    class_labels = np.array(
        ["confirmed_fault"] * confirmed_count_actual
        + ["false_alarm"] * false_alarm_count_actual
        + ["normal_background"] * background_count_actual,
        dtype=object,
    )
    is_confirmed = np.concatenate([
        np.ones(confirmed_count_actual, dtype=bool),
        np.zeros(false_alarm_count_actual + background_count_actual, dtype=bool),
    ])
    order_rng = np.random.default_rng(seed + 1)
    permutation = order_rng.permutation(len(evaluation_matrix))
    evaluation_matrix = evaluation_matrix[permutation]
    class_labels = class_labels[permutation]
    is_confirmed = is_confirmed[permutation]
    evaluation_scores = pipeline_anomaly_scores(model, evaluation_matrix)

    k = int(alarm_budget) if alarm_budget is not None else confirmed_count_actual
    before = precision_at_k(evaluation_scores, is_confirmed, baseline_threshold, k)
    after = precision_at_k(evaluation_scores, is_confirmed, recalibrated_threshold, k)
    ranking_control = precision_at_k_ranking(evaluation_scores, is_confirmed, k)

    # ---- 6. 合成基准门禁重跑（防精调过拟合确认样本） ------------------
    recalibrated_metrics = _metrics_at_threshold(
        threshold=recalibrated_threshold,
        contamination=contamination,
        holdout_scores=holdout_scores,
        uniform_scores=uniform_scores,
        perturbation_scores=perturbation_scores,
        combinatorial_scores=combinatorial_scores,
        baseline_metrics=baseline_metrics,
    )

    # ---- 7. 各类检出与 false_alarm 分布位移 ----------------------------
    def _class_scores(name: str) -> np.ndarray:
        return evaluation_scores[class_labels == name]

    confirmed_eval_scores = _class_scores("confirmed_fault")
    false_alarm_eval_scores = _class_scores("false_alarm")
    background_eval_scores = _class_scores("normal_background")

    false_alarm_alarm_before = false_alarm_eval_scores[false_alarm_eval_scores >= baseline_threshold]
    false_alarm_alarm_after = false_alarm_eval_scores[false_alarm_eval_scores >= recalibrated_threshold]
    margin_before = false_alarm_eval_scores - baseline_threshold
    margin_after = false_alarm_eval_scores - recalibrated_threshold
    background_alarm_before = int(np.sum(background_eval_scores >= baseline_threshold))
    background_alarm_after = int(np.sum(background_eval_scores >= recalibrated_threshold))

    false_alarm_shift = {
        "semantics": (
            "档 1 只动阈值不动检测器主体（§6.2 硬约束）→ 同一误报样本的**分数本身不变**，"
            "下移的是「分数相对阈值」的分布：阈值抬高 Δt 后全部误报样本的分数裕度"
            "（score − threshold）整体下移 Δt，且仍能触发报警的误报子集分数更低。"
        ),
        "threshold_delta": round(recalibrated_threshold - baseline_threshold, 6),
        "false_alarm_alarm_set_before": _quantiles(false_alarm_alarm_before),
        "false_alarm_alarm_set_after": _quantiles(false_alarm_alarm_after),
        "false_alarm_score_margin_before": _quantiles(margin_before),
        "false_alarm_score_margin_after": _quantiles(margin_after),
        "false_alarm_score_margin_median_shift": round(
            float(np.median(margin_after) - np.median(margin_before)), 6
        ),
        "normal_background_alarm_count": {
            "before": background_alarm_before,
            "after": background_alarm_after,
            "background_rows": background_count_actual,
        },
        "normal_background_alarm_rate": {
            "before": _rate(background_alarm_before, background_count_actual),
            "after": _rate(background_alarm_after, background_count_actual),
        },
        "shifted_down": bool(
            float(np.median(margin_after)) < float(np.median(margin_before))
            and background_alarm_after <= background_alarm_before
        ),
    }

    # ---- 8. §6.2 门槛（机制门槛 / 真实门槛分列） -----------------------
    morphology = confirmed_morphology_clusters(confirmed_matrix)
    mechanism_gate = meets_m6_gate(confirmed_count_actual, morphology.get("cluster_count"))
    morphology_report = false_alarm_morphology_report(false_alarm_matrix, names)

    if mode == MODE_REAL:
        real_gate = {
            "unlocked": bool(mechanism_gate["unlocked"]),
            "status": "unlocked" if mechanism_gate["unlocked"] else "not_unlocked",
            "confirmed_count": mechanism_gate["confirmed_count"],
            "morphology_cluster_count": mechanism_gate["morphology_cluster_count"],
            "min_confirmed_required": mechanism_gate["min_confirmed_required"],
            "provenance": data_provenance,
            "provenance_qualified": bool(data_provenance == "production-real"),
            "reason": (
                "标签来自 --data 提供的回流标签集（标签口径由调用方声明，脚本不校验数据来源；"
                f"声明 provenance={data_provenance}）"
            ),
        }
    else:
        real_gate = {
            "unlocked": False,
            "status": "not_unlocked",
            "confirmed_count": 0,
            "morphology_cluster_count": None,
            "min_confirmed_required": mechanism_gate["min_confirmed_required"],
            "reason": (
                "mechanism-verification 模式：本次标签为合成标签，不构成 §6.2 真实门槛证据；"
                "平台真实 confirmed_fault 标签数 0（DEVELOPMENT_PLAN「2026-11-12 二期开工」"
                "登记 M6 按 §6.2 自动顺延），真实门槛未解锁"
            ),
        }

    # ---- 9. 结论 --------------------------------------------------------
    precision_improved = bool(
        before["precision"] is not None
        and after["precision"] is not None
        and after["precision"] > before["precision"]
    )
    gates_passed = bool(recalibrated_metrics.get("gates_passed"))
    gates_passed_corrected = bool(recalibrated_metrics.get("gates_passed_corrected"))
    platform_gate_defect = recalibrated_metrics.get("platform_gate_defect")
    shifted_down = bool(false_alarm_shift["shifted_down"])
    mechanism_verified = bool(
        precision_improved and gates_passed_corrected and shifted_down
    )

    release_blockers: list[str] = []
    if mode != MODE_REAL:
        release_blockers.append("§6.2 真实标签门槛未解锁（平台真实 confirmed_fault 标签 0 条）")
    elif data_provenance != "production-real":
        release_blockers.append(
            f"标签集来源声明为 {data_provenance}（非产线实测）——机制验证结论不可作为对外发布依据"
        )

    result = {
        "date": date.today().isoformat(),
        "criterion": "§6.4 二期总验收 判据②（precision@k 提升 + 合成基准重跑不破门禁 + false_alarm 分布下移）",
        "mode": mode,
        "mode_detail": data_note,
        "honesty_notice": (
            "mechanism-verification 模式的数字只证明机制在合成标签上成立，"
            "不代表 §6.2 真实门槛（confirmed_fault ≥50 条真实确认故障 + ≥2 种真实异常形态）已满足；"
            "真实门槛状态见 m6_real_gate。"
            if mode == MODE_MECHANISM
            else (
                "real-labels 模式：标签来自 --data 提供的回流标签集；数据来源由调用方声明"
                f"（provenance={data_provenance}），脚本不校验来源——结论强度取决于该声明；"
                "§6.2 门槛状态见 m6_real_gate。"
            )
        ),
        "data": {
            "source": data_path or "deterministic-synthetic-generator",
            "data_path": data_path,
            "provenance": (
                "generator-synthetic" if mode == MODE_MECHANISM else data_provenance
            ),
            "seed": seed,
            "n_features": len(names),
            "feature_names": names,
            "train_rows": int(len(train_matrix)),
            "holdout_rows": int(len(holdout_matrix)),
            "evaluation_rows": int(len(evaluation_matrix)),
            "confirmed_rows": confirmed_count_actual,
            "false_alarm_rows": false_alarm_count_actual,
            "normal_background_rows": background_count_actual,
            "fault_shape_counts": shape_counts,
        },
        "model": {
            "family": family_id,
            "params": {key: value for key, value in params.items()},
            "holdout_ratio": ANOMALY_HOLDOUT_RATIO,
        },
        "contamination": round(float(contamination), 6),
        "alarm_budget_k": k,
        "thresholds": {
            "baseline_score": round(baseline_threshold, 6),
            "baseline_source": (
                "一期标定：AnomalyScoreCalibrator.fit(holdout_scores, contamination="
                f"{contamination}).threshold_score（保留集 (1-contamination) 分位）"
            ),
            "recalibrated_score": round(recalibrated_threshold, 6),
            "recalibrated_source": (
                "标签重标定：optimal_threshold_from_labels(confirmed_scores, false_alarm_scores)"
                "（漏报罚 2×误报，201 分位网格扫描）"
            ),
            "delta": round(recalibrated_threshold - baseline_threshold, 6),
            "recalibration_detail": recalibration,
        },
        "precision_at_k": {
            "definition": PRECISION_AT_K_DEFINITION,
            "k": k,
            "before": before,
            "after": after,
            "delta": (
                round(after["precision"] - before["precision"], 6)
                if before["precision"] is not None and after["precision"] is not None
                else None
            ),
            "improved": precision_improved,
        },
        "precision_at_k_ranking_control": {
            "definition": "纯排序口径（runner.py S4：混合池分数降序取前 k）——阈值不变，前后必然相同",
            **ranking_control,
        },
        "class_score_distributions": {
            "confirmed_fault": _quantiles(confirmed_eval_scores),
            "false_alarm": _quantiles(false_alarm_eval_scores),
            "normal_background": _quantiles(background_eval_scores),
        },
        "detection": {
            "confirmed_fault_detection_rate": {
                "before": _rate(
                    int(np.sum(confirmed_eval_scores >= baseline_threshold)),
                    confirmed_count_actual,
                ),
                "after": _rate(
                    int(np.sum(confirmed_eval_scores >= recalibrated_threshold)),
                    confirmed_count_actual,
                ),
            },
            "false_alarm_alarm_rate_on_false_alarm_class": {
                "before": _rate(
                    int(np.sum(false_alarm_eval_scores >= baseline_threshold)),
                    false_alarm_count_actual,
                ),
                "after": _rate(
                    int(np.sum(false_alarm_eval_scores >= recalibrated_threshold)),
                    false_alarm_count_actual,
                ),
            },
            "normal_background_alarm_rate": false_alarm_shift["normal_background_alarm_rate"],
        },
        "false_alarm_shift": false_alarm_shift,
        "synthetic_benchmark": {
            "note": (
                "synthetic_auc（ROC AUC）与 stability（Spearman）由分数排序决定、与判定阈值无关；"
                "normal_fpr / perturbation_recall 随阈值变化。重跑用同一模型、同一合成基准，"
                "只把判定阈值换成标签重标定阈值。"
            ),
            "baseline": {
                "threshold_score": round(baseline_threshold, 6),
                "synthetic_auc": baseline_metrics.get("synthetic_auc"),
                "normal_fpr": baseline_metrics.get("normal_fpr"),
                "stability": baseline_metrics.get("stability"),
                "perturbation_recall": baseline_metrics.get("perturbation_recall"),
                "acceptance_gates": baseline_metrics.get("acceptance_gates"),
                "gates_passed": baseline_metrics.get("gates_passed"),
            },
            "recalibrated": {
                "threshold_score": recalibrated_metrics["threshold_score"],
                "synthetic_auc": recalibrated_metrics.get("synthetic_auc"),
                "normal_fpr": recalibrated_metrics.get("normal_fpr"),
                "stability": recalibrated_metrics.get("stability"),
                "perturbation_recall": recalibrated_metrics.get("perturbation_recall"),
                "detection_recall_per_class": recalibrated_metrics.get("detection_recall_per_class"),
                "acceptance_gates": recalibrated_metrics.get("acceptance_gates"),
                "gates_passed": recalibrated_metrics.get("gates_passed"),
                "acceptance_gates_corrected": recalibrated_metrics.get("acceptance_gates_corrected"),
                "gates_passed_corrected": recalibrated_metrics.get("gates_passed_corrected"),
                "platform_gate_defect": platform_gate_defect,
            },
        },
        "m6_mechanism_gate": {
            "note": "合成/给定标签上跑 meets_m6_gate 的结果（机制门槛，非真实门槛）",
            **mechanism_gate,
        },
        "m6_real_gate": real_gate,
        "false_alarm_morphology_report": morphology_report,
        "verdict": {
            "precision_at_k_improved": precision_improved,
            "synthetic_benchmark_gates_still_pass": gates_passed_corrected,
            "synthetic_benchmark_gates_passed_platform_raw": gates_passed,
            "synthetic_benchmark_gates_note": (
                "门禁判定按真实 normal_fpr 复算（平台 evaluate_anomaly_gates 的 "
                "`or 1.0` 读数会把 normal_fpr=0.0 读成 1.0，详见 "
                "synthetic_benchmark.recalibrated.platform_gate_defect）"
                if platform_gate_defect
                else "门禁判定为平台 evaluate_anomaly_gates 原样输出"
            ),
            "false_alarm_distribution_shifted_down": shifted_down,
            "criterion_2_mechanism_verified": mechanism_verified,
            "criterion_2_release_ready": bool(
                mode == MODE_REAL
                and data_provenance == "production-real"
                and mechanism_verified
            ),
            "release_blockers": release_blockers,
        },
    }
    return result


def _load_labeled_frame(
    data_path: str,
    *,
    label_column: str,
    feature_names: list[str] | None,
) -> tuple[dict, list[str], str, str]:
    """读取回流标签集（real-labels 模式）。

    列约定：特征列 + 标签列（默认 ``feedback``）；标签值
    ``confirmed_fault`` / ``false_alarm`` / 空（或其它值=未标注正常背景）。
    """
    import pandas as pd

    frame = pd.read_csv(data_path)
    if label_column not in frame.columns:
        raise ValueError("AUTOML_ANOMALY_LABELED_COLUMN_MISSING")
    if feature_names:
        columns = [name for name in feature_names if name in frame.columns]
    else:
        columns = [
            name for name in frame.columns
            if name != label_column and pd.api.types.is_numeric_dtype(frame[name])
        ]
    if not columns:
        raise ValueError("AUTOML_ANOMALY_LABELED_NO_FEATURES")
    marks = frame[label_column].fillna("").astype(str).str.strip()
    matrix = frame.reindex(columns=columns).apply(pd.to_numeric, errors="coerce").dropna()
    marks = marks.loc[matrix.index]
    confirmed = matrix[marks == "confirmed_fault"].to_numpy(dtype=float)
    false_alarm = matrix[marks == "false_alarm"].to_numpy(dtype=float)
    normal = matrix[(marks != "confirmed_fault") & (marks != "false_alarm")].to_numpy(dtype=float)
    payload = {
        "normal": normal,
        "confirmed": confirmed,
        "false_alarm": false_alarm,
    }
    note = (
        f"回流标签集（{label_column} 列：confirmed_fault/false_alarm/未标注正常背景），"
        f"特征 {len(columns)} 列"
    )
    return payload, columns, MODE_REAL, note


# --------------------------------------------------------------------------
# Markdown 报告（与 JSON 同源，数字必然一致）
# --------------------------------------------------------------------------
def render_markdown(result: dict) -> str:
    thresholds = result["thresholds"]
    precision = result["precision_at_k"]
    before = precision["before"]
    after = precision["after"]
    benchmark = result["synthetic_benchmark"]
    base_gates = benchmark["baseline"]
    recal_gates = benchmark["recalibrated"]
    shift = result["false_alarm_shift"]
    detection = result["detection"]
    data = result["data"]
    real_gate = result["m6_real_gate"]
    mechanism_gate = result["m6_mechanism_gate"]
    verdict = result["verdict"]

    def _gate_rows(gates: dict) -> str:
        rows = []
        for name, item in (gates or {}).items():
            rows.append(
                f"| {name} | {item['value']} | {item['threshold']} | "
                f"{'通过' if item['passed'] else '未通过'} |"
            )
        return "\n".join(rows)

    lines = [
        "# 验收记录：M6 半监督精调档 1（技术方案 §6.4 判据②）",
        "",
        f"- 日期：{result['date']}",
        "- 方案：[技术方案-无监督弱监督异常检测.md](技术方案-无监督弱监督异常检测.md) §6.2 验收 / §6.4 二期总验收 判据②",
        f"- 结果数据：[验收-M6-precision@k.json](验收-M6-precision@k.json)",
        "- 可复现：`ml-platform/backend/tools/acceptance/run_m6_precision_at_k.py`",
        "  （在 `ml-platform/backend` 下：`.venv/Scripts/python.exe tools/acceptance/run_m6_precision_at_k.py`；"
        "默认写 `ml-platform/docs/验收-M6-precision@k.json` + `.md`；`--data <回流标签集.csv>` 进入 real-labels 模式）",
        f"- 运行模式：**{result['mode']}**",
        "",
        "## 0. 诚实边界（先读）",
        "",
        f"> {result['honesty_notice']}",
        "",
        f"- 数据来源：`{data['source']}`（provenance={data['provenance']}）",
        f"- §6.2 真实门槛状态：**{real_gate['status']}**（unlocked={real_gate['unlocked']}）——{real_gate['reason']}",
        f"- 机制门槛（{mechanism_gate.get('note')}）：unlocked={mechanism_gate['unlocked']}，"
        f"confirmed={mechanism_gate['confirmed_count']}/{mechanism_gate['min_confirmed_required']}，"
        f"形态簇={mechanism_gate['morphology_cluster_count']}",
        f"- 发布就绪：**{'是' if verdict['criterion_2_release_ready'] else '否'}**"
        + (f"（阻塞：{'；'.join(verdict['release_blockers'])}）" if verdict["release_blockers"] else ""),
        "",
        "## 1. 数据与模型",
        "",
        f"- 数据构造口径：{result['mode_detail']}",
        f"- 训练集 {data['train_rows']} 行 / 正常保留集 {data['holdout_rows']} 行"
        f"（holdout_ratio={result['model']['holdout_ratio']}）",
        f"- 评估集 {data['evaluation_rows']} 行 = confirmed_fault {data['confirmed_rows']}"
        f" + false_alarm {data['false_alarm_rows']} + 正常背景 {data['normal_background_rows']}",
        f"- 确认故障形态计数（取自独立种子 seed+{1000} 的合成基准）：{data['fault_shape_counts']}",
        f"- 模型：`{result['model']['family']}`，参数 {result['model']['params']}；contamination={result['contamination']}；seed={data['seed']}",
        "",
        "## 2. 阈值：一期标定 → 标签重标定",
        "",
        f"- 一期基线阈值 **{thresholds['baseline_score']}**（{thresholds['baseline_source']}）",
        f"- 标签重标定阈值 **{thresholds['recalibrated_score']}**（{thresholds['recalibrated_source']}）",
        f"- 阈值位移 Δ = **{thresholds['delta']}**",
        "",
        f"重标定细节：loss={thresholds['recalibration_detail']['loss']}、"
        f"fnr={thresholds['recalibration_detail']['fnr']}、"
        f"fpr={thresholds['recalibration_detail']['fpr']}、"
        f"confirmed={thresholds['recalibration_detail']['confirmed_count']}、"
        f"false_alarm={thresholds['recalibration_detail']['false_alarm_count']}",
        "",
        "## 3. 判据②之一：precision@k（k=报警预算）",
        "",
        f"口径：{precision['definition']}",
        "",
        "> 夹具前提（机制前提，真实标签下需由数据检验）：真故障样本的分数整体高于"
        "误报样本（正常样本超基线阈值者）——这正是 §6.2 档 1「用标签把阈值抬到"
        "误报带之上」成立的前提。",
        "",
        f"| 指标 | 一期基线阈值 | 标签重标定阈值 |",
        "|---|---|---|",
        f"| 阈值 | {before['threshold']} | {after['threshold']} |",
        f"| 报警数 | {before['alarm_count']} | {after['alarm_count']} |",
        f"| 报警预算 k | {before['alarm_budget_k']} | {after['alarm_budget_k']} |",
        f"| 超预算丢弃 | {before['dropped_over_budget']} | {after['dropped_over_budget']} |",
        f"| 处置批内真故障数 | {before['true_fault_in_processed']} | {after['true_fault_in_processed']} |",
        f"| **precision@k** | **{before['precision']}** | **{after['precision']}** |",
        "",
        f"- precision@k 提升：{'是' if precision['improved'] else '否'}（Δ={precision['delta']}）",
        f"- 纯排序口径对照（阈值不变）：{result['precision_at_k_ranking_control']['precision']}"
        f"（k={result['precision_at_k_ranking_control']['k']}）——提升来自运行点（阈值），不是排序变化",
        "",
        "### 各类检出",
        "",
        "| 口径 | 一期基线阈值 | 标签重标定阈值 |",
        "|---|---|---|",
        f"| confirmed_fault 检出率 | {detection['confirmed_fault_detection_rate']['before']} | {detection['confirmed_fault_detection_rate']['after']} |",
        f"| false_alarm 类报警率 | {detection['false_alarm_alarm_rate_on_false_alarm_class']['before']} | {detection['false_alarm_alarm_rate_on_false_alarm_class']['after']} |",
        f"| 正常背景误报率 | {detection['normal_background_alarm_rate']['before']} | {detection['normal_background_alarm_rate']['after']} |",
        "",
        "## 4. 判据②之二：合成基准重跑（防精调过拟合确认样本）",
        "",
        f"> {benchmark['note']}",
        "",
        "| 指标 | 一期基线阈值 | 标签重标定阈值 |",
        "|---|---|---|",
        f"| synthetic_auc（≥0.85） | {base_gates['synthetic_auc']} | {recal_gates['synthetic_auc']} |",
        f"| normal_fpr（≤contamination×1.5） | {base_gates['normal_fpr']} | {recal_gates['normal_fpr']} |",
        f"| stability（≥0.8） | {base_gates['stability']} | {recal_gates['stability']} |",
        f"| perturbation_recall | {base_gates['perturbation_recall']} | {recal_gates['perturbation_recall']} |",
        f"| **gates_passed** | **{base_gates['gates_passed']}** | **{recal_gates.get('gates_passed_corrected')}**（平台原样输出 {recal_gates['gates_passed']}）|",
        "",
        f"重标定后门禁明细（按真实 normal_fpr 复算）：\n\n| 门禁 | 值 | 阈值 | 结论 |\n|---|---|---|---|\n{_gate_rows(recal_gates.get('acceptance_gates_corrected'))}",
        "",
        f"- 平台原样输出 gates_passed = **{recal_gates['gates_passed']}**；"
        f"按真实指标值复算 gates_passed = **{recal_gates.get('gates_passed_corrected')}**",
        "",
    ]
    defect = recal_gates.get("platform_gate_defect")
    if defect:
        lines.extend([
            "> **平台实现缺陷（如实登记，本次未修改被点名文件）**",
            ">",
            f"> - 门禁项：`{defect['gate']}`；平台报数 {defect['platform_reported_value']}，"
            f"真实值 {defect['actual_value']}",
            f"> - 原因：{defect['detail']}",
            f"> - 位置：{defect['reference']}；{defect['note']}",
            "> - 影响面：仅当 normal_fpr **恰好为 0.0** 时触发（falsy→1.0）；"
            "本次为「零误报」被判未过，真实门禁结论应为通过。",
            "",
        ])
    lines.extend([
        "## 5. 判据②之三：false_alarm 分数分布下移",
        "",
        f"> {shift['semantics']}",
        "",
        f"- 阈值位移 Δt = **{shift['threshold_delta']}**",
        f"- 误报类分数裕度中位数：{shift['false_alarm_score_margin_before']['median']}"
        f" → {shift['false_alarm_score_margin_after']['median']}"
        f"（位移 {shift['false_alarm_score_margin_median_shift']}）",
        f"- 仍能触发报警的误报子集：{shift['false_alarm_alarm_set_before']['count']} 条"
        f"（中位分 {shift['false_alarm_alarm_set_before']['median']}）"
        f" → {shift['false_alarm_alarm_set_after']['count']} 条"
        f"（中位分 {shift['false_alarm_alarm_set_after']['median']}）",
        f"- 正常背景误报：{shift['normal_background_alarm_count']['before']}"
        f"/{shift['normal_background_alarm_count']['background_rows']}"
        f" → {shift['normal_background_alarm_count']['after']}"
        f"/{shift['normal_background_alarm_count']['background_rows']} 条",
        f"- 分布显著下移：**{'是' if shift['shifted_down'] else '否'}**",
        "",
        "## 6. 结论",
        "",
        f"- precision@k 提升：**{'是' if verdict['precision_at_k_improved'] else '否'}**",
        f"- 合成基准重跑仍全过门禁：**{'是' if verdict['synthetic_benchmark_gates_still_pass'] else '否'}**"
        f"（{verdict.get('synthetic_benchmark_gates_note', '')}）",
        f"- false_alarm 分数分布显著下移：**{'是' if verdict['false_alarm_distribution_shifted_down'] else '否'}**",
        f"- 判据②机制验证（{result['mode']}）：**{'通过' if verdict['criterion_2_mechanism_verified'] else '未通过'}**",
        f"- 判据②发布就绪：**{'是' if verdict['criterion_2_release_ready'] else '否'}**",
        "",
        "## 7. 附加产出：误报形态分析报表（§6.2）",
        "",
        "```json",
        json.dumps(result["false_alarm_morphology_report"], ensure_ascii=False, indent=2),
        "```",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    # Windows 管道 stdout 默认用 locale 代码页（cp1252），中文 print 会抛
    # UnicodeEncodeError —— 统一切 UTF-8（见 app/console_encoding.py）。
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        default="",
        help="回流标签集 CSV（含 feedback 列）；缺省用确定性合成发生器",
    )
    parser.add_argument("--label-column", default="feedback")
    parser.add_argument(
        "--data-provenance",
        default="unknown",
        choices=["production-real", "generator-synthetic", "unknown"],
        help=(
            "数据来源声明（仅 --data 模式有意义）：production-real=产线实测回流标签集；"
            "generator-synthetic=生成器产物；unknown=来源不明（不可用于对外结论）"
        ),
    )
    parser.add_argument("--features", default="", help="逗号分隔特征列；缺省取全部数值列")
    parser.add_argument("--family", default="iforest", choices=["iforest", "ocsvm"])
    parser.add_argument("--contamination", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-rows", type=int, default=800)
    parser.add_argument("--confirmed", type=int, default=60)
    parser.add_argument("--false-alarm", type=int, default=40)
    parser.add_argument("--normal", type=int, default=200)
    parser.add_argument("--features-count", type=int, default=6)
    parser.add_argument("--alarm-budget", type=int, default=0, help="0 = 取 confirmed 数（默认报警预算）")
    parser.add_argument("--skip-stability", action="store_true")
    parser.add_argument("--output", default=str(DEFAULT_JSON_OUTPUT))
    parser.add_argument("--markdown", default=str(DEFAULT_MD_OUTPUT))
    args = parser.parse_args()

    feature_names = [name.strip() for name in args.features.split(",") if name.strip()] or None
    result = run_acceptance(
        data_path=args.data or None,
        label_column=args.label_column,
        feature_names=feature_names,
        data_provenance=args.data_provenance,
        family_id=args.family,
        contamination=args.contamination,
        seed=args.seed,
        train_rows=args.train_rows,
        confirmed_count=args.confirmed,
        false_alarm_count=args.false_alarm,
        normal_count=args.normal,
        n_features=args.features_count,
        alarm_budget=args.alarm_budget or None,
        compute_stability=not args.skip_stability,
    )

    json_path = Path(args.output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path = Path(args.markdown)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"saved: {json_path}")
    print(f"saved: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
