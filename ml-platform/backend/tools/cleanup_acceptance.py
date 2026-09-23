"""Write a SHA-bound orphan-artifact cleanup receipt."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
import json
import re

from app.config import settings
from app.services.operation_lifecycle import write_cleanup_report
from app.storage.factory import create_artifact_storage


def validate_cleanup_report(path: Path, current_sha: str) -> dict:
    """Validate a cleanup receipt before it can satisfy REL-01."""
    if not re.fullmatch(r"[0-9a-f]{40}", current_sha or ""):
        raise ValueError("CLEANUP_SOURCE_COMMIT_INVALID")
    report_path = Path(path)
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("CLEANUP_REPORT_INVALID") from exc
    required = {"status", "scanned", "removed", "retained_committed", "errors", "ttl_seconds", "source_commit"}
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise ValueError("CLEANUP_REPORT_INVALID")
    if payload.get("status") != "passed":
        raise ValueError("CLEANUP_REPORT_NOT_PASSED")
    if payload.get("source_commit") != current_sha:
        raise ValueError("CLEANUP_REPORT_SHA_MISMATCH")
    for key in ("scanned", "removed", "retained_committed", "ttl_seconds"):
        if isinstance(payload.get(key), bool) or not isinstance(payload.get(key), int) or payload[key] < 0:
            raise ValueError("CLEANUP_REPORT_INVALID")
    if not isinstance(payload.get("errors"), list) or payload["errors"]:
        raise ValueError("CLEANUP_REPORT_INVALID")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--older-than-seconds", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    if args.older_than_seconds < 0:
        parser.error("--older-than-seconds must be non-negative")
    storage = create_artifact_storage(settings)
    write_cleanup_report(
        storage,
        args.output,
        timedelta(seconds=args.older_than_seconds),
        args.source_commit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
