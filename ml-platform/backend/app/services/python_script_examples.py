"""Curated example scripts for the ``python_script`` operator.

Examples are served to the workflow editor ("插入示例脚本" dropdown). The
spot-weld example embeds the *current* source of
``app/services/spot_weld_features.py`` (read via inspect, so it always stays
in sync with the native operator); the tighten example mirrors the tighten
feature operator logic as a curated constant.

This file is an explicit legacy-adapter bridge: it reads the point-weld
feature module source to build examples and is whitelisted in
``app/services/genericization_gate.py``.
"""

from __future__ import annotations

import inspect

from app.services import spot_weld_features

LEGACY_ADAPTER_ONLY = True

_SPOT_WELD_GLUE = '''
# ---- 平台脚本接口：调用嵌入的特征工程模块 ----
LABEL_COLUMN = "Fault"  # 上游标签列（存在则追加为末列；置为 "" 可关闭）

features, _schema, _statistics = build_feature_frame(df)

if LABEL_COLUMN:
    _label_lookup = {str(column).casefold(): str(column) for column in df.columns}
    _actual_label = _label_lookup.get(str(LABEL_COLUMN).casefold())
    if _actual_label is not None:
        _label = df[_actual_label].reset_index(drop=True)
        if len(_label) != len(features):
            raise ValueError(f"{_actual_label} label length must match feature rows")
        features[_actual_label] = _label.to_numpy()

result = features
'''

_TIGHTEN_BODY = '''
import re
import numpy as np
import pandas as pd

# 列名配置（按需修改；大小写不敏感，支持带中文括号注解表头的基础名匹配）
TORQUE_COLUMN = "ACTUAL_TORQUE"          # 实际扭矩列
TARGET_TORQUE_COLUMN = "TARGET_TORQUE"   # 目标扭矩列
UPPER_LIMIT_COLUMN = "UPPER_LIMIT"       # 力矩上限列
LOWER_LIMIT_COLUMN = "LOWER_LIMIT"       # 力矩下限列
TORQUE_TWO_COLUMN = "ACTUAL_TORQUE_TWO"  # 二轴扭矩列（置 "" 跳过双轴差）
OUTPUT_PREFIX = "TIGHTEN_"               # 派生特征名前缀
DROP_COLUMNS = "DECIDE_ONE,DECIDE_TWO"   # 泄漏判定列（逗号分隔，空串禁用剔除）
MISSING_STRATEGY = "median"              # 缺失填充：keep/zero/median/mean
MISSING_FLAG_COLUMN = "TIGHTEN_MISSING_FLAG"  # 缺失标记列（空串禁用）


def _resolve_column(lookup, name):
    key = str(name or "").strip()
    if not key:
        return None
    if key.casefold() in lookup:
        return lookup[key.casefold()]
    # 生产表头常带中文注解（如 "ACTUAL_TORQUE(实际扭矩)"）：按括号前基础名匹配
    for column_folded, original in lookup.items():
        base = re.split(r"[(（]", column_folded, maxsplit=1)[0].strip()
        if base == key.casefold():
            return original
    return None


def _fill_numeric_missing(features, strategy, columns=None):
    """按策略填充数值列缺失，返回（填充单元格数, 行级缺失掩码）；全缺失列回退 0。"""
    target_columns = (
        list(features.select_dtypes(include=[np.number]).columns)
        if columns is None else [c for c in columns if c in features.columns]
    )
    mask = (
        features[target_columns].isna().any(axis=1)
        if target_columns else pd.Series(False, index=features.index)
    )
    filled = 0
    if strategy in ("zero", "median", "mean"):
        for column in target_columns:
            series = features[column]
            if not series.isna().any():
                continue
            if strategy == "zero":
                value = 0
            else:
                value = series.median() if strategy == "median" else series.mean()
                if pd.isna(value):
                    value = 0
            filled += int(series.isna().sum())
            features[column] = series.fillna(value)
    return filled, mask


def process(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        raise ValueError("Tighten feature engineering requires non-empty input data")

    lookup = {str(column).casefold(): str(column) for column in df.columns}

    torque_col = _resolve_column(lookup, TORQUE_COLUMN)
    target_col = _resolve_column(lookup, TARGET_TORQUE_COLUMN)
    if torque_col is None or target_col is None:
        raise ValueError(
            f"Tighten feature engineering requires both {TORQUE_COLUMN!r} and {TARGET_TORQUE_COLUMN!r}"
        )
    upper_col = _resolve_column(lookup, UPPER_LIMIT_COLUMN)
    lower_col = _resolve_column(lookup, LOWER_LIMIT_COLUMN)
    torque_two_col = _resolve_column(lookup, TORQUE_TWO_COLUMN)
    prefix = str(OUTPUT_PREFIX or "").strip() or "TIGHTEN_"
    strategy = str(MISSING_STRATEGY or "median").strip().lower()
    flag_column = str(MISSING_FLAG_COLUMN or "").strip()

    features = df.copy()

    # --- 缺失填充（派生前，作用在原始数值列；单轴行二轴缺失由此保留参与训练） ---
    missing_mask = pd.Series(False, index=features.index)
    if strategy != "keep":
        missing_mask = _fill_numeric_missing(features, strategy)[1]

    torque = pd.to_numeric(features[torque_col], errors="coerce")
    target = pd.to_numeric(features[target_col], errors="coerce")

    derived: list[str] = []
    deviation = torque - target
    features[f"{prefix}TORQUE_DEVIATION"] = deviation
    derived.append(f"{prefix}TORQUE_DEVIATION")

    if upper_col is not None and lower_col is not None:
        upper = pd.to_numeric(features[upper_col], errors="coerce")
        lower = pd.to_numeric(features[lower_col], errors="coerce")
        band = upper - lower
        features[f"{prefix}DEVIATION_RATIO"] = deviation / band.replace(0, np.nan)
        features[f"{prefix}UPPER_MARGIN"] = upper - torque
        features[f"{prefix}LOWER_MARGIN"] = torque - lower
        derived.extend([
            f"{prefix}DEVIATION_RATIO", f"{prefix}UPPER_MARGIN", f"{prefix}LOWER_MARGIN",
        ])

    if torque_two_col is not None:
        torque_two = pd.to_numeric(features[torque_two_col], errors="coerce")
        if torque_two.notna().any():
            features[f"{prefix}DUAL_AXIS_DIFF"] = torque - torque_two
            derived.append(f"{prefix}DUAL_AXIS_DIFF")

    # --- 泄漏判定列剔除（判定结果与目标强相关属标签泄漏；空串禁用） ---
    drop_source = str(DROP_COLUMNS or "").strip()
    if drop_source:
        for name in [item.strip() for item in drop_source.split(",") if item.strip()]:
            resolved = _resolve_column(lookup, name)
            if resolved is not None and resolved in features.columns:
                features = features.drop(columns=[resolved])

    # --- 派生列残留缺失填充（如零带宽比率）+ 缺失标记列（单轴行置 1） ---
    if strategy != "keep" and derived:
        derived_filled, derived_mask = _fill_numeric_missing(features, strategy, columns=derived)
        missing_mask = missing_mask | derived_mask
    if strategy != "keep" and flag_column:
        features[flag_column] = missing_mask.astype(int)

    return features


if __name__ == "__main__":
    result = process(df)
'''


