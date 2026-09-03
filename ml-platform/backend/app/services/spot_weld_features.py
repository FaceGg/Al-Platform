"""Legacy spot-weld feature adapter; generic routes must not import it."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

LEGACY_ADAPTER_ONLY = True


WAVEFORM_BYTES = 1740
WAVEFORM_POINTS = 870
WAVEFORM_FIELDS = ("cvei", "cvev", "cver", "cvep")
CHANNEL_NAMES = ("current", "voltage", "resistance", "power")
REPORT_TABLE_FIELDS = (
    "wld1c", "wld2c", "tipv1", "tipv2", "wres", "energy",
    "wld_spatter_strength", "wld1_spatter_strength", "wld2_spatter_strength",
    "spatterpos_wld", "spatterpos_pre", "spotdiameter", "spotposition", "spattercode",
)
DERIVED_TABLE_FIELDS = (
    "current_ratio", "voltage_ratio", "power_wld1", "power_wld2", "power_ratio",
    "energy_per_current", "spatter_total", "spatter_asym", "diameter_norm",
    "energy_dev", "spatter_seg",
)
TABLE_FEATURES = REPORT_TABLE_FIELDS + DERIVED_TABLE_FIELDS
WAVEFORM_STATISTICS = (
    "mean", "std", "max", "min", "pp", "median", "rise_time", "stable_mean",
    "stable_std", "avg_diff", "max_diff", "p95_diff",
)
FEATURE_SCHEMA = tuple(
    TABLE_FEATURES
    + tuple(f"{channel}_{statistic}" for channel in CHANNEL_NAMES for statistic in WAVEFORM_STATISTICS)
)


class QualityPipelineError(ValueError):
    """Stable client-safe failure for the quality pipeline."""

    def __init__(self, code: str, *, row_index: int | None = None, field_name: str | None = None, message: str | None = None):
        self.code = code
        self.row_index = row_index
        self.field_name = field_name
        detail = message or code
        context = []
        if row_index is not None:
            context.append(f"row={row_index}")
        if field_name:
            context.append(f"field={field_name}")
        super().__init__(f"{detail} ({', '.join(context)})" if context else detail)

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "row_index": self.row_index,
            "field_name": self.field_name,
            "message": str(self),
        }


@dataclass(frozen=True)
class DecodedReportRow:
    index: int
    values: dict[str, float]
    waveforms: dict[str, list[float]]


def decode_waveform(encoded: str, *, field_name: str, row_index: int) -> np.ndarray:
    if not isinstance(encoded, str) or not encoded.strip():
        raise QualityPipelineError("QUALITY_WAVEFORM_INVALID_BASE64", row_index=row_index, field_name=field_name)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError, binascii.Error) as error:
        raise QualityPipelineError("QUALITY_WAVEFORM_INVALID_BASE64", row_index=row_index, field_name=field_name) from error
    if len(raw) != WAVEFORM_BYTES:
        raise QualityPipelineError("QUALITY_WAVEFORM_LENGTH_INVALID", row_index=row_index, field_name=field_name)
    values = np.frombuffer(raw, dtype=">i2").astype(np.float64)
    if values.shape != (WAVEFORM_POINTS,) or not np.isfinite(values).all():
        raise QualityPipelineError("QUALITY_WAVEFORM_LENGTH_INVALID", row_index=row_index, field_name=field_name)
    return values


def canonicalize_report_frame(
    frame: pd.DataFrame,
    field_mapping: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise QualityPipelineError("QUALITY_DATASET_INVALID", message="Dataset must be a dataframe")
    # CSV/XLSX readers may preserve a UTF-8 BOM or accidental surrounding
    # whitespace in headers. Keep exact names authoritative, then use a
    # normalized alias only when the exact source column is absent.
    normalized_columns: dict[str, str] = {}
    for column in frame.columns:
        normalized = str(column).lstrip("\ufeff").strip()
        if normalized and normalized not in normalized_columns:
            normalized_columns[normalized] = column
    mapping = {name: name for name in (*REPORT_TABLE_FIELDS, *WAVEFORM_FIELDS)}
    if field_mapping:
        mapping.update({str(key).lstrip("\ufeff").strip(): str(value) for key, value in field_mapping.items()})
    required = (*REPORT_TABLE_FIELDS, *WAVEFORM_FIELDS)
    sources: list[str] = []
    missing: list[str] = []
    for name in required:
        source = mapping.get(name, name)
        if source not in frame.columns:
            source = normalized_columns.get(str(source).lstrip("\ufeff").strip(), source)
        if source not in frame.columns:
            missing.append(name)
        else:
            sources.append(source)
    if missing:
        raise QualityPipelineError("QUALITY_FIELD_MAPPING_INVALID", message=f"Missing fields: {', '.join(missing)}")
    if len(sources) != len(set(sources)):
        raise QualityPipelineError("QUALITY_FIELD_MAPPING_INVALID", message="Field mapping contains duplicate source columns")
    selected = frame.loc[:, sources].copy()
    selected.columns = list(required)
    return selected.reset_index(drop=True)


def _numeric_column(frame: pd.DataFrame, name: str) -> np.ndarray:
    values = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=np.float64)
    if not np.isfinite(values).all():
        row = int(np.flatnonzero(~np.isfinite(values))[0])
        raise QualityPipelineError("QUALITY_FEATURE_NONFINITE", row_index=row, field_name=name)
    return values


def _safe_divide(numerator: np.ndarray, denominator: np.ndarray, *, field_name: str) -> np.ndarray:
    if np.any(denominator == 0):
        row = int(np.flatnonzero(denominator == 0)[0])
        raise QualityPipelineError("QUALITY_FEATURE_NONFINITE", row_index=row, field_name=field_name)
    result = numerator / denominator
    if not np.isfinite(result).all():
        row = int(np.flatnonzero(~np.isfinite(result))[0])
        raise QualityPipelineError("QUALITY_FEATURE_NONFINITE", row_index=row, field_name=field_name)
    return result


def _waveform_statistics(values: np.ndarray) -> dict[str, float]:
    differences = np.abs(np.diff(values))
    minimum = float(np.min(values))
    maximum = float(np.max(values))
    span = maximum - minimum
    if span == 0:
        rise_time = 0.0
    else:
        low = minimum + span * 0.1
        high = minimum + span * 0.9
        low_index = int(np.argmax(values >= low))
        high_index = int(np.argmax(values >= high))
        rise_time = float(max(0, high_index - low_index))
    stable = values[len(values) // 2:]
    result = {
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "max": maximum,
        "min": minimum,
        "pp": float(span),
        "median": float(np.median(values)),
        "rise_time": rise_time,
        "stable_mean": float(np.mean(stable)),
        "stable_std": float(np.std(stable)),
        "avg_diff": float(np.mean(differences)),
        "max_diff": float(np.max(differences)),
        "p95_diff": float(np.percentile(differences, 95)),
    }
    if not np.isfinite(list(result.values())).all():
        raise QualityPipelineError("QUALITY_FEATURE_NONFINITE")
    return result


def decode_report_waveforms(
    frame: pd.DataFrame,
    field_mapping: Mapping[str, str] | None = None,
) -> list[dict[str, list[float]]]:
    canonical = canonicalize_report_frame(frame, field_mapping)
    decoded: list[dict[str, list[float]]] = []
    for row_index, row in canonical.iterrows():
        channels = {}
        for field_name, channel in zip(WAVEFORM_FIELDS, CHANNEL_NAMES):
            channels[channel] = decode_waveform(row[field_name], field_name=field_name, row_index=int(row_index)).tolist()
        decoded.append(channels)
    return decoded


def build_feature_frame(
    frame: pd.DataFrame,
    field_mapping: Mapping[str, str] | None = None,
) -> tuple[pd.DataFrame, list[str], dict[str, object]]:
    canonical = canonicalize_report_frame(frame, field_mapping)
    values = {name: _numeric_column(canonical, name) for name in REPORT_TABLE_FIELDS}
    wld1c, wld2c = values["wld1c"], values["wld2c"]
    tipv1, tipv2 = values["tipv1"], values["tipv2"]
    energy = values["energy"]
    spotdiameter = values["spotdiameter"]
    spatter_1, spatter_2 = values["wld1_spatter_strength"], values["wld2_spatter_strength"]
    energy_std = float(np.std(energy))
    diameter_median = float(np.median(spotdiameter))
    derived = {
        "current_ratio": _safe_divide(wld1c, wld2c, field_name="current_ratio"),
        "voltage_ratio": _safe_divide(tipv1, tipv2, field_name="voltage_ratio"),
        "power_wld1": wld1c * tipv1,
        "power_wld2": wld2c * tipv2,
        "power_ratio": _safe_divide(wld1c * tipv1, wld2c * tipv2, field_name="power_ratio"),
        "energy_per_current": _safe_divide(energy, wld1c, field_name="energy_per_current"),
        "spatter_total": spatter_1 + spatter_2,
        "spatter_asym": np.abs(spatter_1 - spatter_2),
        "diameter_norm": np.zeros_like(spotdiameter) if diameter_median == 0 else spotdiameter / diameter_median,
        "energy_dev": np.zeros_like(energy) if energy_std == 0 else (energy - float(np.mean(energy))) / energy_std,
        "spatter_seg": np.floor(values["spattercode"] / 10.0),
    }
    columns = {name: values[name] for name in REPORT_TABLE_FIELDS}
    columns.update(derived)
    waveforms = decode_report_waveforms(canonical)
    for channel in CHANNEL_NAMES:
        stats = [_waveform_statistics(np.asarray(row[channel], dtype=np.float64)) for row in waveforms]
        for statistic in WAVEFORM_STATISTICS:
            columns[f"{channel}_{statistic}"] = np.asarray([item[statistic] for item in stats], dtype=np.float64)
    result = pd.DataFrame({name: columns[name] for name in FEATURE_SCHEMA})
    if list(result.columns) != list(FEATURE_SCHEMA) or len(result.columns) != 73:
        raise QualityPipelineError("QUALITY_FEATURE_SCHEMA_INVALID")
    if not np.isfinite(result.to_numpy(dtype=np.float64)).all():
        raise QualityPipelineError("QUALITY_FEATURE_NONFINITE")
    statistics = {
        "row_count": int(len(result)),
        "feature_count": len(FEATURE_SCHEMA),
        "waveform_points": WAVEFORM_POINTS,
        "feature_version": "report_v1",
        "waveform_fields": list(WAVEFORM_FIELDS),
    }
    return result, list(FEATURE_SCHEMA), statistics
