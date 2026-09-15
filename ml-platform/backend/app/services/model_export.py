"""Deterministic, signed model packages for offline inference.

The package builder deliberately accepts a model-version-like object as well as
the ORM model.  This keeps the file-level contract testable without weakening
the project-scoped service that resolves ORM artifacts in the API layer.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


EXPORT_TOOL_VERSION = "1.0.0"
REQUIRED_PACKAGE_FILES = {
    "manifest.json",
    "checksums.json",
    "security/sbom.spdx.json",
    "security/manifest.sig",
    "contracts/input_contract.json",
    "contracts/output_contract.json",
    "runtime/inference.py",
    "runtime/cli.py",
    "runtime/requirements.lock",
    "runtime/README-runtime.md",
}
CHECKSUM_METADATA_FILES = {"checksums.json", "security/manifest.sig"}
FORBIDDEN_NAME_PARTS = {
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
    "user",
    "sample",
    "label_data",
}


class ExportError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


class ExportValidationError(ExportError):
    pass


@dataclass(frozen=True)
class ExportResult:
    path: Path
    manifest: dict[str, Any]
    export_id: str


@dataclass(frozen=True)
class ExportValidationReport:
    valid: bool
    files: tuple[str, ...] = ()
    errors: tuple[dict[str, Any], ...] = ()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    return str(value)


def _signing_key(value: str | bytes | None) -> Ed25519PrivateKey:
    if value is None:
        value = os.environ.get("MODEL_EXPORT_SIGNING_KEY")
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ExportError("EXPORT_SIGNING_KEY_UNAVAILABLE")
    raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(raw).digest())


def _artifact_path(version: Any) -> Path:
    candidates: list[Any] = []
    for name in ("source_artifact_path", "model_path", "artifact_path"):
        candidates.append(getattr(version, name, None))
    for name in ("source_artifact", "onnx_artifact"):
        artifact = getattr(version, name, None)
        if artifact is not None:
            if isinstance(artifact, Mapping):
                candidates.append(artifact)
            else:
                candidates.extend((getattr(artifact, "storage_path", None), getattr(artifact, "storage_uri", None)))
    metadata = getattr(version, "conversion_metadata", None) or {}
    candidates.extend((metadata.get("artifact_path"), metadata.get("model_path")))
    for candidate in candidates:
        references = [candidate]
        if isinstance(candidate, Mapping):
            references = [candidate.get(name) for name in ("storage_path", "storage_uri", "artifact_path", "model_path", "path")]
        for reference in references:
            if not reference:
                continue
            value = str(reference)
            if value.startswith("file://"):
                value = value[7:]
            path = Path(value).expanduser()
            if path.is_file():
                return path.resolve()
    raise ExportError("MODEL_ARTIFACT_UNAVAILABLE")


def _ensure_exportable(version: Any) -> None:
    approval = getattr(version, "approval_status", None)
    if approval is not None and approval not in {"approved", "stable", "published"}:
        raise ExportError("MODEL_VERSION_NOT_APPROVED")
    lifecycle = getattr(version, "lifecycle_state", None)
    if lifecycle is not None and lifecycle in {"failed", "rejected", "archived", "disabled"}:
        raise ExportError("MODEL_VERSION_NOT_EXPORTABLE")


def _write_json(root: Path, relative: str, payload: Any) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_canonical(payload))


def _safe_requirements() -> str:
    return (
        "cryptography==50.0.1\n"
        "defusedxml==0.7.1\n"
        "joblib==1.5.3\n"
        "numpy==2.3.5\n"
        "onnxruntime==1.24.4\n"
        "openpyxl==3.1.5\n"
        "pandas==2.3.3\n"
        "pyarrow==23.0.1\n"
        "scikit-learn==1.7.2\n"
        "xlrd==2.0.2\n"
    )


def _runtime_security_source() -> str:
    return '''"""Package authentication and checksum validation."""

from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


CHECKSUM_METADATA_FILES = {"checksums.json", "security/manifest.sig"}
REQUIRED_FILES = {
    "manifest.json",
    "checksums.json",
    "security/sbom.spdx.json",
    "security/manifest.sig",
    "contracts/input_contract.json",
    "contracts/output_contract.json",
}


class PackageValidationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validate_names(names: tuple[str, ...]) -> None:
    if any(name.startswith("/") or ".." in Path(name).parts for name in names):
        raise PackageValidationError("EXPORT_PATH_TRAVERSAL")
    if REQUIRED_FILES - set(names):
        raise PackageValidationError("EXPORT_REQUIRED_FILE_MISSING")


def validate_package(package: str | Path) -> tuple[str, ...]:
    path = Path(package)
    if path.is_dir():
        names = tuple(sorted(item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_file()))
        _validate_names(names)
        read = lambda name: (path / name).read_bytes()
    else:
        try:
            archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as error:
            raise PackageValidationError("EXPORT_PACKAGE_INVALID") from error
        names = tuple(sorted(archive.namelist()))
        _validate_names(names)
        read = archive.read
    try:
        manifest_bytes = read("manifest.json")
        checksums_bytes = read("checksums.json")
        checksums = json.loads(checksums_bytes)
        if not isinstance(checksums, dict) or not checksums:
            raise PackageValidationError("EXPORT_CHECKSUMS_INVALID")
        expected = set(names) - CHECKSUM_METADATA_FILES
        if set(checksums) != expected:
            raise PackageValidationError("EXPORT_CHECKSUM_COVERAGE_INCOMPLETE")
        for name, digest in checksums.items():
            if not isinstance(name, str) or not isinstance(digest, str) or _sha256(read(name)) != digest:
                raise PackageValidationError("EXPORT_CHECKSUM_MISMATCH")
        signature = json.loads(read("security/manifest.sig"))
        public_key = base64.b64decode(signature["public_key"], validate=True)
        signed = base64.b64decode(signature["signature"], validate=True)
        Ed25519PublicKey.from_public_bytes(public_key).verify(signed, manifest_bytes + bytes((10,)) + checksums_bytes)
        manifest = json.loads(manifest_bytes)
        if manifest.get("manifest_version") != 1:
            raise PackageValidationError("EXPORT_MANIFEST_INVALID")
        return names
    except PackageValidationError:
        raise
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, InvalidSignature) as error:
        raise PackageValidationError("EXPORT_SIGNATURE_INVALID") from error
    finally:
        if not path.is_dir():
            archive.close()


def extract_package(package: str | Path, root: Path) -> None:
    path = Path(package)
    if path.is_dir():
        for name in validate_package(path):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path / name, target)
        return
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            target = (root / info.filename).resolve()
            if not target.is_relative_to(root.resolve()):
                raise PackageValidationError("EXPORT_PATH_TRAVERSAL")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info.filename))
'''


def _runtime_data_import_source() -> str:
    return '''"""Standalone copy of the platform's bounded dataset parser."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class DataImportError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ParseOptions:
    sample_id_column: str | None = None
    record_path: str | None = None
    max_file_bytes: int = 1_000_000_000
    max_decompressed_bytes: int = 4_000_000_000
    max_rows: int = 1_000_000
    max_columns: int = 200
    max_depth: int = 32
    max_field_bytes: int = 64 * 1024
    max_time_seconds: float = 300.0
    encoding: str = "utf-8-sig"
    delimiter: str = ","
    has_header: bool = True
    sheet_name: int | str = 0

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "ParseOptions":
        payload = dict(payload or {})
        allowed = {field for field in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in payload.items() if key in allowed})


