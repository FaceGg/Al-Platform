from __future__ import annotations

import json
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


def _version(tmp_path: Path, *, annotation_revision: int | None = None):
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
            "rules": {"rules": []},
    }
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        source_artifact_id=uuid.uuid4(),
        onnx_artifact_id=None,
        source_artifact_path=str(model_path),
        framework="scikit-learn",
        algorithm="logistic_regression",
        feature_schema=[{"name": "feature", "dtype": "float"}],
        output_schema={"task_type": "classification", "target_columns": ["label"]},
        conversion_metadata=metadata,
        lifecycle_state="approved",
        approval_status="approved",
    )


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
        "contracts/input_contract.json",
        "contracts/output_contract.json",
    } <= names
    assert not any(name.startswith("data/") for name in names)
    assert not any("sample" in name.lower() or "credential" in name.lower() for name in names)


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
    assert "annotation/rules.json" in bound_names


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
