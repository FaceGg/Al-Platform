from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


IDENTITY_COLUMNS = ["Car Body", "Welding Spot", "Date"]
SOURCE_FILES = {
    "current": "current.csv",
    "voltage": "voltage.csv",
    "force": "force.csv",
    "labels": "labels.csv",
}
PREPARATION_VERSION = "1.0"


class WeldDemoPreparationError(ValueError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.details = details or {}
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class WeldDemoResult:
    output_path: Path
    row_count: int
    columns: list[str]
    class_distribution: dict[str, int]
    source_hashes: dict[str, str]
    generated_at: str
    preparation_version: str = PREPARATION_VERSION


class WeldDemoService:
    def prepare(self, source_dir: str | Path, output_csv: str | Path) -> WeldDemoResult:
        source_dir = Path(source_dir)
        output_csv = Path(output_csv)
        if not source_dir.is_dir():
            raise WeldDemoPreparationError(
                "WELD_DATA_DIRECTORY_MISSING", f"Source directory not found: {source_dir}",
            )

        paths = {name: source_dir / filename for name, filename in SOURCE_FILES.items()}
        missing = [path.name for path in paths.values() if not path.is_file()]
        if missing:
            raise WeldDemoPreparationError(
                "WELD_DATA_FILE_MISSING", "Required source files are missing", {"files": missing},
            )

        frames = {name: pd.read_csv(path) for name, path in paths.items()}
        self._validate_frames(frames)
        prepared = frames["labels"][IDENTITY_COLUMNS].copy()
        for signal in ("current", "voltage", "force"):
            prepared = pd.concat(
                [prepared, self._extract_features(frames[signal], signal)], axis=1,
            )
        prepared["Fault"] = frames["labels"]["Fault"].astype(int)

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", suffix=".csv",
                dir=output_csv.parent, delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                prepared.to_csv(temporary, index=False, lineterminator="\n")
            temporary_path.replace(output_csv)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise WeldDemoPreparationError(
                "WELD_DATA_OUTPUT_FAILED", f"Failed to write output: {exc}",
            ) from exc

        distribution = prepared["Fault"].value_counts().sort_index()
        return WeldDemoResult(
            output_path=output_csv.resolve(),
            row_count=len(prepared),
            columns=list(prepared.columns),
            class_distribution={str(key): int(value) for key, value in distribution.items()},
            source_hashes={name: self._sha256(path) for name, path in paths.items()},
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _validate_frames(frames: dict[str, pd.DataFrame]) -> None:
        for name, frame in frames.items():
            missing_identity = [column for column in IDENTITY_COLUMNS if column not in frame.columns]
            if missing_identity:
                raise WeldDemoPreparationError(
                    "WELD_DATA_SCHEMA_INVALID", f"{name} is missing identity columns",
                    {"columns": missing_identity},
                )
        row_counts = {name: len(frame) for name, frame in frames.items()}
        if len(set(row_counts.values())) != 1:
            raise WeldDemoPreparationError(
                "WELD_DATA_ROW_COUNT_MISMATCH", "Source files have different row counts", row_counts,
            )
        expected_identity = frames["labels"][IDENTITY_COLUMNS].astype(str).reset_index(drop=True)
        for name in ("current", "voltage", "force"):
            actual_identity = frames[name][IDENTITY_COLUMNS].astype(str).reset_index(drop=True)
            if not expected_identity.equals(actual_identity):
                raise WeldDemoPreparationError(
                    "WELD_DATA_IDENTITY_MISMATCH", f"{name} identity rows do not match labels",
                )
        if "Fault" not in frames["labels"].columns:
            raise WeldDemoPreparationError(
                "WELD_DATA_SCHEMA_INVALID", "labels.csv is missing Fault",
            )
        fault = pd.to_numeric(frames["labels"]["Fault"], errors="coerce")
        values = set(fault.dropna().astype(int).unique())
        if fault.isna().any() or values != {0, 1}:
            raise WeldDemoPreparationError(
                "WELD_DATA_FAULT_INVALID", "Fault must contain both binary classes 0 and 1",
                {"values": sorted(values)},
            )

    @staticmethod
    def _extract_features(frame: pd.DataFrame, signal: str) -> pd.DataFrame:
        value_columns = [column for column in frame.columns if column not in IDENTITY_COLUMNS]
        values = frame[value_columns].apply(pd.to_numeric, errors="coerce")
        if not value_columns or not values.notna().any().any():
            raise WeldDemoPreparationError(
                "WELD_DATA_FEATURES_EMPTY", f"{signal} has no usable numeric features",
            )
        values = values.fillna(0.0)
        array = values.to_numpy(dtype=float)
        non_zero = array != 0
        peak_positions = np.argmax(array, axis=1)
        first_non_zero = np.where(non_zero.any(axis=1), non_zero.argmax(axis=1), -1)
        last_non_zero = np.where(
            non_zero.any(axis=1), array.shape[1] - 1 - non_zero[:, ::-1].argmax(axis=1), -1,
        )
        prefix = signal.lower()
        return pd.DataFrame({
            f"{prefix}_mean": np.mean(array, axis=1),
            f"{prefix}_std": np.std(array, axis=1),
            f"{prefix}_min": np.min(array, axis=1),
            f"{prefix}_max": np.max(array, axis=1),
            f"{prefix}_median": np.median(array, axis=1),
            f"{prefix}_range": np.ptp(array, axis=1),
            f"{prefix}_non_zero_count": np.sum(non_zero, axis=1),
            f"{prefix}_non_zero_ratio": np.mean(non_zero, axis=1),
            f"{prefix}_peak_position": peak_positions,
            f"{prefix}_peak_value": array[np.arange(len(array)), peak_positions],
            f"{prefix}_first_non_zero": first_non_zero,
            f"{prefix}_last_non_zero": last_non_zero,
            f"{prefix}_area": np.trapezoid(array, axis=1),
        })

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
