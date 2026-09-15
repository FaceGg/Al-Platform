from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import joblib
from sklearn.linear_model import LogisticRegression

from app.services.model_export import (
    ExportValidationError,
    build_export_package,
    validate_export_package,
)


def _version(tmp_path: Path, *, annotation_revision: int | None = None, dict_artifact: bool = False):
    model_path = tmp_path / "model.joblib"
    model = LogisticRegression().fit([[0.0], [1.0], [2.0], [3.0]], [0, 0, 1, 1])
    joblib.dump(model, model_path)
    contract = {
        "required_columns": ["feature"],
        "columns": {"feature": {"dtype": "float", "missing_policy": "reject"}},
        "sample_id_column": "sample_id",
        "parse_contract": {"parser_version": "1", "source_format": "csv"},
    }
    metadata = {
        "input_contract": contract,
        "preprocessing": {"version": "preprocess-1"},
        "artifact_path": str(model_path),
        "candidate_id": str(uuid.uuid4()),
        "task_type": "classification",
        "target_columns": ["label"],
    }
    if annotation_revision is not None:
        metadata["annotation"] = {
            "strategy": {"strategy": "rule", "other_values": {"label": 0}},
            "cluster_method": {"name": "weighted_kmeans", "seed": 7},
            "cluster_artifacts": {"centroids": "artifacts/clusters/centroids.json"},
            "cluster_label_mappings": {"0": "reject", "1": "accept"},
            "rules": {"rules": []},
        }
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        source_artifact_id=uuid.uuid4(),
        onnx_artifact_id=None,
        source_artifact_path=None if dict_artifact else str(model_path),
        source_artifact={"storage_path": str(model_path)} if dict_artifact else None,
        framework="scikit-learn",
        algorithm="logistic_regression",
        feature_schema=[{"name": "feature", "dtype": "float"}],
        output_schema={"task_type": "classification", "target_columns": ["label"]},
        conversion_metadata=metadata,
        lifecycle_state="approved",
        approval_status="approved",
    )


class _DeserializationMarker:
    def __init__(self, marker: Path):
        self.marker = marker

    def __reduce__(self):
        return (Path.write_text, (self.marker, "deserialized", "utf-8"))


def test_export_contains_contracts_checksums_sbom_and_signature(tmp_path: Path):
    export = build_export_package(
        _version(tmp_path),
        output_dir=tmp_path / "exports",
        include_runtime=True,
        signing_key="contract-test-key",
    )

    report = validate_export_package(export.path)
    assert report.valid is True
    with zipfile.ZipFile(export.path) as archive:
        names = set(archive.namelist())
    assert {
        "manifest.json",
        "checksums.json",
        "security/sbom.spdx.json",
        "security/manifest.sig",
        "runtime/inference.py",
        "runtime/cli.py",
        "runtime/requirements.lock",
        "runtime/README-runtime.md",
        "contracts/input_contract.json",
        "contracts/output_contract.json",
        "README.md",
    } <= names
    assert "README.txt" not in names
    assert not any(name.startswith("data/") for name in names)
    assert not any("sample" in name.lower() or "credential" in name.lower() for name in names)


def test_runtime_requirements_are_exactly_pinned(tmp_path: Path):
    export = build_export_package(
        _version(tmp_path),
        output_dir=tmp_path / "exports",
        signing_key="contract-test-key",
    )
    with zipfile.ZipFile(export.path) as archive:
        requirements = archive.read("runtime/requirements.lock").decode("utf-8")
    assert requirements.strip()
    assert all("==" in line and not any(operator in line for operator in ("*", ">", "<", "~")) for line in requirements.splitlines())


