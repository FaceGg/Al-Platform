"""profile_data — deterministic dataset profiling for the AutoML Agent (S1).

Spec v0.9 §S1 + §17.1: column-level statistics only by default; row samples
are the most sensitive egress surface and stay off unless explicitly enabled
(and sensitive columns are always masked). Numeric results come straight from
platform computation — the LLM only reads the structured report.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

_ANNOTATION_RE = re.compile(r"^(.*?)([（(])+(.*?)([）)])+$", re.IGNORECASE)
# 宽表画像瘦身阈值：超过该列数时逐列统计自动截断（见 profile_data 尾部）
_WIDE_TABLE_COLUMN_THRESHOLD = 200
_TIME_NAME_RE = re.compile(
    r"time|date|timestamp|datetime|时间|日期|时刻", re.IGNORECASE
)


def split_annotation(column_name: str) -> tuple[str, str | None]:
    """``ACTUAL_TORQUE(实际扭矩/一轴实际扭矩)`` → (base, semantic)."""
    match = _ANNOTATION_RE.match(column_name.strip())
    if match:
        base = match.group(1).strip()
        semantic = match.group(3).strip()
        if base:
            return base, semantic or None
    return column_name.strip(), None


def _column_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "string"


def _quantiles(series: pd.Series) -> dict:
    values = series.dropna()
    if values.empty:
        return {}
    return {
        "min": float(values.min()),
        "p25": float(values.quantile(0.25)),
        "median": float(values.median()),
        "p75": float(values.quantile(0.75)),
        "max": float(values.max()),
    }


def profile_data(
    frame: pd.DataFrame,
    target: str | None = None,
    *,
    row_samples: bool = False,
    sensitive_columns: set[str] | frozenset[str] | None = None,
    sample_limit: int = 20,
    mi_top_k: int = 10,
    correlation_threshold: float = 0.95,
) -> dict:
    """Build the deterministic S1 input profile for one dataset snapshot."""
    sensitive = frozenset(sensitive_columns or ())
    row_count = int(len(frame))
    columns: list[dict] = []
    for name in frame.columns:
        series = frame[name]
        missing_rate = float(series.isna().mean()) if row_count else 0.0
        non_null = series.dropna()
        cardinality = int(non_null.nunique())
        entry: dict = {
            "name": str(name),
            "base_name": split_annotation(str(name))[0],
            "semantic": split_annotation(str(name))[1],
            "dtype": _column_type(series),
            "missing_rate": round(missing_rate, 6),
            "cardinality": cardinality,
            "cardinality_ratio": round(cardinality / row_count, 6) if row_count else 0.0,
            "constant": bool(cardinality <= 1),
        }
        if entry["dtype"] in {"integer", "float"} and not non_null.empty:
            entry["quantiles"] = _quantiles(series)
        if entry["dtype"] == "string" and not non_null.empty:
            entry["top_values"] = [
                str(value) for value in non_null.astype(str).value_counts().head(5).index
            ]
        columns.append(entry)

    report: dict = {
        "row_count": row_count,
        "column_count": int(frame.shape[1]),
        "columns": columns,
    }

    numeric = frame.select_dtypes(include=["number"])
    report["high_correlation_pairs"] = _high_correlation_pairs(
        numeric, correlation_threshold
    )
    report["time_columns"] = _time_columns(frame)
    report["mutual_info_top"] = _mutual_info_top(
        frame, target, mi_top_k
    )

    if target is not None and target in frame.columns:
        report["target"] = _target_profile(frame[target])
    else:
        report["target"] = None

    # 宽表画像瘦身（自动截断并告知用户）：列数超过阈值时逐列统计不再提供
    # quantiles/top_values/cardinality 细节——3004 列全量曾把 S1 prompt 撑到
    # 9.8MB 顶爆请求体、把模型输出撑爆 8k token 上限（JSON 被截断）。瘦身后
    # 每列仅保留 name/dtype/missing_rate，S1 依据列名语义 + 互信息 top-k 仍
    # 能生成有效的通道预期；压缩事实写入 wide_table_note 一并落档案告知用户。
    if len(columns) > _WIDE_TABLE_COLUMN_THRESHOLD:
        slim: list[dict] = []
        for entry in columns:
            slim.append(
                {
                    "name": entry["name"],
                    "dtype": entry["dtype"],
                    "missing_rate": entry["missing_rate"],
                }
            )
        report["columns"] = slim
        report["wide_table_note"] = (
            f"数据集为宽表（{len(columns)} 列），画像已自动瘦身：每列仅保留"
            "名称/类型/缺失率，分位数与高频值摘要已省略；关键特征线索见"
            " mutual_info_top 与高相关对。"
        )

    if row_samples and row_count:
        sample = frame.head(sample_limit).copy()
        for column in sensitive & set(sample.columns):
            sample[column] = "***"
        report["row_samples"] = [
            {str(key): (None if pd.isna(value) else _jsonable(value)) for key, value in row.items()}
            for row in sample.to_dict(orient="records")
        ]
    return report


def _jsonable(value):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def _high_correlation_pairs(
    numeric: pd.DataFrame, threshold: float
) -> list[dict]:
    if numeric.shape[1] < 2:
        return []
    correlation = numeric.corr(method="pearson")
    pairs: list[dict] = []
    names = list(correlation.columns)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            value = correlation.loc[left, right]
            if pd.isna(value):
                continue
            if abs(float(value)) > threshold:
                pairs.append(
                    {"a": left, "b": right, "corr": round(abs(float(value)), 6)}
                )
    pairs.sort(key=lambda item: (-item["corr"], item["a"], item["b"]))
    # 宽表守卫：数千列时高相关对是 O(n²) 组合爆炸（3004 列实测 12.3 万对
    # ≈7.6MB，曾把 S1 prompt 撑到 9.8MB 直接顶爆请求体上限）。已按 corr
    # 降序排列，只保留最强的前 40 对供 S1 参考——冗余对不产生增量信息。
    return pairs[:40]


def _time_columns(frame: pd.DataFrame) -> list[str]:
    detected: list[str] = []
    for name in frame.columns:
        series = frame[name]
        is_time = pd.api.types.is_datetime64_any_dtype(series) or (
            _TIME_NAME_RE.search(str(name)) is not None
            and not pd.api.types.is_numeric_dtype(series)
        )
        if is_time:
            detected.append(str(name))
    return detected


def _target_profile(series: pd.Series) -> dict:
    non_null = series.dropna()
    distribution = {str(key): int(value) for key, value in non_null.value_counts().items()}
    counts = sorted(distribution.values(), reverse=True)
    if len(counts) >= 2 and counts[0]:
        majority_share = counts[0] / max(sum(counts), 1)
        imbalance_ratio = round(counts[0] / counts[1], 6)
    else:
        majority_share = 1.0
        imbalance_ratio = float("inf") if counts else 0.0
    if distribution:
        majority_label = max(distribution, key=lambda key: distribution[key])
        minority_label = min(distribution, key=lambda key: distribution[key])
    else:
        majority_label = minority_label = None
    return {
        "dtype": _column_type(series),
        "distribution": distribution,
        "majority_label": majority_label,
        "minority_label": minority_label,
        "majority_share": round(majority_share, 6),
        "imbalance_ratio": imbalance_ratio,
        "missing": int(series.isna().sum()),
    }


def _mutual_info_top(
    frame: pd.DataFrame, target: str | None, top_k: int
) -> list[dict]:
    if target is None or target not in frame.columns:
        return []
    from sklearn.feature_selection import mutual_info_classif

    target_series = frame[target].dropna()
    if target_series.empty:
        return []
    aligned = frame.loc[target_series.index]
    features = aligned.drop(columns=[target])
    matrix = pd.DataFrame(index=features.index)
    for name in features.columns:
        series = features[name]
        if pd.api.types.is_numeric_dtype(series):
            matrix[name] = series.fillna(series.median())
        else:
            matrix[name] = series.astype(str).fillna("__missing__")
            codes, _uniques = pd.factorize(matrix[name])
            matrix[name] = codes
    matrix = matrix.astype(float)
    matrix = matrix.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    scores = mutual_info_classif(matrix, target_series, discrete_features=False, random_state=0)
    ranking = sorted(
        (
            {"column": str(name), "mi": round(float(score), 6)}
            for name, score in zip(matrix.columns, scores)
        ),
        key=lambda item: (-item["mi"], item["column"]),
    )
    return ranking[:top_k]
