"""Subprocess entry for converting trusted platform joblib packages."""

import argparse
import json
from pathlib import Path
import sys

import joblib
import onnx
from sklearn.ensemble import (
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType


ALLOWED_MODEL_TYPES = {
    LogisticRegression,
    LinearRegression,
    RandomForestClassifier,
    RandomForestRegressor,
    GradientBoostingClassifier,
    GradientBoostingRegressor,
}


class WorkerError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _apply_resource_limits() -> None:
    if sys.platform == "win32":
        return
    try:
        import resource

        memory_limit = 2 * 1024 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
        resource.setrlimit(resource.RLIMIT_CPU, (110, 110))
    except (ImportError, OSError, ValueError):
        return


def _feature_schema(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise WorkerError("MODEL_CONVERSION_FAILED")
    normalized: list[dict[str, str]] = []
    names: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            name, dtype = item.get("name"), item.get("dtype")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            name, dtype = item
        else:
            raise WorkerError("MODEL_CONVERSION_FAILED")
        name = str(name or "").strip()
        dtype = str(dtype or "").strip().lower()
        if not name or not dtype or name in names:
            raise WorkerError("MODEL_CONVERSION_FAILED")
        names.add(name)
        normalized.append({"name": name, "dtype": dtype})
    return normalized


def _output_schema(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WorkerError("MODEL_CONVERSION_FAILED")
    name = str(value.get("name") or "prediction").strip()
    dtype = str(value.get("dtype") or "").strip().lower()
    task = str(value.get("task") or "").strip().lower()
    if not name or not dtype or task not in {"classification", "regression"}:
        raise WorkerError("MODEL_CONVERSION_FAILED")
    return {**value, "name": name, "dtype": dtype, "task": task}


def _convert(source: Path, destination: Path) -> dict[str, object]:
    try:
        package = joblib.load(source)
    except Exception:
        raise WorkerError("MODEL_CONVERSION_FAILED") from None
    if not isinstance(package, dict):
        raise WorkerError("MODEL_CONVERSION_FAILED")

    model = package.get("model")
    if model is None:
        raise WorkerError("MODEL_CONVERSION_FAILED")
    if type(model) not in ALLOWED_MODEL_TYPES:
        raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
    scaler = package.get("scaler")
    if scaler is not None and type(scaler) is not StandardScaler:
        raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")

    features = _feature_schema(package.get("feature_schema"))
    output = _output_schema(package.get("target_schema"))
    estimator = model
    if scaler is not None:
        estimator = Pipeline([("scaler", scaler), ("model", model)])

    options = None
    if output["task"] == "classification":
        options = {id(model): {"zipmap": False}}
    try:
        converted = convert_sklearn(
            estimator,
            initial_types=[
                ("features", FloatTensorType([None, len(features)])),
            ],
            target_opset=17,
            options=options,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        onnx.save_model(converted, str(destination))
    except Exception:
        raise WorkerError("MODEL_CONVERSION_FAILED") from None

    return {
        "ok": True,
        "feature_schema": features,
        "output_schema": output,
        "input_names": [item.name for item in converted.graph.input],
        "output_names": [item.name for item in converted.graph.output],
        "opset": max(
            (item.version for item in converted.opset_import),
            default=0,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    arguments = parser.parse_args(argv)
    _apply_resource_limits()

    try:
        payload = _convert(arguments.source, arguments.destination)
        return_code = 0
    except WorkerError as error:
        payload = {"ok": False, "code": error.code}
        return_code = 2
        try:
            arguments.destination.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        arguments.result.write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )
    except (OSError, UnicodeError):
        return 3
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
