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
}
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
            candidates.extend((getattr(artifact, "storage_path", None), getattr(artifact, "storage_uri", None)))
    metadata = getattr(version, "conversion_metadata", None) or {}
    candidates.extend((metadata.get("artifact_path"), metadata.get("model_path")))
    for candidate in candidates:
        if not candidate:
            continue
        value = str(candidate)
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
    # This is a lock-style record, not a path dump.  It intentionally lists only
    # runtime packages needed by the generated runner.
    return "joblib==1.5.*\nnumpy==2.3.*\npandas==2.3.*\nscikit-learn==1.7.*\n"


def _runtime_source() -> str:
    return '''"""Generated offline runner entry points.

Use ``app.services.offline_inference`` from the platform package when running
inside the platform.  The package keeps this source file so an audited export
always declares its runtime boundary.
"""

from pathlib import Path

from app.services.offline_inference import run_offline_annotate, run_offline_predict


def predict(package: str | Path, input_path: str | Path, output_path: str | Path):
    return run_offline_predict(Path(package), Path(input_path), Path(output_path))


def annotate(package: str | Path, input_path: str | Path, output_path: str | Path):
    return run_offline_annotate(Path(package), Path(input_path), Path(output_path))
'''


def _build_sbom(root: Path) -> None:
    packages = []
    for name, version in (("joblib", "1.5.*"), ("numpy", "2.3.*"), ("pandas", "2.3.*"), ("scikit-learn", "1.7.*")):
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
        (temporary_root / "requirements.lock").write_text(_safe_requirements(), encoding="utf-8")
        (temporary_root / "README.txt").write_text(
            "Signed model export. Runtime accepts only the declared input contract.\n",
            encoding="utf-8",
        )
        if include_runtime:
            (temporary_root / "runtime").mkdir(parents=True, exist_ok=True)
            (temporary_root / "runtime/inference.py").write_text(_runtime_source(), encoding="utf-8")

        if annotation_task_revision is not None:
            annotation = metadata.get("annotation") or {}
            _write_json(temporary_root, "annotation/strategy.json", annotation.get("strategy") or {})
            _write_json(temporary_root, "annotation/cluster_method.json", annotation.get("cluster_method") or {})
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

