"""Curated example scripts for the ``python_script`` operator.

Examples are served to the workflow editor ("插入示例脚本" dropdown). The
spot-weld example embeds the *current* source of
``app/services/spot_weld_features.py`` (read via inspect, so it always stays
in sync with the native operator); the tighten example mirrors the tighten
feature operator logic as a curated constant.
"""

from __future__ import annotations

import inspect

from app.services import spot_weld_features

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
import numpy as np
import pandas as pd

# 列名配置（按需修改；大小写不敏感）
TORQUE_COLUMN = "ACTUAL_TORQUE"          # 实际扭矩列
TARGET_TORQUE_COLUMN = "TARGET_TORQUE"   # 目标扭矩列
UPPER_LIMIT_COLUMN = "UPPER_LIMIT"       # 力矩上限列
LOWER_LIMIT_COLUMN = "LOWER_LIMIT"       # 力矩下限列
TORQUE_TWO_COLUMN = "ACTUAL_TORQUE_TWO"  # 二轴扭矩列（置 "" 跳过双轴差）
OUTPUT_PREFIX = "TIGHTEN_"               # 派生特征名前缀


def process(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        raise ValueError("Tighten feature engineering requires non-empty input data")

    lookup = {str(column).casefold(): str(column) for column in df.columns}

    def resolve_column(name: str):
        key = str(name or "").strip()
        return lookup.get(key.casefold()) if key else None

    torque_col = resolve_column(TORQUE_COLUMN)
    target_col = resolve_column(TARGET_TORQUE_COLUMN)
    if torque_col is None or target_col is None:
        raise ValueError(
            f"Tighten feature engineering requires both {TORQUE_COLUMN!r} and {TARGET_TORQUE_COLUMN!r}"
        )
    upper_col = resolve_column(UPPER_LIMIT_COLUMN)
    lower_col = resolve_column(LOWER_LIMIT_COLUMN)
    torque_two_col = resolve_column(TORQUE_TWO_COLUMN)
    prefix = str(OUTPUT_PREFIX or "").strip() or "TIGHTEN_"

    torque = pd.to_numeric(df[torque_col], errors="coerce")
    target = pd.to_numeric(df[target_col], errors="coerce")
    features = df.copy()

    deviation = torque - target
    features[f"{prefix}TORQUE_DEVIATION"] = deviation

    if upper_col is not None and lower_col is not None:
        upper = pd.to_numeric(df[upper_col], errors="coerce")
        lower = pd.to_numeric(df[lower_col], errors="coerce")
        band = upper - lower
        features[f"{prefix}DEVIATION_RATIO"] = deviation / band.replace(0, np.nan)
        features[f"{prefix}UPPER_MARGIN"] = upper - torque
        features[f"{prefix}LOWER_MARGIN"] = torque - lower

    if torque_two_col is not None:
        torque_two = pd.to_numeric(df[torque_two_col], errors="coerce")
        if torque_two.notna().any():
            features[f"{prefix}DUAL_AXIS_DIFF"] = torque - torque_two

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
            "description": "派生扭矩偏差、公差带内偏差率、上下限余量、双轴扭矩差，列名可配置",
            "script": tighten_script,
        },
    ]
