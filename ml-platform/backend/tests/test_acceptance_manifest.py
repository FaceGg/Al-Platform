import json
from pathlib import Path

import pytest

from tools.generic_acceptance_evidence import (
    AcceptanceGateError,
    REQUIRED_EVIDENCE_IDS,
    validate_acceptance_manifest,
    write_contract_receipt,
)


CURRENT_SHA = "a" * 40


def _manifest(*, status: str = "passed", commit_sha: str = CURRENT_SHA) -> dict:
    return {
        "commit_sha": commit_sha,
        "evidence": {
            evidence_id: {
                "status": status,
                "commit_sha": CURRENT_SHA,
                "command": ["python", "-m", "pytest"],
                "evidence_paths": [f"evidence/{evidence_id}.json"],
            }
            for evidence_id in REQUIRED_EVIDENCE_IDS
        },
    }


def test_acceptance_manifest_rejects_skipped_required_evidence():
    manifest = _manifest()
    manifest["evidence"]["EXP-01"]["status"] = "skipped"

    with pytest.raises(AcceptanceGateError) as error:
        validate_acceptance_manifest(manifest, current_sha=CURRENT_SHA)

    assert error.value.code == "REQUIRED_EVIDENCE_NOT_PASSED"


def test_acceptance_manifest_binds_all_evidence_to_current_sha():
    manifest = _manifest(commit_sha="b" * 40)

    with pytest.raises(AcceptanceGateError) as error:
        validate_acceptance_manifest(manifest, current_sha=CURRENT_SHA)

    assert error.value.code == "EVIDENCE_SHA_MISMATCH"


def test_contract_receipt_is_redacted_and_sha_bound(tmp_path: Path):
    report = tmp_path / "reports" / "api.json"
    report.parent.mkdir()
    report.write_text('{"status": "passed"}', encoding="utf-8")
    receipt = write_contract_receipt(
        tmp_path,
        "API-01",
        status="passed",
        command=["python", "-m", "pytest", "tests/test_api.py"],
        evidence_paths=["reports/api.json"],
        commit_sha=CURRENT_SHA,
        repository_root=tmp_path,
    )

    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt == tmp_path / "receipts" / "API-01.json"
    assert payload["evidence_id"] == "API-01"
    assert payload["commit_sha"] == CURRENT_SHA
    assert payload["status"] == "passed"


def test_contract_receipt_rejects_absolute_or_secret_bearing_values(tmp_path: Path):
    with pytest.raises(AcceptanceGateError) as absolute_error:
        write_contract_receipt(
            tmp_path,
            "API-01",
            status="passed",
            command=["pytest", "C:\\private\\report.json"],
            evidence_paths=["reports/api.json"],
            commit_sha=CURRENT_SHA,
        )
    assert absolute_error.value.code == "EVIDENCE_PATH_UNSAFE"

    with pytest.raises(AcceptanceGateError) as secret_error:
        write_contract_receipt(
            tmp_path,
            "API-01",
            status="passed",
            command=["pytest", "--token=secret-value"],
            evidence_paths=["reports/api.json"],
            commit_sha=CURRENT_SHA,
        )
    assert secret_error.value.code == "EVIDENCE_SECRET_DETECTED"


def test_contract_receipt_rejects_nonexistent_evidence(tmp_path: Path):
    with pytest.raises(AcceptanceGateError) as error:
        write_contract_receipt(
            tmp_path,
            "API-01",
            status="passed",
            command=["python", "-m", "pytest"],
            evidence_paths=["reports/nonexistent-acceptance-result.json"],
            commit_sha=CURRENT_SHA,
        )
    assert error.value.code == "EVIDENCE_FILE_MISSING"


def test_acceptance_manifest_rejects_tampered_hashed_evidence(tmp_path: Path):
    report = tmp_path / "evidence" / "api.json"
    report.parent.mkdir()
    report.write_text("original", encoding="utf-8")
    receipt = write_contract_receipt(
        tmp_path,
        "API-01",
        status="passed",
        command=["pytest", "tests/test_api.py"],
        evidence_paths=["evidence/api.json"],
        commit_sha=CURRENT_SHA,
        repository_root=tmp_path,
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    manifest = _manifest()
    manifest["evidence"]["API-01"] = payload
    report.write_text("tampered", encoding="utf-8")
    with pytest.raises(AcceptanceGateError) as error:
        validate_acceptance_manifest(manifest, current_sha=CURRENT_SHA, repository_root=tmp_path)
    assert error.value.code == "EVIDENCE_HASH_MISMATCH"