@dataclass(frozen=True)
class NormalizedTable:
    frame: pd.DataFrame
    parse_contract: dict[str, Any]


def _depth(value: Any, level: int = 0) -> int:
    if isinstance(value, dict):
        return max([level] + [_depth(item, level + 1) for item in value.values()])
    if isinstance(value, list):
        return max([level] + [_depth(item, level + 1) for item in value])
    return level


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DataImportError("DATA_PARSE_DUPLICATE_KEY")
        result[key] = value
    return result


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _sniff_source_format(path: Path) -> str:
    raw = path.read_bytes()[:4096]
    stripped = raw.lstrip()
    if raw.startswith(b"PAR1"):
        return "parquet"
    if stripped.startswith((b"[", b"{")):
        return "json"
    if stripped.startswith(b"<"):
        return "xml"
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            if "[Content_Types].xml" in set(archive.namelist()):
                return "excel"
    return "csv"


def _decompressed_size(path: Path) -> int:
    if not zipfile.is_zipfile(path):
        return path.stat().st_size
    with zipfile.ZipFile(path) as archive:
        return sum(item.file_size for item in archive.infolist())


def _check_frame(frame: pd.DataFrame, options: ParseOptions) -> None:
    if len(frame) > options.max_rows:
        raise DataImportError("DATA_LIMIT_ROWS")
    if len(frame.columns) > options.max_columns:
        raise DataImportError("DATA_LIMIT_COLUMNS")
    if len(set(map(str, frame.columns))) != len(frame.columns):
        raise DataImportError("DATA_PARSE_DUPLICATE_COLUMN")
    for column in frame.columns:
        for value in frame[column]:
            if value is not None and len(str(value).encode("utf-8")) > options.max_field_bytes:
                raise DataImportError("DATA_LIMIT_FIELD_BYTES")


