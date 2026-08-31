"""Reduce a Playwright JSON report to the fail-closed Week 12 evidence shape."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterator

from tools.redaction import redact_text


_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)[^\s\"'<>]*"
    r"|(?<![:A-Za-z0-9+./-])/(?:[^\s\"'<>]+)"
)


def _tests(value: object) -> Iterator[dict[str, object]]:
    if not isinstance(value, dict):
        return
    specs = value.get("specs")
    if isinstance(specs, list):
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            tests = spec.get("tests")
            if not isinstance(tests, list):
                continue
            for test in tests:
                if isinstance(test, dict):
                    yield test
    suites = value.get("suites")
    if isinstance(suites, list):
        for suite in suites:
            yield from _tests(suite)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _ABSOLUTE_PATH.sub("[redacted-path]", redact_text(value))
    return value


def sanitize_report(input_path: Path, output_path: Path) -> None:
    """Write a path- and credential-safe copy of a Playwright JSON report."""
    try:
        report = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = {}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_sanitize_value(report), ensure_ascii=True, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def summarize_report(
    input_path: Path,
    output_path: Path,
    *,
    project: str = "chromium",
) -> dict[str, object]:
    """Write only completion counts; skipped or malformed results cannot pass."""
    try:
        report = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = {}

    total = 0
    passed = 0
    failed = 0
    for test in _tests(report):
        if test.get("projectName") != project:
            continue
        total += 1
        results = test.get("results")
        if not isinstance(results, list) or not results:
            failed += 1
            continue
        result = results[-1]
        status = result.get("status") if isinstance(result, dict) else None
        if status == "passed":
            passed += 1
        elif status == "failed":
            failed += 1

    result = {
        "status": "passed" if total > 0 and passed == total and failed == 0 else "failed",
        "project": project,
        "tests": {"total": total, "passed": passed, "failed": failed},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sanitized-output", type=Path)
    parser.add_argument("--project", default="chromium")
    args = parser.parse_args(argv)
    result = summarize_report(args.input, args.output, project=args.project)
    if args.sanitized_output is not None:
        sanitize_report(args.input, args.sanitized_output)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