def test_exported_runtime_is_self_contained_and_executable(tmp_path: Path):
    export = build_export_package(
        _version(tmp_path),
        output_dir=tmp_path / "exports",
        include_runtime=True,
        signing_key="contract-test-key",
    )
    runtime_root = tmp_path / "runtime"
    source = tmp_path / "input.csv"
    source.write_text("sample_id,feature\na,0.2\nb,2.8\n", encoding="utf-8")
    output = tmp_path / "output.csv"

    with zipfile.ZipFile(export.path) as archive:
        archive.extractall(runtime_root)
    inference_source = (runtime_root / "runtime/inference.py").read_text(encoding="utf-8")
    assert "app." not in inference_source
    assert "from app " not in inference_source

    environment = os.environ.copy()
    environment["PYTHONPATH"] = ""
    result = subprocess.run(
        [
            sys.executable,
            str(runtime_root / "runtime/cli.py"),
            "predict",
            "--package",
            str(export.path),
            "--input",
            str(source),
            "--output",
            str(output),
        ],
        cwd=runtime_root / "runtime",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.exists()
    frame = __import__("pandas").read_csv(output)
    assert frame["label"].tolist() == [0, 1]
    assert str(frame["label"].dtype) in {"int64", "int32"}


def test_runtime_predict_reports_contract_failure_without_business_output(tmp_path: Path):
    export = build_export_package(
        _version(tmp_path),
        output_dir=tmp_path / "exports",
        signing_key="contract-test-key",
    )
    runtime_root = tmp_path / "runtime-contract"
    source = tmp_path / "wrong.csv"
    source.write_text("sample_id,wrong\na,1\n", encoding="utf-8")
    output = tmp_path / "wrong-output.csv"
    with zipfile.ZipFile(export.path) as archive:
        archive.extractall(runtime_root)

    environment = os.environ.copy()
    environment["PYTHONPATH"] = ""
    result = subprocess.run(
        [
            sys.executable,
            str(runtime_root / "runtime/cli.py"),
            "predict",
            "--package",
            str(export.path),
            "--input",
            str(source),
            "--output",
            str(output),
        ],
        cwd=runtime_root / "runtime",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert not output.exists()
    report = tmp_path / "validation-report.json"
    assert report.exists()
    assert "wrong" not in report.read_text(encoding="utf-8")


def test_runtime_rejects_tampered_model_before_deserialization(tmp_path: Path):
    export = build_export_package(
        _version(tmp_path),
        output_dir=tmp_path / "exports",
        signing_key="contract-test-key",
    )
    marker = tmp_path / "deserialized.txt"
    payload = tmp_path / "malicious.joblib"
    joblib.dump(_DeserializationMarker(marker), payload)
    tampered = tmp_path / "tampered-model.zip"
    with zipfile.ZipFile(export.path) as source, zipfile.ZipFile(tampered, "w") as target:
        for info in source.infolist():
            content = payload.read_bytes() if info.filename == "model/model.joblib" else source.read(info.filename)
            target.writestr(info, content)

    runtime_root = tmp_path / "runtime-tampered"
    source = tmp_path / "valid.csv"
    source.write_text("sample_id,feature\na,0.2\n", encoding="utf-8")
    output = tmp_path / "tampered-output.csv"
    with zipfile.ZipFile(export.path) as archive:
        archive.extractall(runtime_root)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = ""
    result = subprocess.run(
        [
            sys.executable,
            str(runtime_root / "runtime/cli.py"),
            "predict",
            "--package",
            str(tampered),
            "--input",
            str(source),
            "--output",
            str(output),
        ],
        cwd=runtime_root / "runtime",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert not marker.exists()
    assert not output.exists()
    assert (tmp_path / "validation-report.json").exists()


def test_annotation_export_includes_strategy_only_when_task_revision_is_bound(tmp_path: Path):
    unbound = build_export_package(
        _version(tmp_path),
        output_dir=tmp_path / "exports-unbound",
        include_runtime=False,
        signing_key="contract-test-key",
        annotation_task_revision=None,
    )
    bound = build_export_package(
        _version(tmp_path, annotation_revision=3),
        output_dir=tmp_path / "exports-bound",
        include_runtime=False,
        signing_key="contract-test-key",
        annotation_task_revision=3,
    )

    with zipfile.ZipFile(unbound.path) as archive:
        unbound_names = set(archive.namelist())
    with zipfile.ZipFile(bound.path) as archive:
        bound_names = set(archive.namelist())
    assert "annotation/strategy.json" not in unbound_names
    assert "annotation/strategy.json" in bound_names
    assert "annotation/cluster_method.json" in bound_names
    assert "annotation/cluster_artifacts.json" in bound_names
    assert "annotation/cluster_label_mappings.json" in bound_names
    assert "annotation/rules.json" in bound_names


def test_runtime_annotate_executes_annotation_strategy_instead_of_aliasing_predict(tmp_path: Path):
    export = build_export_package(
        _version(tmp_path, annotation_revision=3),
        output_dir=tmp_path / "exports-bound",
        signing_key="contract-test-key",
        annotation_task_revision=3,
    )
    runtime_root = tmp_path / "runtime-annotate"
    source = tmp_path / "input.csv"
    source.write_text("sample_id,feature\na,0.2\nb,2.8\n", encoding="utf-8")
    output = tmp_path / "annotation.csv"
    with zipfile.ZipFile(export.path) as archive:
        archive.extractall(runtime_root)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = ""
    result = subprocess.run(
        [
            sys.executable,
            str(runtime_root / "runtime/cli.py"),
            "annotate",
            "--package",
            str(export.path),
            "--input",
            str(source),
            "--output",
            str(output),
        ],
        cwd=runtime_root / "runtime",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    frame = __import__("pandas").read_csv(output)
    assert list(frame["annotation_status"]) == ["needs_review", "needs_review"]


def test_runtime_rejects_output_target_count_mismatch(tmp_path: Path):
    version = _version(tmp_path)
    version.output_schema = {"task_type": "classification", "target_columns": ["label", "extra"]}
    export = build_export_package(version, output_dir=tmp_path / "exports", signing_key="contract-test-key")
    runtime_root = tmp_path / "runtime-target-mismatch"
    source = tmp_path / "input.csv"
    source.write_text("sample_id,feature\na,0.2\n", encoding="utf-8")
    output = tmp_path / "target-mismatch.csv"
    with zipfile.ZipFile(export.path) as archive:
        archive.extractall(runtime_root)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = ""
    result = subprocess.run(
        [sys.executable, str(runtime_root / "runtime/cli.py"), "predict", "--package", str(export.path), "--input", str(source), "--output", str(output)],
        cwd=runtime_root / "runtime", env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert not output.exists()


def test_export_resolves_dict_model_artifact_reference(tmp_path: Path):
    export = build_export_package(
        _version(tmp_path, dict_artifact=True),
        output_dir=tmp_path / "exports",
        signing_key="contract-test-key",
    )
    with zipfile.ZipFile(export.path) as archive:
        assert archive.read("model/model.joblib")


def test_runtime_rejects_bad_dtype_and_duplicate_sample_identity(tmp_path: Path):
    export = build_export_package(_version(tmp_path), output_dir=tmp_path / "exports", signing_key="contract-test-key")
    runtime_root = tmp_path / "runtime-invalid-input"
    source = tmp_path / "invalid.csv"
    source.write_text("sample_id,feature\na,wrong\na,wrong\n", encoding="utf-8")
    output = tmp_path / "invalid-output.csv"
    with zipfile.ZipFile(export.path) as archive:
        archive.extractall(runtime_root)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = ""
    result = subprocess.run(
        [sys.executable, str(runtime_root / "runtime/cli.py"), "predict", "--package", str(export.path), "--input", str(source), "--output", str(output)],
        cwd=runtime_root / "runtime", env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert not output.exists()
    assert (tmp_path / "validation-report.json").exists()


def test_runtime_annotate_requires_bound_strategy(tmp_path: Path):
    export = build_export_package(_version(tmp_path), output_dir=tmp_path / "exports", signing_key="contract-test-key")
    runtime_root = tmp_path / "runtime-unbound-annotate"
    source = tmp_path / "input.csv"
    source.write_text("sample_id,feature\na,0.2\n", encoding="utf-8")
    output = tmp_path / "unbound-annotation.csv"
    with zipfile.ZipFile(export.path) as archive:
        archive.extractall(runtime_root)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = ""
    result = subprocess.run(
        [sys.executable, str(runtime_root / "runtime/cli.py"), "annotate", "--package", str(export.path), "--input", str(source), "--output", str(output)],
        cwd=runtime_root / "runtime", env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert not output.exists()
    assert (tmp_path / "validation-report.json").exists()


def test_runtime_writes_parquet_and_xml_outputs(tmp_path: Path):
    export = build_export_package(_version(tmp_path), output_dir=tmp_path / "exports", signing_key="contract-test-key")
    runtime_root = tmp_path / "runtime-output-formats"
    source = tmp_path / "input.csv"
    source.write_text("sample_id,feature\na,0.2\n", encoding="utf-8")
    with zipfile.ZipFile(export.path) as archive:
        archive.extractall(runtime_root)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = ""
    for suffix in ("parquet", "xml"):
        output = tmp_path / f"predictions.{suffix}"
        result = subprocess.run(
            [sys.executable, str(runtime_root / "runtime/cli.py"), "predict", "--package", str(export.path), "--input", str(source), "--output", str(output)],
            cwd=runtime_root / "runtime", env=environment, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
        assert output.exists()


def test_export_validation_rejects_file_not_covered_by_checksums(tmp_path: Path):
    export = build_export_package(
        _version(tmp_path),
        output_dir=tmp_path / "exports",
        include_runtime=True,
        signing_key="contract-test-key",
    )
    untracked = tmp_path / "untracked.zip"
    with zipfile.ZipFile(export.path) as source, zipfile.ZipFile(untracked, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        target.writestr("runtime/untracked.txt", "not covered")

    try:
        validate_export_package(untracked)
    except ExportValidationError as error:
        assert error.code == "EXPORT_CHECKSUM_COVERAGE_INCOMPLETE"
    else:
        raise AssertionError("package with an unchecksummed file was accepted")


def test_export_validation_rejects_tampered_manifest(tmp_path: Path):
    export = build_export_package(
        _version(tmp_path),
        output_dir=tmp_path / "exports",
        include_runtime=True,
        signing_key="contract-test-key",
    )
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(export.path) as source, zipfile.ZipFile(tampered, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "manifest.json":
                manifest = json.loads(content)
                manifest["algorithm"] = "tampered"
                content = json.dumps(manifest, sort_keys=True).encode()
            target.writestr(info, content)
    try:
        validate_export_package(tampered)
    except ExportValidationError as error:
        assert error.code in {"EXPORT_SIGNATURE_INVALID", "EXPORT_CHECKSUM_MISMATCH"}
    else:
        raise AssertionError("tampered manifest was accepted")