def _json_records(path: Path, options: ParseOptions) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except DataImportError:
        raise
    except Exception as error:
        raise DataImportError("DATA_PARSE_INVALID") from error
    if _depth(value) > options.max_depth:
        raise DataImportError("DATA_LIMIT_DEPTH")
    if options.record_path:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", options.record_path):
            raise DataImportError("DATA_PARSE_UNSAFE_PATH")
        for part in options.record_path.split("."):
            if not isinstance(value, dict) or part not in value:
                raise DataImportError("DATA_PARSE_INVALID")
            value = value[part]
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise DataImportError("DATA_PARSE_INVALID")
    if any(not _scalar(item) for row in value for item in row.values()):
        raise DataImportError("DATA_PARSE_NON_SCALAR")
    kinds: dict[str, set[str]] = {}
    for row in value:
        for key, item in row.items():
            if item is None:
                continue
            kind = "bool" if isinstance(item, bool) else "number" if isinstance(item, (int, float)) else "string"
            kinds.setdefault(key, set()).add(kind)
    if any(len(values) > 1 for values in kinds.values()):
        raise DataImportError("DATA_PARSE_INCOMPATIBLE_COLUMN_TYPE")
    return value


def _xml_records(path: Path, options: ParseOptions) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if len(raw) > options.max_decompressed_bytes or re.search(br"<!DOCTYPE|<!ENTITY|SYSTEM\s+|PUBLIC\s+", raw, re.I):
        raise DataImportError("DATA_PARSE_UNSAFE_XML")
    try:
        from defusedxml import ElementTree
        root = ElementTree.parse(path).getroot()
    except Exception as error:
        raise DataImportError("DATA_PARSE_UNSAFE_XML") from error
    record_path = options.record_path or ".//record"
    if not re.fullmatch(r"(?:\.//)?[A-Za-z_][A-Za-z0-9_.-]*(?:/[A-Za-z_][A-Za-z0-9_.-]*)*", record_path):
        raise DataImportError("DATA_PARSE_UNSAFE_PATH")
    nodes = root.findall(record_path)
    if not nodes:
        raise DataImportError("DATA_PARSE_INVALID")
    records = []
    expected_columns = None
    for node in nodes:
        row = dict(node.attrib)
        for child in list(node):
            if list(child) or child.tag in row:
                raise DataImportError("DATA_PARSE_NON_SCALAR")
            row[child.tag] = child.text
        if expected_columns is None:
            expected_columns = set(row)
        elif set(row) != expected_columns:
            raise DataImportError("DATA_PARSE_DUPLICATE_COLUMN")
        records.append(row)
    return records


def read_dataset_upload(path: Path, source_format: str | None, options: ParseOptions) -> NormalizedTable:
    started = time.monotonic()
    if not path.is_file() or path.stat().st_size > options.max_file_bytes:
        raise DataImportError("DATA_LIMIT_FILE_BYTES")
    if _decompressed_size(path) > options.max_decompressed_bytes:
        raise DataImportError("DATA_LIMIT_DECOMPRESSED_BYTES")
    detected = _sniff_source_format(path)
    source_format = detected if source_format is None else source_format.lower().lstrip(".")
    if source_format in {"xlsx", "xls"}:
        source_format = "excel"
    if source_format != detected:
        raise DataImportError("DATA_FORMAT_MISMATCH")
    try:
        if source_format == "csv":
            header = path.read_text(encoding="utf-8-sig").splitlines()[0]
            columns = next(csv.reader([header]))
            if len(set(columns)) != len(columns):
                raise DataImportError("DATA_PARSE_DUPLICATE_COLUMN")
            frame = pd.read_csv(path, sep=options.delimiter, encoding=options.encoding, header=0 if options.has_header else None)
            if not options.has_header:
                frame.columns = [f"column_{index}" for index in range(len(frame.columns))]
        elif source_format == "excel":
            frame = pd.read_excel(path, sheet_name=options.sheet_name)
        elif source_format == "parquet":
            frame = pd.read_parquet(path)
        elif source_format == "json":
            frame = pd.DataFrame(_json_records(path, options))
        elif source_format == "xml":
            frame = pd.DataFrame(_xml_records(path, options))
        else:
            raise DataImportError("DATA_PARSE_UNSUPPORTED_FORMAT")
    except DataImportError:
        raise
    except Exception as error:
        raise DataImportError("DATA_PARSE_INVALID") from error
    frame.columns = [str(column) for column in frame.columns]
    if time.monotonic() - started > options.max_time_seconds:
        raise DataImportError("DATA_LIMIT_TIME")
    _check_frame(frame, options)
    sample_ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"dataset:{hashlib.sha256(frame.to_json(orient='records').encode()).hexdigest()}:{index}")) for index in range(len(frame))]
    if options.sample_id_column:
        if options.sample_id_column not in frame:
            raise DataImportError("DATA_SAMPLE_ID_INVALID")
        values = frame[options.sample_id_column].tolist()
        if any(value is None or pd.isna(value) or not str(value).strip() for value in values):
            raise DataImportError("DATA_SAMPLE_ID_INVALID")
        sample_ids = [str(value) for value in values]
        if len(set(sample_ids)) != len(sample_ids):
            raise DataImportError("DATA_SAMPLE_ID_NOT_UNIQUE")
    return NormalizedTable(frame, {"sample_ids": sample_ids, "source_format": source_format})