def list_examples() -> list[dict[str, str]]:
    """Return curated python_script examples (interface template wrapped)."""
    from app.operators.utility_operators import (
        PYTHON_SCRIPT_FOOTER,
        PYTHON_SCRIPT_HEADER,
    )

    spot_weld_source = inspect.getsource(spot_weld_features)
    spot_weld_script = (
        PYTHON_SCRIPT_HEADER + "\n" + spot_weld_source + _SPOT_WELD_GLUE + "\n"
        + PYTHON_SCRIPT_FOOTER + "\n"
    )
    tighten_script = (
        PYTHON_SCRIPT_HEADER + "\n" + _TIGHTEN_BODY + "\n"
        + PYTHON_SCRIPT_FOOTER + "\n"
    )
    return [
        {
            "id": "spot_weld_feature_engineering",
            "name": "示例：点焊特征工程（波形解码 73 特征）",
            "description": "内嵌点焊报告波形解码与 73 维特征计算，与原生算子等价；上游含 Fault 列时自动追加标签",
            "script": spot_weld_script,
        },
        {
            "id": "tighten_feature_engineering",
            "name": "示例：拧紧特征工程（扭矩派生特征）",
            "description": (
                "与原生拧紧特征工程算子逐值等价：先中位数填充原始数值列缺失并生成"
                "缺失标记列（单轴行保留），再派生扭矩偏差、公差带内偏差率、上下限"
                "余量、双轴扭矩差，最后剔除泄漏判定列（基础名匹配）；列名/剔除列/"
                "填充策略均可配置"
            ),
            "script": tighten_script,
        },
    ]
