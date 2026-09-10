"""All-or-nothing offline prediction and annotation runtime."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from app.schemas.dataset_import import ParseOptions
from app.services.data_import import DataImportError, read_dataset_upload
from app.services.input_contract import ValidationReport, validate_input_contract
from app.services.model_export import ExportValidationError, validate_export_package


class InputContractError(ValueError):
    def __init__(self, code: str, details: dict[str, Any] | None = None):
        self.code = code
        self.details = details or {}
        super().__init__(code)


class OutputContractError(ValueError):
    def __init__(self, code: str, details: dict[str, Any] | None = None):
        self.code = code
        self.details = details or {}
        super().__init__(code)


@dataclass(frozen=True)
class OfflineInferenceResult:
    mode: str
    row_count: int
    output_path: Path


def _report_path(output_path: Path) -> Path:
    return output_path.parent / "validation-report.json"


def _write_validation_report(output_path: Path, code: str, details: dict[str, Any] | None = None) -> None:
    # Never echo user column names, sample ids or row contents into a report.
    safe_details = {key: value for key, value in (details or {}).items() if key in {"column_count", "row_count", "source_format"}}
    temporary = _report_path(output_path).with_suffix(".tmp")
    temporary.write_text(json.dumps({"status": "invalid", "code": code, "details": safe_details}, sort_keys=True), encoding="utf-8")
    os.replace(temporary, _report_path(output_path))


def _extract(package: Path, root: Path) -> None:
    with zipfile.ZipFile(package) as archive:
        for info in archive.infolist():
            target = (root / info.filename).resolve()
            if not target.is_relative_to(root.resolve()):
                raise InputContractError("EXPORT_PATH_TRAVERSAL")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info.filename))


def _load_frame(root: Path, input_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    contract = json.loads((root / "contracts/input_contract.json").read_text(encoding="utf-8"))
    parse_contract = contract.get("parse_contract") or {}
    source_format = parse_contract.get("source_format")
    options_payload = parse_contract.get("options") or {}
    try:
        options = ParseOptions(**options_payload)
        normalized = read_dataset_upload(input_path, source_format, options)
    except (DataImportError, ValueError) as error:
        raise InputContractError("INPUT_CONTRACT_MISMATCH", {"source_format": source_format}) from error
    report: ValidationReport = validate_input_contract(normalized.frame, contract)
    if not report.partial_output_allowed or report.code != "OK":
        raise InputContractError("INPUT_CONTRACT_MISMATCH", {"column_count": len(normalized.frame.columns), "row_count": len(normalized.frame)})
    return normalized.frame, contract


def _load_prediction(root: Path, frame: pd.DataFrame, contract: dict[str, Any], output_contract: dict[str, Any]) -> pd.DataFrame:
    model_path = root / "model/model.joblib"
    if not model_path.exists():
        model_path = root / "model/model.onnx"
    if not model_path.exists():
        raise OutputContractError("MODEL_ARTIFACT_MISSING")
    if model_path.suffix == ".onnx":
        try:
            import onnxruntime as ort
        except Exception as error:
            raise OutputContractError("ONNX_RUNTIME_UNAVAILABLE") from error
        session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        feature_columns = list(contract.get("required_columns", []))
        outputs = session.run(None, {session.get_inputs()[0].name: frame[feature_columns].to_numpy(dtype=np.float32)})
        prediction = outputs[0]
    else:
        model = joblib.load(model_path)
        feature_columns = list(contract.get("required_columns", []))
        try:
            prediction = model.predict(frame[feature_columns])
        except Exception as error:
            raise OutputContractError("MODEL_PREDICT_FAILED") from error
    values = np.asarray(prediction)
    if values.ndim == 1:
        values = values.reshape(-1, 1)
    if len(values) != len(frame):
        raise OutputContractError("OUTPUT_ROW_COUNT_MISMATCH")
    if np.issubdtype(values.dtype, np.number) and not np.isfinite(values.astype(float)).all():
        raise OutputContractError("OUTPUT_NONFINITE_VALUE")
    targets = output_contract.get("target_columns") or []
    if len(targets) != values.shape[1]:
        targets = ["prediction"] if values.shape[1] == 1 else [f"prediction_{index}" for index in range(values.shape[1])]
    result = pd.DataFrame(values, columns=targets)
    sample_column = contract.get("sample_id_column")
    if sample_column:
        result.insert(0, sample_column, frame[sample_column].astype(str).to_numpy())
    return result


def _write_output(frame: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    try:
        suffix = output_path.suffix.lower()
        if suffix == ".csv":
            frame.to_csv(temporary, index=False)
        elif suffix in {".xlsx", ".xls"}:
            frame.to_excel(temporary, index=False)
        elif suffix == ".parquet":
            frame.to_parquet(temporary, index=False)
        elif suffix == ".json":
            frame.to_json(temporary, orient="records", date_format="iso")
        else:
            raise OutputContractError("OUTPUT_FORMAT_UNSUPPORTED")
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)


def _run(package: Path, input_path: Path, output_path: Path, *, mode: str, signing_key: str | bytes | None = None) -> OfflineInferenceResult:
    try:
        validate_export_package(package, signing_key=signing_key)
        with tempfile.TemporaryDirectory(prefix="offline-inference-") as temporary:
            root = Path(temporary)
            _extract(package, root)
            frame, contract = _load_frame(root, input_path)
            output_contract = json.loads((root / "contracts/output_contract.json").read_text(encoding="utf-8"))
            if mode == "annotate" and not (root / "annotation/strategy.json").exists():
                raise InputContractError("ANNOTATION_REVISION_REQUIRED")
            predictions = _load_prediction(root, frame, contract, output_contract)
            if mode == "annotate":
                strategy = json.loads((root / "annotation/strategy.json").read_text(encoding="utf-8"))
                predictions["annotation_status"] = "needs_review" if strategy.get("strategy") == "rule" and not strategy.get("rules") else "predicted"
            _write_output(predictions, output_path)
            _report_path(output_path).unlink(missing_ok=True)
            return OfflineInferenceResult(mode=mode, row_count=len(predictions), output_path=output_path)
    except (InputContractError, OutputContractError, ExportValidationError):
        error = locals().get("error")
        code = getattr(error, "code", "OFFLINE_INFERENCE_FAILED")
        _write_validation_report(output_path, code)
        raise
    except Exception as error:
        _write_validation_report(output_path, "OFFLINE_INFERENCE_FAILED")
        raise OutputContractError("OFFLINE_INFERENCE_FAILED") from error


def run_offline_predict(
    package: str | Path,
    input_path: str | Path,
    output_path: str | Path,
    *,
    signing_key: str | bytes | None = None,
) -> OfflineInferenceResult:
    return _run(Path(package), Path(input_path), Path(output_path), mode="predict", signing_key=signing_key)


def run_offline_annotate(
    package: str | Path,
    input_path: str | Path,
    output_path: str | Path,
    *,
    signing_key: str | bytes | None = None,
) -> OfflineInferenceResult:
    return _run(Path(package), Path(input_path), Path(output_path), mode="annotate", signing_key=signing_key)