'''


def _runtime_input_contract_source() -> str:
    return '''"""Standalone input contract validation shared by offline modes."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


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


def validate_input_contract(frame: pd.DataFrame, contract: dict[str, Any]) -> str:
    required = list(contract.get("required_columns", []))
    missing = [name for name in required if name not in frame.columns]
    if missing:
        return "INPUT_REQUIRED_COLUMN_MISSING"
    for name, spec in contract.get("columns", {}).items():
        if name not in frame.columns:
            continue
        series = frame[name]
        if spec.get("missing_policy", "allow") == "reject" and series.isna().any():
            return "INPUT_NULL_VALUE"
        if not _dtype_matches(series.dropna(), spec.get("dtype", str(series.dtype))):
            return "INPUT_DTYPE_MISMATCH"
        if pd.api.types.is_numeric_dtype(series):
            values = series.dropna().to_numpy(dtype=float)
            if not np.isfinite(values).all():
                return "INPUT_NONFINITE_FLOAT"
        if spec.get("min_value") is not None and (series.dropna() < spec["min_value"]).any():
            return "INPUT_RANGE_INVALID"
        if spec.get("max_value") is not None and (series.dropna() > spec["max_value"]).any():
            return "INPUT_RANGE_INVALID"
    sample_column = contract.get("sample_id_column")
    if sample_column:
        if sample_column not in frame:
            return "INPUT_SAMPLE_ID_INVALID"
        values = frame[sample_column]
        if values.isna().any() or values.astype(str).str.strip().eq("").any() or values.astype(str).duplicated().any():
            return "INPUT_SAMPLE_ID_INVALID"
    return "OK"
'''


def _runtime_inference_source() -> str:
    return '''"""Standalone predict/annotate implementation for an export package."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import tempfile
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
import zipfile

import joblib
import numpy as np
import pandas as pd

from .data_import import DataImportError, ParseOptions, read_dataset_upload
from .input_contract import validate_input_contract
from .package_security import PackageValidationError, extract_package, validate_package


class InputContractError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class OutputContractError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OfflineInferenceResult:
    mode: str
    row_count: int
    output_path: Path


def _report_path(output_path: Path) -> Path:
    return output_path.parent / "validation-report.json"


def _write_validation_report(output_path: Path, code: str, details: dict[str, Any] | None = None) -> None:
    safe = {key: value for key, value in (details or {}).items() if key in {"column_count", "row_count", "source_format"}}
    temporary = _report_path(output_path).with_suffix(".tmp")
    temporary.write_text(json.dumps({"status": "invalid", "code": code, "details": safe}, sort_keys=True), encoding="utf-8")
    os.replace(temporary, _report_path(output_path))


@contextmanager
def _package_root(package: Path) -> Iterator[Path]:
    validate_package(package)
    with tempfile.TemporaryDirectory(prefix="offline-inference-") as temporary:
        root = Path(temporary)
        extract_package(package, root)
        yield root


