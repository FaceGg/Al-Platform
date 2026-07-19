"""Trusted platform model conversion and ONNX validation."""

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np


@dataclass(frozen=True)
class ConversionResult:
    input_names: tuple[str, ...]
    output_names: tuple[str, ...]
    opset: int
    sha256: str
    size: int
    converter: str
    feature_schema: list[dict[str, str]]
    output_schema: dict[str, object]


class ConversionError(RuntimeError):
    """A conversion failure safe to expose through a stable domain code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _safe_worker_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
    }
    environment = {
        key: value for key, value in os.environ.items()
        if key.upper() in allowed
    }
    backend_root = Path(__file__).resolve().parents[2]
    environment["PYTHONPATH"] = str(backend_root)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def _delete_partial(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _worker_failure_code(result_path: Path) -> str:
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "MODEL_CONVERSION_FAILED"
    code = payload.get("code")
    if code in {"MODEL_CONVERSION_UNSUPPORTED", "MODEL_CONVERSION_FAILED"}:
        return code
    return "MODEL_CONVERSION_FAILED"


def convert_platform_joblib(
    source: Path,
    destination: Path,
    *,
    timeout_seconds: int = 120,
) -> ConversionResult:
    """Convert a provenance-checked platform joblib package in a subprocess."""

    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_file():
        raise ConversionError("MODEL_CONVERSION_FAILED")
    if timeout_seconds <= 0:
        raise ConversionError("MODEL_CONVERSION_FAILED")

    destination.parent.mkdir(parents=True, exist_ok=True)
    _delete_partial(destination)
    with tempfile.TemporaryDirectory(prefix="onnx-conversion-") as temporary:
        temporary_path = Path(temporary)
        result_path = temporary_path / "result.json"
        command = [
            sys.executable,
            "-m",
            "app.services.onnx_worker",
            "--source",
            str(source),
            "--destination",
            str(destination),
            "--result",
            str(result_path),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=temporary_path,
                env=_safe_worker_environment(),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            _delete_partial(destination)
            raise ConversionError("MODEL_CONVERSION_TIMEOUT") from None
        except (OSError, ValueError):
            _delete_partial(destination)
            raise ConversionError("MODEL_CONVERSION_FAILED") from None

        if completed.returncode != 0:
            code = _worker_failure_code(result_path)
            _delete_partial(destination)
            raise ConversionError(code)

        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if payload.get("ok") is not True:
                raise ValueError
            feature_schema = _normalize_feature_schema(payload["feature_schema"])
            output_schema = _normalize_output_schema(payload["output_schema"])
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            _delete_partial(destination)
            raise ConversionError("MODEL_CONVERSION_FAILED") from None

        try:
            validated = validate_onnx(
                destination,
                feature_schema,
                output_schema,
            )
        except ConversionError:
            _delete_partial(destination)
            raise
        return replace(
            validated,
            converter="skl2onnx",
            feature_schema=feature_schema,
            output_schema=output_schema,
        )


def _normalize_feature_schema(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("feature schema is required")
    normalized: list[dict[str, str]] = []
    names: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            name = item.get("name")
            dtype = item.get("dtype")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            name, dtype = item
        else:
            raise ValueError("invalid feature schema")
        name = str(name or "").strip()
        dtype = str(dtype or "").strip().lower()
        if not name or name in names or not dtype:
            raise ValueError("invalid feature schema")
        names.add(name)
        normalized.append({"name": name, "dtype": dtype})
    return normalized


def _normalize_output_schema(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("output schema is required")
    name = str(value.get("name") or "prediction").strip()
    dtype = str(value.get("dtype") or "").strip().lower()
    task = str(value.get("task") or "").strip().lower()
    if not name or not dtype or task not in {"classification", "regression"}:
        raise ValueError("invalid output schema")
    return {**value, "name": name, "dtype": dtype, "task": task}


def _synthetic_input(feature_schema: list[dict[str, str]]) -> np.ndarray:
    numeric_prefixes = ("float", "int", "uint")
    if any(
        not str(feature["dtype"]).lower().startswith(numeric_prefixes)
        for feature in feature_schema
    ):
        raise ConversionError("MODEL_SCHEMA_INVALID")
    return np.zeros((1, len(feature_schema)), dtype=np.float32)


def validate_onnx(
    path: Path,
    feature_schema: list[dict[str, str]],
    output_schema: dict[str, object],
) -> ConversionResult:
    """Validate structure, manifest agreement, and one synthetic inference."""

    import onnx
    import onnxruntime as ort

    path = Path(path)
    try:
        normalized_features = _normalize_feature_schema(feature_schema)
        normalized_output = _normalize_output_schema(output_schema)
    except (TypeError, ValueError):
        raise ConversionError("MODEL_SCHEMA_INVALID") from None

    try:
        model = onnx.load(str(path))
        onnx.checker.check_model(model)
        session = ort.InferenceSession(
            str(path),
            providers=["CPUExecutionProvider"],
        )
    except Exception:
        raise ConversionError("ONNX_INVALID") from None

    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or not outputs:
        raise ConversionError("MODEL_SCHEMA_INVALID")
    input_shape = inputs[0].shape
    if (
        len(input_shape) != 2
        or not isinstance(input_shape[1], int)
        or input_shape[1] != len(normalized_features)
    ):
        raise ConversionError("MODEL_SCHEMA_INVALID")

    synthetic = _synthetic_input(normalized_features)
    try:
        session.run(None, {inputs[0].name: synthetic})
    except Exception:
        raise ConversionError("MODEL_SCHEMA_INVALID") from None

    content = path.read_bytes()
    opset = max((item.version for item in model.opset_import), default=0)
    return ConversionResult(
        input_names=tuple(item.name for item in inputs),
        output_names=tuple(item.name for item in outputs),
        opset=opset,
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
        converter="onnx-validation",
        feature_schema=normalized_features,
        output_schema=normalized_output,
    )
