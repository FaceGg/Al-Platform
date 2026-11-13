"""无监督异常检测引擎核心（anomaly_detection 任务专用）。

三层评估体系的第一层（训练期合成异常注入基准）与管线强制结构的
分数标定/阈值策略都在本模块：监督链路零依赖本文件，这是范式互斥
（技术方案 §2.1）的结构性保证之一。

统一分数口径：``anomaly score 越高越异常``。IsolationForest 的
``score_samples`` 与 OneClassSVM 的 ``decision_function`` 语义都是
「越正越正常」，因此一律取负后进入标定与阈值判定。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.stats import spearmanr
from sklearn.base import clone
from sklearn.metrics import roc_auc_score

ANOMALY_TASK_TYPE = "anomaly_detection"
ANOMALY_DEFAULT_CONTAMINATION = 0.01
# 方案 §3.1：无监督行数下限（正常样本海量，低于此值建模无意义）。
ANOMALY_MIN_ROWS = 200
# 工况分段护栏（方案 §6.3/§6.6E）：每工况段 ≥200 行才独立训练，不足段并入
# 默认段——与 M1 fpr 统计容差的 Binomial 教训一致，小样本分片的 fpr 门禁
# 会随机挂（一期 trainer 过渡形态曾用 ≥100，M7 挂载时统一）。
ANOMALY_SEGMENT_MIN_ROWS = 200
ANOMALY_HOLDOUT_RATIO = 0.2
# 每类合成异常的注入数量上限：与保留集 1:1 但封顶，控制大表评估耗时。
ANOMALY_BENCHMARK_PER_CLASS_CAP = 2000
# 局部扰动的 σ 倍数：1.5σ 保持「轻微劣化、最难形态」定位且具备可分性。
ANOMALY_PERTURBATION_SIGMA = 1.5
ANOMALY_STABILITY_SUBSAMPLES = 5
ANOMALY_STABILITY_SAMPLE_RATIO = 0.8
# OC-SVM 训练成本随样本量平方级增长：>2 万行自动降采样（沿用 UMAP 路径既定策略）。
ANOMALY_OCSVM_MAX_TRAIN_ROWS = 20000
# 方案 §3.3 第二层默认验收门禁（M1 引擎侧冠军资格；S4 可配置在 M2 接入）。
ANOMALY_ACCEPTANCE_SYNTHETIC_AUC = 0.85
ANOMALY_ACCEPTANCE_STABILITY = 0.8
ANOMALY_ACCEPTANCE_FPR_TOLERANCE = 1.5  # normal_fpr ≤ contamination × 1.5


def normalize_anomaly_contamination(value) -> float:
    """预期异常比例先验：缺省 0.01（宁低勿高），合法域 (0, 0.5]。"""
    if value is None:
        return ANOMALY_DEFAULT_CONTAMINATION
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("AUTOML_ANOMALY_CONTAMINATION_INVALID")
    contamination = float(value)
    if not 0.0 < contamination <= 0.5:
        raise ValueError("AUTOML_ANOMALY_CONTAMINATION_INVALID")
    return contamination


def pipeline_anomaly_scores(pipeline, matrix) -> np.ndarray:
    """对拟合后的管线/估计器统一计算「越高越异常」的离群分数。

    前置变换（Imputer/Scaler）逐级 transform，末级检测器按
    ``score_samples``（IF）或 ``decision_function``（OC-SVM）取负。
    """
    transformed = np.asarray(matrix, dtype=float)
    steps = list(getattr(pipeline, "steps", []) or [])
    if steps:
        for _, step in steps[:-1]:
            transformed = step.transform(transformed)
        detector = steps[-1][1]
    else:
        detector = pipeline
    if hasattr(detector, "score_samples"):
        return -np.asarray(detector.score_samples(transformed), dtype=float)
    if hasattr(detector, "decision_function"):
        return -np.asarray(detector.decision_function(transformed), dtype=float)
    raise ValueError("AUTOML_ANOMALY_SCORE_UNAVAILABLE")


@dataclass(frozen=True)
class SyntheticBenchmark:
    """保留集（全部正常）+ 三类合成异常，评估全程共用同一基准。"""

    holdout_matrix: np.ndarray
    uniform_outliers: np.ndarray
    perturbations: np.ndarray
    combinatorial: np.ndarray

    @property
    def synthetic_matrix(self) -> np.ndarray:
        return np.vstack([self.uniform_outliers, self.perturbations, self.combinatorial])

    @property
    def synthetic_class_sizes(self) -> dict[str, int]:
        return {
            "uniform_outlier": int(len(self.uniform_outliers)),
            "local_perturbation": int(len(self.perturbations)),
            "combinatorial_anomaly": int(len(self.combinatorial)),
        }


def _column_fences(train_matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """每列的 Tukey 1.5×IQR 围栏（「单变量合理范围」的定义）。

    IQR=0（常数列）时以 std 兜底；引擎执行层已剔除常数列，此兜底
    仅服务直接调用基准构建的单测路径。
    """
    q1 = np.quantile(train_matrix, 0.25, axis=0)
    q3 = np.quantile(train_matrix, 0.75, axis=0)
    iqr = q3 - q1
    fallback = np.maximum(np.std(train_matrix, axis=0), 1e-9)
    width = np.where(iqr > 0, iqr, fallback)
    return q1 - 1.5 * width, q3 + 1.5 * width


def _build_uniform_outliers(train_matrix: np.ndarray, count: int, rng) -> np.ndarray:
    """均匀流形外点：每维取包围盒外侧（lo−1.5×IQR, lo) 或 (hi, hi+1.5×IQR]，完全偏离正常域。"""
    if count <= 0:
        return np.empty((0, train_matrix.shape[1]), dtype=float)
    lower, upper = _column_fences(train_matrix)
    lo_ext = np.min(train_matrix, axis=0) - 1.5 * (upper - lower)
    hi_ext = np.max(train_matrix, axis=0) + 1.5 * (upper - lower)
    low_side = rng.random((count, train_matrix.shape[1])) < 0.5
    samples = np.empty((count, train_matrix.shape[1]), dtype=float)
    # 逐列区间采样（外点必须落在包围盒之外）。
    for column in range(train_matrix.shape[1]):
        below = rng.uniform(lo_ext[column], min(lower[column], np.min(train_matrix[:, column])), size=count)
        above = rng.uniform(max(upper[column], np.max(train_matrix[:, column])), hi_ext[column], size=count)
        samples[:, column] = np.where(low_side[:, column], below, above)
    return samples


def _build_perturbations(holdout_matrix: np.ndarray, train_matrix: np.ndarray, count: int, rng,
                         sigma_multiplier: float | None = None) -> np.ndarray:
    """局部扰动点：保留集样本 ±kσ 高斯扰动（轻微劣化形态，最难检出）。

    ``sigma_multiplier`` 缺省用基准主强度（ANOMALY_PERTURBATION_SIGMA）；
    强度-检出率曲线（§3.3 第二层 S4 证据）按多档倍率扫描。
    """
    if count <= 0:
        return np.empty((0, holdout_matrix.shape[1]), dtype=float)
    multiplier = float(sigma_multiplier) if sigma_multiplier is not None else ANOMALY_PERTURBATION_SIGMA
    rows = rng.integers(0, len(holdout_matrix), size=count)
    sigma = np.std(train_matrix, axis=0)
    noise = rng.normal(size=(count, holdout_matrix.shape[1])) * np.where(sigma > 0, sigma, 0.0)
    return holdout_matrix[rows] + multiplier * noise


def _build_combinatorial_anomalies(holdout_matrix: np.ndarray, train_matrix: np.ndarray, count: int, rng) -> np.ndarray:
    """单变量合理组合异常（降误报核心场景）。

    分位错配构造：随机锚列取该列高分位值（85%-98%），其余列取各自
    低分位值（2%-15%，方向随机反转以增多样性）——每个单指标都深居
    Tukey 1.5×IQR 围栏内的「合理范围」，但组合落在相关数据从不经过的
    「盒角」密度空洞（工况语义：A 参数高、其余参数低的不合理联动）。
    轴平行切分（IF）与距离模型（OC-SVM）对此均敏感。已否决两版：
    行内列替换（边缘随机采样，联合密度不变，AUC≈0.55）与整行镜像
    （相关列对整体反演保留相关结构，AUC≈0.55）。
    """
    if count <= 0:
        return np.empty((0, holdout_matrix.shape[1]), dtype=float)
    n_features = holdout_matrix.shape[1]
    if n_features < 2:
        # 单特征没有「组合」可言：退化为围栏边缘值。
        lower, upper = _column_fences(train_matrix)
        return rng.uniform(lower, upper, size=(count, n_features))
    source = np.asarray(train_matrix, dtype=float)
    samples = np.empty((count, n_features), dtype=float)
    for index in range(count):
        anchor = int(rng.integers(0, n_features))
        anchor_high = bool(rng.random() < 0.5)
        for column in range(n_features):
            values = source[:, column]
            if anchor_high:
                quantile = rng.uniform(0.85, 0.98) if column == anchor else rng.uniform(0.02, 0.15)
            else:
                quantile = rng.uniform(0.02, 0.15) if column == anchor else rng.uniform(0.85, 0.98)
            samples[index, column] = float(np.quantile(values, quantile))
    return samples


def build_synthetic_benchmark(
    train_matrix: np.ndarray,
    holdout_matrix: np.ndarray,
    *,
    random_seed: int = 42,
) -> SyntheticBenchmark:
    """构建训练期合成异常基准（三类注入，覆盖工业异常典型形态）。"""
    if len(train_matrix) < 2 or len(holdout_matrix) < 1:
        raise ValueError("AUTOML_ANOMALY_BENCHMARK_INVALID")
    per_class = min(len(holdout_matrix), ANOMALY_BENCHMARK_PER_CLASS_CAP)
    rng = np.random.default_rng(random_seed)
    return SyntheticBenchmark(
        holdout_matrix=np.asarray(holdout_matrix, dtype=float),
        uniform_outliers=_build_uniform_outliers(np.asarray(train_matrix, dtype=float), per_class, rng),
        perturbations=_build_perturbations(np.asarray(holdout_matrix, dtype=float), np.asarray(train_matrix, dtype=float), per_class, rng),
        combinatorial=_build_combinatorial_anomalies(np.asarray(holdout_matrix, dtype=float), np.asarray(train_matrix, dtype=float), per_class, rng),
    )


@dataclass(frozen=True)
class AnomalyScoreCalibrator:
    """训练期经验分位数标定：原始分数 → [0, 1]（经验百分位）。

    阈值随模型持久化（非推理时重算）：``threshold_score`` 是标定集
    （训练流程内 held-out 正常保留集）分数的 ``(1 - contamination)``
    分位数，换模对比与误报统计都以「上线时标定阈值」为锚（技术方案
    §3.2）；标定集不用拟合数据本身，避免 in-sample 分数压低推高误报。
    """

    quantile_points: np.ndarray
    quantile_probabilities: np.ndarray
    threshold_score: float
    contamination: float

    @classmethod
    def fit(cls, train_scores: np.ndarray, *, contamination: float) -> "AnomalyScoreCalibrator":
        scores = np.asarray(train_scores, dtype=float)
        probabilities = np.linspace(0.0, 1.0, 201)
        points = np.quantile(scores, probabilities)
        threshold = float(np.quantile(scores, 1.0 - contamination))
        return cls(
            quantile_points=points,
            quantile_probabilities=probabilities,
            threshold_score=threshold,
            contamination=float(contamination),
        )

    def transform(self, scores: np.ndarray) -> np.ndarray:
        """原始分数映射到 [0, 1] 经验百分位（线性插值）。"""
        return np.interp(np.asarray(scores, dtype=float), self.quantile_points, self.quantile_probabilities)

    @property
    def calibrated_threshold(self) -> float:
        return 1.0 - self.contamination


def score_histogram(scores: np.ndarray, *, bins: int = 30) -> dict[str, list[float]]:
    """分数直方图（S4 证据面板的双峰性可视化数据）。"""
    values = np.asarray(scores, dtype=float)
    counts, edges = np.histogram(values, bins=bins)
    return {"bin_edges": [float(value) for value in edges], "counts": [int(value) for value in counts]}


def stability_check(
    fitted_estimator,
    train_matrix: np.ndarray,
    evaluation_matrix: np.ndarray,
    *,
    random_seed: int = 42,
    n_subsamples: int = ANOMALY_STABILITY_SUBSAMPLES,
) -> float:
    """子采样重训稳定性：与全量拟合模型的分数排序做 Spearman 相关。

    无监督不稳定 = 上线误报失控的头号原因（方案 §3.3），因此 5 次
    80% 子采样重训的分数必须与基准模型排序一致（均值 Spearman）。
    任何一次重训失败或分数退化（常数向量）按 0.0 计。
    """
    matrix = np.asarray(train_matrix, dtype=float)
    evaluation = np.asarray(evaluation_matrix, dtype=float)
    base_scores = pipeline_anomaly_scores(fitted_estimator, evaluation)
    rng = np.random.default_rng(random_seed)
    sample_size = max(2, int(len(matrix) * ANOMALY_STABILITY_SAMPLE_RATIO))
    correlations: list[float] = []
    for _ in range(n_subsamples):
        try:
            rows = rng.choice(len(matrix), size=sample_size, replace=False)
            retrained = clone(fitted_estimator)
            retrained.fit(matrix[rows])
            scores = pipeline_anomaly_scores(retrained, evaluation)
            if not np.isfinite(scores).all() or float(np.std(scores)) == 0.0:
                correlations.append(0.0)
                continue
            coefficient = float(spearmanr(base_scores, scores).statistic)
            correlations.append(coefficient if np.isfinite(coefficient) else 0.0)
        except Exception:
            correlations.append(0.0)
    return float(np.mean(correlations)) if correlations else 0.0


def evaluate_anomaly_candidate(
    estimator,
    train_matrix: np.ndarray,
    holdout_matrix: np.ndarray,
    benchmark: SyntheticBenchmark,
    *,
    contamination: float,
    random_seed: int = 42,
    compute_stability: bool = False,
) -> dict[str, object]:
    """拟合候选并在合成异常基准上产出完整评估指标。

    返回 dict 以 ``synthetic_auc`` 为主排序键、``perturbation_recall``
    次键、``stability`` 第三键（rank_candidates 的 anomaly 分支口径），
    ``score`` 字段供搜索器（Optuna）作为 trial 目标值。
    """
    matrix = np.asarray(train_matrix, dtype=float)
    holdout = benchmark.holdout_matrix
    estimator.fit(matrix)
    train_scores = pipeline_anomaly_scores(estimator, matrix)
    holdout_scores = pipeline_anomaly_scores(estimator, holdout)
    # 标定基线用保留集（held-out 正常数据）：train 分数是 in-sample 的，
    # IF/OC-SVM 对拟合过的点分数系统性压低，据此定阈值会推高运行期
    # 误报率；保留集标定使 normal_fpr ≈ contamination 数学上成立。
    calibrator = AnomalyScoreCalibrator.fit(holdout_scores, contamination=contamination)
    threshold = calibrator.threshold_score
    uniform_scores = pipeline_anomaly_scores(estimator, benchmark.uniform_outliers)
    perturbation_scores = pipeline_anomaly_scores(estimator, benchmark.perturbations)
    combinatorial_scores = pipeline_anomaly_scores(estimator, benchmark.combinatorial)

    all_scores = np.concatenate([holdout_scores, uniform_scores, perturbation_scores, combinatorial_scores])
    # 注入强度-检出率曲线（§3.3 第二层 S4 证据）：扰动形态按多档强度扫描——
    # 模型灵敏度随劣化幅度的衰减剖面（S4 面板曲线数据）。温和档在阈值附近
    # 检出率低是预期（最难度量），曲线单调性是健康信号。
    strength_curve: list[dict[str, object]] = []
    curve_count = len(benchmark.perturbations)
    if curve_count > 0:
        curve_rng = np.random.default_rng(random_seed)
        for multiplier in (0.5, float(ANOMALY_PERTURBATION_SIGMA), 3.0):
            perturbed = _build_perturbations(
                holdout, matrix, curve_count, curve_rng,
                sigma_multiplier=multiplier,
            )
            recall = float(np.mean(
                pipeline_anomaly_scores(estimator, perturbed) >= threshold
            )) if len(perturbed) else 0.0
            strength_curve.append({
                "sigma": multiplier,
                "label": f"±{multiplier:g}σ",
                "detection_recall": round(recall, 4),
            })
    labels = np.concatenate([
        np.zeros(len(holdout_scores), dtype=int),
        np.ones(len(all_scores) - len(holdout_scores), dtype=int),
    ])
    synthetic_auc = float(roc_auc_score(labels, all_scores)) if len(np.unique(labels)) == 2 else 0.0
    normal_fpr = float(np.mean(holdout_scores >= threshold))
    per_class_recall = {
        "uniform_outlier": float(np.mean(uniform_scores >= threshold)) if len(uniform_scores) else None,
        "local_perturbation": float(np.mean(perturbation_scores >= threshold)) if len(perturbation_scores) else None,
        "combinatorial_anomaly": float(np.mean(combinatorial_scores >= threshold)) if len(combinatorial_scores) else None,
    }
    metrics: dict[str, object] = {
        "score": synthetic_auc,
        "synthetic_auc": synthetic_auc,
        "perturbation_recall": float(np.mean(perturbation_scores >= threshold)) if len(perturbation_scores) else 0.0,
        "normal_fpr": normal_fpr,
        "holdout_size": int(len(holdout_scores)),
        "detection_recall_per_class": per_class_recall,
        "threshold_score": threshold,
        "calibrated_threshold": calibrator.calibrated_threshold,
        "calibration": {
            "probabilities": [float(value) for value in calibrator.quantile_probabilities],
            "quantile_points": [float(value) for value in calibrator.quantile_points],
        },
        "score_histograms": {
            "train": score_histogram(train_scores),
            "holdout": score_histogram(holdout_scores),
            "synthetic": score_histogram(all_scores[labels == 1]),
        },
        # 注入强度-检出率曲线（S4 证据面板）：扰动幅度衰减剖面
        "strength_curve": strength_curve,
        "synthetic_class_sizes": benchmark.synthetic_class_sizes,
    }
    if compute_stability:
        stability = stability_check(
            estimator, matrix, np.vstack([holdout, benchmark.synthetic_matrix]),
            random_seed=random_seed,
        )
        metrics["stability"] = stability
    metrics.update(evaluate_anomaly_gates(metrics, contamination=contamination))
    return metrics


def anomaly_top_contributors(
    pipeline,
    row: np.ndarray,
    feature_names: Sequence[str],
    *,
    top_k: int = 3,
    delta: float | None = None,
) -> list[dict[str, float | str]]:
    """逐特征归因（技术方案 §3.5）：中心差分数值梯度，方向与人工检查一致。

    贡献 = (score(x+δ·e_i) − score(x−δ·e_i)) / 2δ：离群分数对每个特征的
    敏感度（「特征梯度」实现，通用 IF/OC-SVM/二期 AE——AE 将来换逐特征
    重构误差分解）。输出按 |贡献| 降序 top_k，contribution 带符号
    （正=该特征当前取值推高异常分数）。

    pipeline 必须已拟合；δ 缺省为各特征 std 的 1%（退化列用绝对值兜底）。
    """
    base = np.asarray(row, dtype=float).reshape(1, -1)
    if base.shape[1] != len(feature_names):
        raise ValueError("AUTOML_ANOMALY_ATTRIBUTION_SHAPE_INVALID")
    steps = (
        np.maximum(np.abs(base[0]) * 0.01, 1e-6)
        if delta is None
        else np.full(len(feature_names), float(delta))
    )
    contributions: list[dict[str, float | str]] = []
    for index, name in enumerate(feature_names):
        perturbed_up = base.copy()
        perturbed_up[0, index] += steps[index]
        perturbed_down = base.copy()
        perturbed_down[0, index] -= steps[index]
        score_up = float(pipeline_anomaly_scores(pipeline, perturbed_up)[0])
        score_down = float(pipeline_anomaly_scores(pipeline, perturbed_down)[0])
        contributions.append({
            "feature": str(name),
            "contribution": (score_up - score_down) / (2.0 * steps[index]),
        })
    contributions.sort(key=lambda item: abs(float(item["contribution"])), reverse=True)
    return contributions[:top_k]


def evaluate_anomaly_gates(metrics: dict[str, object], *, contamination: float) -> dict[str, object]:
    """冠军资格门禁：synthetic_auc / normal_fpr / stability（方案 §3.3 第二层默认值）。

    stability 缺测（搜索期 trial）不否决，族冠军补测后由冠军选择统一判定。
    normal_fpr 门禁在大样本严格按 contamination×1.5；保留集小时观测 fpr 有
    Binomial 噪声（120 行下 99 分位阈值会在 1-2 个样本间跳动），按 2σ
    统计容差放宽下限，避免小样本任务被随机波动误杀。
    """
    synthetic_auc = float(metrics.get("synthetic_auc") or 0.0)
    # falsy-zero 陷阱：``normal_fpr=0.0``（零误报——最好情况）会被 ``or 1.0``
    # 读成 1.0（最差），把「一项门禁必过的完美模型」误判为未过。缺失才用
    # 缺省 1.0（缺测=否决，fail-closed），实测 0.0 必须按 0.0 读。
    raw_fpr = metrics.get("normal_fpr")
    normal_fpr = 1.0 if raw_fpr is None else float(raw_fpr)
    stability = metrics.get("stability")
    holdout_size = int(metrics.get("holdout_size") or 0)
    statistical_margin = (
        2.0 * (contamination * (1.0 - contamination) / holdout_size) ** 0.5
        if holdout_size > 0 else 0.0
    )
    fpr_threshold = max(
        contamination * ANOMALY_ACCEPTANCE_FPR_TOLERANCE,
        contamination + statistical_margin,
    )
    gates = {
        "synthetic_auc": {"value": synthetic_auc, "threshold": ANOMALY_ACCEPTANCE_SYNTHETIC_AUC, "passed": synthetic_auc >= ANOMALY_ACCEPTANCE_SYNTHETIC_AUC},
        "normal_fpr": {
            "value": normal_fpr,
            "threshold": fpr_threshold,
            "passed": normal_fpr <= fpr_threshold,
        },
    }
    if stability is not None:
        stability_value = float(stability)
        gates["stability"] = {
            "value": stability_value,
            "threshold": ANOMALY_ACCEPTANCE_STABILITY,
            "passed": stability_value >= ANOMALY_ACCEPTANCE_STABILITY,
        }
    return {
        "acceptance_gates": gates,
        "gates_passed": all(item["passed"] for item in gates.values()),
    }