def _load_frame(root: Path, input_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    contract = json.loads((root / "contracts/input_contract.json").read_text(encoding="utf-8"))
    parse_contract = contract.get("parse_contract") or {}
    options_payload = dict(parse_contract.get("options") or {})
    options_payload.setdefault("sample_id_column", contract.get("sample_id_column"))
    try:
        normalized = read_dataset_upload(input_path, parse_contract.get("source_format"), ParseOptions.from_payload(options_payload))
    except DataImportError as error:
        raise InputContractError(error.code) from error
    result = validate_input_contract(normalized.frame, contract)
    if result != "OK":
        raise InputContractError(result,)
    return normalized.frame, contract


def _load_prediction(root: Path, frame: pd.DataFrame, contract: dict[str, Any], output_contract: dict[str, Any]) -> pd.DataFrame:
    model_path = root / "model/model.joblib"
    if not model_path.exists():
        model_path = root / "model/model.onnx"
    if not model_path.exists():
        raise OutputContractError("MODEL_ARTIFACT_MISSING")
    feature_columns = list(contract.get("required_columns") or [])
    try:
        if model_path.suffix == ".onnx":
            import onnxruntime as ort
            session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
            values = np.asarray(session.run(None, {session.get_inputs()[0].name: frame[feature_columns].to_numpy(dtype=np.float32)})[0])
        else:
            values = np.asarray(joblib.load(model_path).predict(frame[feature_columns]))
    except Exception as error:
        raise OutputContractError("MODEL_PREDICT_FAILED") from error
    if values.ndim == 1:
        values = values.reshape(-1, 1)
    if values.ndim != 2 or len(values) != len(frame):
        raise OutputContractError("OUTPUT_ROW_COUNT_MISMATCH")
    if np.issubdtype(values.dtype, np.number) and not np.isfinite(values.astype(float)).all():
        raise OutputContractError("OUTPUT_NONFINITE_VALUE")
    targets = output_contract.get("target_columns")
    if not isinstance(targets, list) or len(targets) != values.shape[1] or any(not isinstance(target, str) or not target for target in targets):
        raise OutputContractError("OUTPUT_CONTRACT_MISMATCH")
    result = pd.DataFrame(values, columns=targets)
    sample_column = contract.get("sample_id_column")
    if sample_column:
        result.insert(0, sample_column, frame[sample_column].astype(str).to_numpy())
    return result


def _matches_rule(row: pd.Series, when: dict[str, Any]) -> bool:
    for column, condition in when.items():
        if column not in row:
            return False
        value = row[column]
        if isinstance(condition, dict):
            for operator, expected in condition.items():
                if operator == "eq" and value != expected:
                    return False
                if operator == "ne" and value == expected:
                    return False
                if operator == "gt" and not value > expected:
                    return False
                if operator == "gte" and not value >= expected:
                    return False
                if operator == "lt" and not value < expected:
                    return False
                if operator == "lte" and not value <= expected:
                    return False
                if operator == "in" and value not in expected:
                    return False
        elif value != condition:
            return False
    return True


def _apply_annotation_strategy(root: Path, frame: pd.DataFrame, predictions: pd.DataFrame) -> pd.DataFrame:
    strategy = json.loads((root / "annotation/strategy.json").read_text(encoding="utf-8"))
    rules_payload = json.loads((root / "annotation/rules.json").read_text(encoding="utf-8"))
    cluster_mappings = json.loads((root / "annotation/cluster_label_mappings.json").read_text(encoding="utf-8"))
    cluster_artifacts = json.loads((root / "annotation/cluster_artifacts.json").read_text(encoding="utf-8"))
    name = strategy.get("strategy")
    if name not in {"model", "rule", "cluster", "cluster_rule"}:
        raise InputContractError("ANNOTATION_STRATEGY_INVALID")
    target_columns = list(predictions.columns)
    sample_column = None
    for candidate in ("sample_id", "id"):
        if candidate in target_columns:
            sample_column = candidate
            target_columns.remove(candidate)
            break
    rules = rules_payload.get("rules") if isinstance(rules_payload, dict) else rules_payload
    rules = rules if isinstance(rules, list) else []
    other = strategy.get("other_values") or rules_payload.get("other_values") if isinstance(rules_payload, dict) else strategy.get("other_values")
    assignments = cluster_artifacts.get("assignments") if isinstance(cluster_artifacts, dict) else None
    if name in {"cluster", "cluster_rule"} and (not isinstance(assignments, dict) or not cluster_mappings):
        raise InputContractError("ANNOTATION_CLUSTER_ARTIFACT_INVALID")
    statuses = []
    for index, row in frame.reset_index(drop=True).iterrows():
        status = "predicted" if name == "model" else "needs_review"
        row_values = {column: predictions.iloc[index][column] for column in target_columns}
        matched = [rule for rule in rules if isinstance(rule, dict) and _matches_rule(row, rule.get("when") or {})]
        if name in {"rule", "cluster_rule"} and matched:
            for rule in matched:
                for column, value in (rule.get("values") or {}).items():
                    if column in row_values:
                        row_values[column] = value
            status = "ready"
        if name in {"cluster", "cluster_rule"}:
            cluster_id = assignments.get(str(row.get("sample_id")))
            mapping = cluster_mappings.get(str(cluster_id))
            if isinstance(mapping, dict):
                row_values.update({column: value for column, value in mapping.items() if column in row_values})
            elif len(target_columns) == 1 and mapping is not None:
                row_values[target_columns[0]] = mapping
            status = "ready" if mapping is not None else "needs_review"
        if name != "model" and not matched and isinstance(other, dict):
            for column, value in other.items():
                if column in row_values:
                    row_values[column] = value
        for column, value in row_values.items():
            predictions.iloc[index, predictions.columns.get_loc(column)] = value
        statuses.append(status)
    predictions["annotation_status"] = statuses
    return predictions


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
        elif suffix == ".xml":
            root = ElementTree.Element("records")
            for record in frame.to_dict(orient="records"):
                item = ElementTree.SubElement(root, "record")
                for key, value in record.items():
                    child = ElementTree.SubElement(item, str(key))
                    child.text = "" if pd.isna(value) else str(value)
            ElementTree.ElementTree(root).write(temporary, encoding="utf-8", xml_declaration=True)
        else:
            raise OutputContractError("OUTPUT_FORMAT_UNSUPPORTED")
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)


