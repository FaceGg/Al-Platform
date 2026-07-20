"""Thread-safe ONNX session registry and strict prediction execution."""

from dataclasses import dataclass
import math
from pathlib import Path
import threading
from time import perf_counter

import numpy as np
import onnxruntime as ort


MAX_RECORDS = 100


class RuntimeErrorCode(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class LoadedDeployment:
    deployment_id: str
    model_version_id: str
    version_number: int
    storage_uri: str
    sha256: str
    size: int
    feature_schema: tuple[dict[str, str], ...]
    output_schema: dict[str, object]
    input_names: tuple[str, ...]
    output_names: tuple[str, ...]
    session: object

    def identity(self) -> tuple[object, ...]:
        return (
            self.model_version_id,
            self.version_number,
            self.storage_uri,
            self.sha256,
            self.size,
            self.feature_schema,
            self.input_names,
            self.output_names,
        )


class RuntimeRegistry:
    def __init__(self, storage):
        self.storage = storage
        self._lock = threading.RLock()
        self._deployments: dict[str, LoadedDeployment] = {}

    @staticmethod
    def _normalized_spec(spec: dict) -> dict:
        required = {
            "deployment_id",
            "model_version_id",
            "version_number",
            "storage_uri",
            "sha256",
            "size",
            "feature_schema",
            "output_schema",
            "input_names",
            "output_names",
        }
        if set(spec) != required:
            raise RuntimeErrorCode("DEPLOYMENT_SPEC_INVALID")
        features = spec["feature_schema"]
        if not isinstance(features, list) or not features:
            raise RuntimeErrorCode("DEPLOYMENT_SPEC_INVALID")
        normalized_features = []
        names = set()
        for feature in features:
            if not isinstance(feature, dict):
                raise RuntimeErrorCode("DEPLOYMENT_SPEC_INVALID")
            name = str(feature.get("name") or "").strip()
            dtype = str(feature.get("dtype") or "").strip().lower()
            if not name or not dtype or name in names:
                raise RuntimeErrorCode("DEPLOYMENT_SPEC_INVALID")
            names.add(name)
            normalized_features.append({"name": name, "dtype": dtype})
        if not isinstance(spec["output_schema"], dict):
            raise RuntimeErrorCode("DEPLOYMENT_SPEC_INVALID")
        return {
            **spec,
            "deployment_id": str(spec["deployment_id"]),
            "model_version_id": str(spec["model_version_id"]),
            "version_number": int(spec["version_number"]),
            "storage_uri": str(spec["storage_uri"]),
            "sha256": str(spec["sha256"]),
            "size": int(spec["size"]),
            "feature_schema": normalized_features,
            "output_schema": dict(spec["output_schema"]),
            "input_names": [str(item) for item in spec["input_names"]],
            "output_names": [str(item) for item in spec["output_names"]],
        }

    def load(self, spec: dict) -> LoadedDeployment:
        normalized = self._normalized_spec(spec)
        deployment_id = normalized["deployment_id"]
        with self._lock:
            existing = self._deployments.get(deployment_id)
        if existing is not None:
            candidate_identity = (
                normalized["model_version_id"],
                normalized["version_number"],
                normalized["storage_uri"],
                normalized["sha256"],
                normalized["size"],
                tuple(normalized["feature_schema"]),
                tuple(normalized["input_names"]),
                tuple(normalized["output_names"]),
            )
            if existing.identity() != candidate_identity:
                raise RuntimeErrorCode("DEPLOYMENT_SPEC_CONFLICT")
            return existing

        if not self.storage.verify(
            normalized["storage_uri"],
            normalized["sha256"],
            normalized["size"],
        ):
            raise RuntimeErrorCode("MODEL_ARTIFACT_INTEGRITY_FAILED")
        try:
            with self.storage.materialize(normalized["storage_uri"]) as path:
                session = ort.InferenceSession(
                    str(Path(path)),
                    providers=["CPUExecutionProvider"],
                )
        except Exception:
            raise RuntimeErrorCode("MODEL_LOAD_FAILED") from None
        actual_inputs = tuple(item.name for item in session.get_inputs())
        actual_outputs = tuple(item.name for item in session.get_outputs())
        if (
            actual_inputs != tuple(normalized["input_names"])
            or actual_outputs != tuple(normalized["output_names"])
            or len(actual_inputs) != 1
        ):
            raise RuntimeErrorCode("MODEL_SCHEMA_INVALID")
        loaded = LoadedDeployment(
            deployment_id=deployment_id,
            model_version_id=normalized["model_version_id"],
            version_number=normalized["version_number"],
            storage_uri=normalized["storage_uri"],
            sha256=normalized["sha256"],
            size=normalized["size"],
            feature_schema=tuple(normalized["feature_schema"]),
            output_schema=normalized["output_schema"],
            input_names=actual_inputs,
            output_names=actual_outputs,
            session=session,
        )
        with self._lock:
            concurrent = self._deployments.get(deployment_id)
            if concurrent is not None:
                if concurrent.identity() != loaded.identity():
                    raise RuntimeErrorCode("DEPLOYMENT_SPEC_CONFLICT")
                return concurrent
            self._deployments[deployment_id] = loaded
        return loaded

    def unload(self, deployment_id: str) -> bool:
        with self._lock:
            return self._deployments.pop(str(deployment_id), None) is not None

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            values = tuple(self._deployments.values())
        return [
            {
                "deployment_id": item.deployment_id,
                "model_version_id": item.model_version_id,
                "version_number": item.version_number,
            }
            for item in values
        ]

    def _loaded(self, deployment_id: str) -> LoadedDeployment:
        with self._lock:
            loaded = self._deployments.get(str(deployment_id))
        if loaded is None:
            raise RuntimeErrorCode("DEPLOYMENT_NOT_READY")
        return loaded

    @staticmethod
    def _records(loaded: LoadedDeployment, records: object) -> np.ndarray:
        if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
            raise RuntimeErrorCode("INFERENCE_LIMIT_EXCEEDED")
        names = [item["name"] for item in loaded.feature_schema]
        expected = set(names)
        rows = []
        for record in records:
            if not isinstance(record, dict) or set(record) != expected:
                raise RuntimeErrorCode("INFERENCE_SCHEMA_MISMATCH")
            row = []
            for name in names:
                value = record[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise RuntimeErrorCode("INFERENCE_SCHEMA_MISMATCH")
                numeric = float(value)
                if not math.isfinite(numeric):
                    raise RuntimeErrorCode("INFERENCE_SCHEMA_MISMATCH")
                row.append(numeric)
            rows.append(row)
        return np.asarray(rows, dtype=np.float32)

    @staticmethod
    def _json_value(value):
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, list):
            return [RuntimeRegistry._json_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): RuntimeRegistry._json_value(item)
                for key, item in value.items()
            }
        return value

    def predict(self, deployment_id: str, records: object) -> dict[str, object]:
        loaded = self._loaded(deployment_id)
        matrix = self._records(loaded, records)
        started = perf_counter()
        try:
            outputs = loaded.session.run(
                None,
                {loaded.input_names[0]: matrix},
            )
        except Exception:
            raise RuntimeErrorCode("INFERENCE_FAILED") from None
        duration_ms = (perf_counter() - started) * 1000
        if not outputs:
            raise RuntimeErrorCode("INFERENCE_FAILED")
        response = {
            "deployment_id": loaded.deployment_id,
            "model_version_id": loaded.model_version_id,
            "version_number": loaded.version_number,
            "predictions": self._json_value(outputs[0]),
            "duration_ms": round(duration_ms, 3),
        }
        if len(outputs) > 1:
            response["probabilities"] = self._json_value(outputs[1])
        return response
