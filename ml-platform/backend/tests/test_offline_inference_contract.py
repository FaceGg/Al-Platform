from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from app.services.model_export import build_export_package
from app.services.offline_inference import (
    InputContractError,
    run_offline_predict,
)
from tests.test_model_export_contract import _version


def test_offline_predict_rejects_missing_column_without_partial_output(tmp_path: Path):
    package = build_export_package(
        _version(tmp_path),
        output_dir=tmp_path / "exports",
        include_runtime=True,
        signing_key="contract-test-key",
    )
    source = tmp_path / "missing.csv"
    source.write_text("sample_id,other\na,1\n", encoding="utf-8")
    output = tmp_path / "out.csv"

    with pytest.raises(InputContractError) as error:
        run_offline_predict(
            package.path,
            source,
            output,
            signing_key="contract-test-key",
        )

    assert error.value.code == "INPUT_CONTRACT_MISMATCH"
    assert not output.exists()
    report = tmp_path / "validation-report.json"
    assert report.exists()
    assert "other" not in report.read_text(encoding="utf-8")


def test_offline_predict_validates_input_and_writes_atomic_result(tmp_path: Path):
    package = build_export_package(
        _version(tmp_path),
        output_dir=tmp_path / "exports",
        include_runtime=True,
        signing_key="contract-test-key",
    )
    source = tmp_path / "valid.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["sample_id", "feature"])
        writer.writeheader()
        writer.writerow({"sample_id": "a", "feature": "0.2"})
        writer.writerow({"sample_id": "b", "feature": "2.8"})
    output = tmp_path / "out.csv"

    result = run_offline_predict(
        package.path,
        source,
        output,
        signing_key="contract-test-key",
    )

    assert result.row_count == 2
    frame = pd.read_csv(output)
    assert list(frame.columns) == ["sample_id", "label"]
    assert len(frame) == 2
    assert not (tmp_path / "validation-report.json").exists()