def _run(package: Path, input_path: Path, output_path: Path, *, mode: str) -> OfflineInferenceResult:
    try:
        with _package_root(package) as root:
            frame, contract = _load_frame(root, input_path)
            output_contract = json.loads((root / "contracts/output_contract.json").read_text(encoding="utf-8"))
            predictions = _load_prediction(root, frame, contract, output_contract)
            if mode == "annotate":
                if not all((root / f"annotation/{name}.json").exists() for name in ("strategy", "cluster_method", "cluster_artifacts", "cluster_label_mappings", "rules")):
                    raise InputContractError("ANNOTATION_REVISION_REQUIRED")
                predictions = _apply_annotation_strategy(root, frame, predictions)
            _write_output(predictions, output_path)
            _report_path(output_path).unlink(missing_ok=True)
            return OfflineInferenceResult(mode=mode, row_count=len(predictions), output_path=output_path)
    except (InputContractError, OutputContractError, PackageValidationError) as error:
        _write_validation_report(output_path, getattr(error, "code", "OFFLINE_INFERENCE_FAILED"))
        raise
    except Exception as error:
        _write_validation_report(output_path, "OFFLINE_INFERENCE_FAILED")
        raise OutputContractError("OFFLINE_INFERENCE_FAILED") from error


def run_offline_predict(package: str | Path, input_path: str | Path, output_path: str | Path) -> OfflineInferenceResult:
    return _run(Path(package), Path(input_path), Path(output_path), mode="predict")


def run_offline_annotate(package: str | Path, input_path: str | Path, output_path: str | Path) -> OfflineInferenceResult:
    return _run(Path(package), Path(input_path), Path(output_path), mode="annotate")
'''


def _runtime_source() -> str:
    return '''"""Generated runtime entry points backed by the private runtime package."""

from __future__ import annotations

from pathlib import Path

from runtime_package.offline_inference import run_offline_annotate, run_offline_predict


def predict(package: str | Path, input_path: str | Path, output_path: str | Path):
    return run_offline_predict(package, input_path, output_path)


def annotate(package: str | Path, input_path: str | Path, output_path: str | Path):
    return run_offline_annotate(package, input_path, output_path)
'''


def _runtime_cli_source() -> str:
    return '''"""Command-line entry point for a self-contained model export."""

from __future__ import annotations

import argparse
import sys

from inference import annotate, predict
from runtime_package.offline_inference import InputContractError, OutputContractError
from runtime_package.package_security import PackageValidationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="model-runtime")
    parser.add_argument("mode", choices=("predict", "annotate"))
    parser.add_argument("--package", required=True)
    parser.add_argument("--input", required=True, dest="input_path")
    parser.add_argument("--output", required=True, dest="output_path")
    args = parser.parse_args(argv)
    try:
        runner = annotate if args.mode == "annotate" else predict
        runner(args.package, args.input_path, args.output_path)
    except (InputContractError, OutputContractError, PackageValidationError) as error:
        print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _runtime_readme() -> str:
    return """# Offline model runtime

Extract the export package and install the locked dependencies from this directory:

    python -m pip install -r requirements.lock
    python cli.py predict --package ../model-export.zip --input input.csv --output predictions.csv

Use `annotate` instead of `predict` for a package that contains an annotation revision.
The runtime is self-contained and does not require the platform source tree.
"""


def _runtime_readme_root() -> str:
    return """# Signed model export

This package contains the model, immutable input/output contracts, and a private
runtime package. Validate the signature and checksums before deserializing the
model. Do not add data, credentials, or platform source files to this archive.
"""


def _build_sbom(root: Path) -> None:
    packages = []
    for name, version in (
        ("cryptography", "50.0.1"),
        ("defusedxml", "0.7.1"),
        ("joblib", "1.5.3"),
        ("numpy", "2.3.5"),
        ("onnxruntime", "1.24.4"),
        ("openpyxl", "3.1.5"),
        ("pandas", "2.3.3"),
        ("pyarrow", "23.0.1"),
        ("scikit-learn", "1.7.2"),
        ("xlrd", "2.0.2"),
    ):
        packages.append({"SPDXID": f"SPDXRef-Package-{name}", "name": name, "versionInfo": version})
    _write_json(
        root,
        "security/sbom.spdx.json",
        {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "model-export-sbom",
            "documentNamespace": f"urn:uuid:{uuid.uuid4()}",
            "packages": packages,
        },
    )


