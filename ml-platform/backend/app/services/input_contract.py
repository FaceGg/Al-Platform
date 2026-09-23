from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class ValidationReport:
    code: str
    partial_output_allowed: bool
    details: dict[str, Any] | None = None


def build_input_contract(frame: pd.DataFrame, feature_columns: list[str], missing_policy: dict[str, str], preprocessing_version: str) -> dict[str, Any]:
    columns = {}
    for name in feature_columns:
        if name not in frame.columns:
            continue
        columns[name] = {
            "dtype": "float" if pd.api.types.is_float_dtype(frame[name]) else ("int" if pd.api.types.is_integer_dtype(frame[name]) else "str"),
            "missing_policy": missing_policy.get(name, "allow"),
        }
    return {"required_columns": list(feature_columns), "columns": columns, "preprocessing_version": preprocessing_version}


def _dtype_matches(series: pd.Series, expected: str) -> bool:
    if expected == "int":
        return pd.api.types.is_integer_dtype(series.dtype)
    if expected == "float":
        return pd.api.types.is_float_dtype(series.dtype) or pd.api.types.is_integer_dtype(series.dtype)
    if expected == "number":
        return pd.api.types.is_numeric_dtype(series.dtype)
    if expected in {"str", "string"}:
        return pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype)
    return str(series.dtype) == expected


def validate_input_contract(frame: pd.DataFrame, contract: dict[str, Any]) -> ValidationReport:
    required = list(contract.get("required_columns", []))
    missing = [name for name in required if name not in frame.columns]
    if missing:
        return ValidationReport("INPUT_REQUIRED_COLUMN_MISSING", False, {"columns": missing})
    for name, spec in contract.get("columns", {}).items():
        if name not in frame.columns:
            continue
        series = frame[name]
        policy = spec.get("missing_policy", "allow")
        if policy == "reject" and series.isna().any():
            return ValidationReport("INPUT_NULL_VALUE", False, {"column": name})
        if not _dtype_matches(series.dropna(), spec.get("dtype", str(series.dtype))):
            return ValidationReport("INPUT_DTYPE_MISMATCH", False, {"column": name})
        if pd.api.types.is_float_dtype(series):
            values = series.dropna().to_numpy(dtype=float)
            if not np.isfinite(values).all():
                return ValidationReport("INPUT_NONFINITE_FLOAT", False, {"column": name})
        if spec.get("min_value") is not None and (series.dropna() < spec["min_value"]).any():
            return ValidationReport("INPUT_RANGE_INVALID", False, {"column": name})
        if spec.get("max_value") is not None and (series.dropna() > spec["max_value"]).any():
            return ValidationReport("INPUT_RANGE_INVALID", False, {"column": name})
    sample_column = contract.get("sample_id_column")
    if sample_column:
        if sample_column not in frame.columns:
            return ValidationReport("INPUT_SAMPLE_ID_INVALID", False, {"column": sample_column})
        values = frame[sample_column]
        if values.isna().any() or values.astype(str).str.strip().eq("").any() or values.astype(str).duplicated().any():
            return ValidationReport("INPUT_SAMPLE_ID_INVALID", False, {"column": sample_column})
    return ValidationReport("OK", True)
