"""Fail-closed receipts for the generic-platform release acceptance gate."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence


REQUIRED_EVIDENCE_IDS = (
    "DAT-01",
    "DAT-02",
    "DAT-03",
    "LAB-01",
    "LAB-02",
    "LAB-03",
    "CLU-01",
    "CLU-02",
    "CON-01",
    "CON-02",
    "RET-01",
    "AUTH-01",
    "AUTH-02",
    "API-01",
    "AUTO-01",
    "AUTO-02",
    "EXP-01",
    "INF-01",
    "REL-01",
)
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SECRET = re.compile(r"(?:password|secret|token|api[_-]?key)\s*(?:=|:)", re.IGNORECASE)


class AcceptanceGateError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _require_sha(value: object) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise AcceptanceGateError("EVIDENCE_SHA_INVALID", "Evidence must bind to a full Git SHA.")
    return value


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise AcceptanceGateError("EVIDENCE_PATH_UNSAFE", "Evidence paths must be non-empty relative paths.")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", normalized):
        raise AcceptanceGateError("EVIDENCE_PATH_UNSAFE", "Evidence paths must be repository-relative.")
    return path.as_posix()


def _safe_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise AcceptanceGateError("EVIDENCE_VALUE_INVALID", "Evidence values must be non-empty strings.")
    if _SECRET.search(value):
        raise AcceptanceGateError("EVIDENCE_SECRET_DETECTED", "Evidence receipts must not contain secrets.")
    return value


def _safe_command_part(value: object) -> str:
    text = _safe_text(value)
    normalized = text.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", normalized):
        raise AcceptanceGateError("EVIDENCE_PATH_UNSAFE", "Evidence commands must not contain absolute paths.")
    return text


def _validate_receipt(evidence_id: str, receipt: object, current_sha: str) -> None:
    if not isinstance(receipt, Mapping):
        raise AcceptanceGateError("REQUIRED_EVIDENCE_INVALID", f"{evidence_id} receipt is invalid.")
    if receipt.get("status") != "passed":
        raise AcceptanceGateError("REQUIRED_EVIDENCE_NOT_PASSED", f"{evidence_id} is not passed.")
    if receipt.get("commit_sha") != current_sha:
        raise AcceptanceGateError("EVIDENCE_SHA_MISMATCH", f"{evidence_id} is not bound to the current SHA.")
    command = receipt.get("command")
    paths = receipt.get("evidence_paths")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command):
        raise AcceptanceGateError("REQUIRED_EVIDENCE_INVALID", f"{evidence_id} command is invalid.")
    for part in command:
        _safe_command_part(part)
    if not isinstance(paths, list) or not paths:
        raise AcceptanceGateError("REQUIRED_EVIDENCE_INVALID", f"{evidence_id} evidence paths are missing.")
    for path in paths:
        _safe_relative_path(path)


def validate_acceptance_manifest(manifest: Mapping[str, object], *, current_sha: str) -> None:
    current_sha = _require_sha(current_sha)
    if manifest.get("commit_sha") != current_sha:
        raise AcceptanceGateError("EVIDENCE_SHA_MISMATCH", "Manifest is not bound to the current SHA.")
    evidence = manifest.get("evidence")
    if not isinstance(evidence, Mapping):
        raise AcceptanceGateError("REQUIRED_EVIDENCE_INVALID", "Evidence map is missing.")
    missing = [evidence_id for evidence_id in REQUIRED_EVIDENCE_IDS if evidence_id not in evidence]
    if missing:
        raise AcceptanceGateError("REQUIRED_EVIDENCE_MISSING", f"Missing required evidence: {', '.join(missing)}.")
    for evidence_id in REQUIRED_EVIDENCE_IDS:
        _validate_receipt(evidence_id, evidence[evidence_id], current_sha)


def write_contract_receipt(
    evidence_dir: Path,
    evidence_id: str,
    *,
    status: str,
    command: Sequence[str],
    evidence_paths: Sequence[str],
    commit_sha: str,
) -> Path:
    if evidence_id not in REQUIRED_EVIDENCE_IDS:
        raise AcceptanceGateError("EVIDENCE_ID_INVALID", "Unknown acceptance evidence id.")
    if status not in {"passed", "failed", "cancelled", "skipped"}:
        raise AcceptanceGateError("EVIDENCE_STATUS_INVALID", "Receipt status is invalid.")
    commit_sha = _require_sha(commit_sha)
    normalized_command = [_safe_command_part(part) for part in command]
    if not normalized_command:
        raise AcceptanceGateError("REQUIRED_EVIDENCE_INVALID", "Receipt command is required.")
    normalized_paths = [_safe_relative_path(path) for path in evidence_paths]
    if not normalized_paths:
        raise AcceptanceGateError("REQUIRED_EVIDENCE_INVALID", "Receipt evidence paths are required.")
    receipt = {
        "commit_sha": commit_sha,
        "command": normalized_command,
        "evidence_id": evidence_id,
        "evidence_paths": normalized_paths,
        "status": status,
    }
    output = Path(evidence_dir) / "receipts" / f"{evidence_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--evidence-id", choices=REQUIRED_EVIDENCE_IDS, required=True)
    parser.add_argument("--status", choices=("passed", "failed", "cancelled", "skipped"), required=True)
    parser.add_argument("--command", nargs="+", required=True)
    parser.add_argument("--evidence-path", action="append", required=True)
    parser.add_argument("--commit-sha", default=os.getenv("ACCEPTANCE_SOURCE_COMMIT"))
    args = parser.parse_args(argv)
    write_contract_receipt(
        args.evidence_dir,
        args.evidence_id,
        status=args.status,
        command=args.command,
        evidence_paths=args.evidence_path,
        commit_sha=args.commit_sha,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
