"""Subprocess entry for converting trusted platform joblib packages."""

import argparse
import json
import os
from pathlib import Path
import sys

import joblib
import onnx
from catboost import CatBoostClassifier, CatBoostRegressor
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.ensemble import (
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier, XGBRegressor
from onnxmltools import convert_lightgbm, convert_xgboost
from onnxmltools.convert.common.data_types import FloatTensorType as OnnxFloatTensorType
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType


ALLOWED_MODEL_TYPES = {
    LogisticRegression,
    LinearRegression,
    RandomForestClassifier,
    RandomForestRegressor,
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
}

CATBOOST_MODEL_TYPES = {CatBoostClassifier, CatBoostRegressor}
XGBOOST_MODEL_TYPES = {XGBClassifier, XGBRegressor}
LIGHTGBM_MODEL_TYPES = {LGBMClassifier, LGBMRegressor}


class WorkerError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _apply_resource_limits() -> None:
    if sys.platform == "win32":
        return
    try:
        import resource

        page_size = os.sysconf("SC_PAGE_SIZE")
        current_virtual_memory = int(
            Path("/proc/self/statm").read_text(encoding="ascii").split()[0]
        ) * page_size
        memory_limit = max(
            4 * 1024 * 1024 * 1024,
            current_virtual_memory + 2 * 1024 * 1024 * 1024,
        )
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
    model_type = type(model)
    if (
        model_type not in ALLOWED_MODEL_TYPES
        and model_type not in CATBOOST_MODEL_TYPES
        and model_type not in XGBOOST_MODEL_TYPES
        and model_type not in LIGHTGBM_MODEL_TYPES
    ):
        raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
    scaler = package.get("scaler")
    if scaler is not None and type(scaler) is not StandardScaler:
        raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")

    features = _feature_schema(package.get("feature_schema"))
    output = _output_schema(package.get("target_schema"))

    if model_type in CATBOOST_MODEL_TYPES:
        if scaler is not None:
            raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
        try:
            model.save_model(str(destination), format="onnx")
        except Exception:
            raise WorkerError("MODEL_CONVERSION_FAILED") from None
        return {
            "ok": True,
            "converter": "catboost",
            "feature_schema": features,
            "output_schema": output,
            "input_names": [],
            "output_names": [],
            "opset": 0,
        }

    if model_type in XGBOOST_MODEL_TYPES or model_type in LIGHTGBM_MODEL_TYPES:
        if scaler is not None:
            raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
        try:
            converter = convert_xgboost if model_type in XGBOOST_MODEL_TYPES else convert_lightgbm
            converted = converter(
                model,
                initial_types=[
                    ("features", OnnxFloatTensorType([None, len(features)])),
                ],
                target_opset=15,
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            onnx.save_model(converted, str(destination))
        except Exception:
            raise WorkerError("MODEL_CONVERSION_FAILED") from None
        return {
            "ok": True,
            "converter": "xgboost" if model_type in XGBOOST_MODEL_TYPES else "lightgbm",
            "feature_schema": features,
            "output_schema": output,
            "input_names": [item.name for item in converted.graph.input],
            "output_names": [item.name for item in converted.graph.output],
            "opset": max((item.version for item in converted.opset_import), default=0),
        }

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
        "converter": "skl2onnx",
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