def _zip_directory(root: Path, target: Path, filenames: Iterable[str]) -> None:
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename in sorted(filenames):
                archive.writestr(filename, (root / filename).read_bytes())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_export_package(
    model_version: Any,
    *,
    output_dir: str | Path,
    include_runtime: bool = True,
    signing_key: str | bytes | None = None,
    annotation_task_revision: int | str | None = None,
) -> ExportResult:
    """Build and atomically publish one signed package."""

    _ensure_exportable(model_version)
    key = _signing_key(signing_key)
    export_id = str(uuid.uuid4())
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=f"model-export-{export_id}-", dir=destination))
    try:
        model_path = _artifact_path(model_version)
        model_suffix = model_path.suffix.lower() or ".bin"
        model_name = "model/model.onnx" if model_suffix == ".onnx" else "model/model.joblib"
        (temporary_root / "model").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(model_path, temporary_root / model_name)

        metadata = _jsonable(getattr(model_version, "conversion_metadata", None) or {})
        input_contract = metadata.get("input_contract") or metadata.get("input_contract_json") or {}
        output_contract = _jsonable(getattr(model_version, "output_schema", None) or {})
        _write_json(temporary_root, "contracts/input_contract.json", input_contract)
        _write_json(temporary_root, "contracts/output_contract.json", output_contract)
        _write_json(temporary_root, "preprocessing/preprocessing.json", metadata.get("preprocessing") or {})
        _write_json(temporary_root, "mappings/mappings.json", metadata.get("mappings") or {})
        # A published export is always independently runnable; preserve the
        # argument for API compatibility while no longer emitting partial ZIPs.
        del include_runtime
        runtime_root = temporary_root / "runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        (runtime_root / "inference.py").write_text(_runtime_source(), encoding="utf-8")
        (runtime_root / "cli.py").write_text(_runtime_cli_source(), encoding="utf-8")
        (runtime_root / "requirements.lock").write_text(_safe_requirements(), encoding="utf-8")
        (runtime_root / "README-runtime.md").write_text(_runtime_readme(), encoding="utf-8")
        package_root = runtime_root / "runtime_package"
        package_root.mkdir(parents=True, exist_ok=True)
        (package_root / "__init__.py").write_text(
            '"""Private runtime implementation for this export package."""\n',
            encoding="utf-8",
        )
        (package_root / "package_security.py").write_text(_runtime_security_source(), encoding="utf-8")
        (package_root / "data_import.py").write_text(_runtime_data_import_source(), encoding="utf-8")
        (package_root / "input_contract.py").write_text(_runtime_input_contract_source(), encoding="utf-8")
        (package_root / "offline_inference.py").write_text(
            _runtime_inference_source(),
            encoding="utf-8",
        )
        (temporary_root / "README.md").write_text(
            "# Signed model export\n\n"
            "Validate `manifest.json`, `checksums.json`, and `security/manifest.sig` "
            "before using the private runtime.\n"
            "The package contains no source data, credentials, or platform modules.\n",
            encoding="utf-8",
        )

        if annotation_task_revision is not None:
            annotation = metadata.get("annotation") or {}
            _write_json(temporary_root, "annotation/strategy.json", annotation.get("strategy") or {})
            _write_json(temporary_root, "annotation/cluster_method.json", annotation.get("cluster_method") or {})
            _write_json(temporary_root, "annotation/cluster_artifacts.json", annotation.get("cluster_artifacts") or {})
            _write_json(
                temporary_root,
                "annotation/cluster_label_mappings.json",
                annotation.get("cluster_label_mappings") or {},
            )
            _write_json(temporary_root, "annotation/rules.json", annotation.get("rules") or {})

        _build_sbom(temporary_root)
        manifest = {
            "manifest_version": 1,
            "export_tool_version": EXPORT_TOOL_VERSION,
            "export_id": export_id,
            "model_version_id": str(getattr(model_version, "id", "")),
            "registered_model_id": str(getattr(model_version, "registered_model_id", "")),
            "project_id": str(getattr(model_version, "project_id", "")),
            "task_type": (getattr(model_version, "output_schema", None) or {}).get("task_type") or metadata.get("task_type"),
            "target_columns": (getattr(model_version, "output_schema", None) or {}).get("target_columns") or metadata.get("target_columns", []),
            "framework": getattr(model_version, "framework", ""),
            "algorithm": getattr(model_version, "algorithm", ""),
            "feature_schema": _jsonable(getattr(model_version, "feature_schema", [])),
            "input_contract_hash": _sha256_bytes(_canonical(input_contract)),
            "output_contract_hash": _sha256_bytes(_canonical(output_contract)),
            "preprocessing_hash": _sha256_bytes(_canonical(metadata.get("preprocessing") or {})),
            "source_artifact_sha256": _sha256_bytes(model_path.read_bytes()),
            "annotation_task_revision": annotation_task_revision,
            "runtime": {"python": platform.python_version(), "os": platform.system(), "machine": platform.machine()},
            "deterministic": {"random_seed": metadata.get("seed"), "threads": 1},
        }
        _write_json(temporary_root, "manifest.json", manifest)
        files = sorted(
            str(path.relative_to(temporary_root)).replace("\\", "/")
            for path in temporary_root.rglob("*")
            if path.is_file() and path.name not in {"checksums.json", "manifest.sig"}
        )
        checksums = {name: _sha256_bytes((temporary_root / name).read_bytes()) for name in files}
        _write_json(temporary_root, "checksums.json", checksums)
        signature_payload = (temporary_root / "manifest.json").read_bytes() + b"\n" + (temporary_root / "checksums.json").read_bytes()
        public_key = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        signature = key.sign(signature_payload)
        _write_json(
            temporary_root,
            "security/manifest.sig",
            {
                "algorithm": "ed25519",
                "public_key": base64.b64encode(public_key).decode("ascii"),
                "signature": base64.b64encode(signature).decode("ascii"),
            },
        )
        all_files = sorted(
            str(path.relative_to(temporary_root)).replace("\\", "/")
            for path in temporary_root.rglob("*")
            if path.is_file()
        )
        target = destination / f"model-export-{export_id}.zip"
        _zip_directory(temporary_root, target, all_files)
        return ExportResult(path=target, manifest=manifest, export_id=export_id)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def validate_export_package(path: str | Path, *, signing_key: str | bytes | None = None) -> ExportValidationReport:
    package = Path(path)
    errors: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(package) as archive:
            names = tuple(sorted(archive.namelist()))
            if any(name.startswith("/") or ".." in Path(name).parts for name in names):
                raise ExportValidationError("EXPORT_PATH_TRAVERSAL")
            required_missing = sorted(REQUIRED_PACKAGE_FILES - set(names))
            if required_missing:
                raise ExportValidationError("EXPORT_REQUIRED_FILE_MISSING", ",".join(required_missing))
            for name in names:
                lowered = name.lower()
                if lowered.startswith("data/") or any(part in FORBIDDEN_NAME_PARTS for part in Path(lowered).parts):
                    raise ExportValidationError("EXPORT_FORBIDDEN_CONTENT")
            manifest_bytes = archive.read("manifest.json")
            checksums_bytes = archive.read("checksums.json")
            manifest = json.loads(manifest_bytes)
            checksums = json.loads(checksums_bytes)
            if not isinstance(checksums, dict) or not checksums:
                raise ExportValidationError("EXPORT_CHECKSUMS_INVALID")
            expected_covered_files = set(names) - CHECKSUM_METADATA_FILES
            if set(checksums) != expected_covered_files:
                raise ExportValidationError("EXPORT_CHECKSUM_COVERAGE_INCOMPLETE")
            for name, expected in checksums.items():
                if name not in names:
                    raise ExportValidationError("EXPORT_CHECKSUM_FILE_MISSING")
                actual = _sha256_bytes(archive.read(name))
                if actual != expected:
                    raise ExportValidationError("EXPORT_CHECKSUM_MISMATCH", name)
            signature = json.loads(archive.read("security/manifest.sig"))
            public_key_bytes = base64.b64decode(signature["public_key"])
            if signing_key is not None:
                expected_public = _signing_key(signing_key).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                if public_key_bytes != expected_public:
                    raise ExportValidationError("EXPORT_SIGNATURE_INVALID")
            try:
                Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                    base64.b64decode(signature["signature"]), manifest_bytes + b"\n" + checksums_bytes
                )
            except (InvalidSignature, ValueError, KeyError, TypeError) as error:
                raise ExportValidationError("EXPORT_SIGNATURE_INVALID") from error
            if manifest.get("manifest_version") != 1:
                raise ExportValidationError("EXPORT_MANIFEST_INVALID")
            return ExportValidationReport(valid=True, files=names)
    except ExportValidationError:
        raise
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError, ValueError) as error:
        raise ExportValidationError("EXPORT_PACKAGE_INVALID") from error


def create_model_export(
    model_version_id: Any,
    annotation_task_revision: int | str | None,
    include_runtime: bool,
    idempotency_key: str,
    *,
    output_dir: str | Path | None = None,
    signing_key: str | bytes | None = None,
    db: Any = None,
    model_version: Any = None,
) -> ExportResult:
    """Create an export from a supplied version or an ORM session.

    API handlers should pass ``db`` and let the project-scoped service resolve
    the model version.  Contract tests may pass ``model_version`` directly.
    """

    if model_version is None and hasattr(model_version_id, "conversion_metadata"):
        model_version = model_version_id
    if model_version is None and db is not None:
        from app.models.model_registry import ModelVersion

        model_version = db.get(ModelVersion, model_version_id)
    if model_version is None:
        raise ExportError("MODEL_VERSION_NOT_FOUND")
    destination = output_dir or Path.cwd() / "exports"
    return build_export_package(
        model_version,
        output_dir=destination,
        include_runtime=include_runtime,
        signing_key=signing_key,
        annotation_task_revision=annotation_task_revision,
    )
