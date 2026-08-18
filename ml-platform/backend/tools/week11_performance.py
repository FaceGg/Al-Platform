"""Reproducible, payload-free helpers for Week 11 performance evidence."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import time
from typing import Mapping, Sequence
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


CORE_READ_LIMITS = {
    "p95_ms": 300.0,
    "p99_ms": 800.0,
    "error_rate": 0.001,
}
SCENARIO_CANDIDATE_LIMITS = {
    "core-read": CORE_READ_LIMITS,
    "warm-inference": {
        "p95_ms": 200.0,
        "p99_ms": 500.0,
        "error_rate": 0.001,
    },
    "enqueue": {"p95_ms": 1000.0, "error_rate": 0.001},
    "cold-model-load": {"error_rate": 0.001},
    "welding-e2e": {"duration_ms": 90000.0, "error_rate": 0.001},
}
SCENARIO_REQUIRED_ITERATIONS = {
    "core-read": frozenset({1, 2, 3}),
    "warm-inference": frozenset({1, 2, 3}),
    "enqueue": frozenset({1, 2, 3}),
    "cold-model-load": frozenset({1}),
    "welding-e2e": frozenset({1}),
}
SCENARIO_EXPECTED_LOAD = {
    "core-read": {"concurrency": 20, "requests_per_worker": 100},
    "warm-inference": {"concurrency": 20, "requests_per_worker": 100},
    "enqueue": {"concurrency": 20, "requests_per_worker": 100},
    "cold-model-load": {"concurrency": 1, "requests_per_worker": 1},
    "welding-e2e": {"concurrency": 1, "requests_per_worker": 10},
}
SCENARIO_EXPECTED_REQUESTS = {
    scenario: load["concurrency"] * load["requests_per_worker"]
    for scenario, load in SCENARIO_EXPECTED_LOAD.items()
}
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


def percentile(values: Sequence[float], quantile: float) -> float:
    """Return a linearly interpolated percentile from an unordered sample set."""
    if not values or not 0.0 <= quantile <= 1.0:
        raise ValueError("values and quantile are required")
    ordered = sorted(float(value) for value in values)
    if not all(math.isfinite(value) for value in ordered):
        raise ValueError("values must be finite")
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def evaluate_thresholds(
    metrics: Mapping[str, float],
    limits: Mapping[str, float],
) -> dict[str, object]:
    """Evaluate named upper-bound gates without changing supplied measurements."""
    missing = sorted(name for name in limits if name not in metrics)
    if missing:
        raise ValueError(f"metrics missing required limits: {', '.join(missing)}")
    gates = {}
    for name, limit in limits.items():
        if (
            isinstance(metrics[name], bool)
            or not isinstance(metrics[name], (int, float))
            or isinstance(limit, bool)
            or not isinstance(limit, (int, float))
        ):
            raise ValueError("metrics and limits must be numeric")
        value = float(metrics[name])
        numeric_limit = float(limit)
        if not math.isfinite(value) or not math.isfinite(numeric_limit):
            raise ValueError("metrics and limits must be finite")
        passed = value < numeric_limit if name == "error_rate" else value <= numeric_limit
        gates[name] = {
            "value": value,
            "limit": numeric_limit,
            "passed": passed,
        }
    return {
        "status": "passed" if all(gate["passed"] for gate in gates.values()) else "failed",
        "gates": gates,
    }


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _valid_commit(value: object) -> bool:
    return isinstance(value, str) and _COMMIT_SHA.fullmatch(value) is not None


def _load_gate(result: Mapping[str, object], scenario: str) -> dict[str, object]:
    expected = SCENARIO_EXPECTED_LOAD.get(scenario)
    actual = {
        "concurrency": result.get("concurrency"),
        "requests_per_worker": result.get("requests_per_worker"),
        "requests": result.get("requests"),
    }
    if expected is None:
        return {
            "value": actual,
            "expected": None,
            "passed": False,
            "error_code": "PERFORMANCE_SCENARIO_UNKNOWN",
        }
    expected_requests = expected["concurrency"] * expected["requests_per_worker"]
    passed = (
        _is_integer(actual["concurrency"])
        and _is_integer(actual["requests_per_worker"])
        and _is_integer(actual["requests"])
        and actual["concurrency"] == expected["concurrency"]
        and actual["requests_per_worker"] == expected["requests_per_worker"]
        and actual["requests"] == expected_requests
    )
    return {
        "value": actual,
        "expected": {**expected, "requests": expected_requests},
        "passed": passed,
    }


def _accounting_gate(result: Mapping[str, object]) -> dict[str, object]:
    requests = result.get("requests")
    errors = result.get("errors")
    error_rate = result.get("error_rate")
    status_counts = result.get("status_counts")
    status_counts_valid = isinstance(status_counts, dict) and bool(status_counts)
    observed_requests = 0
    observed_errors = 0
    if status_counts_valid:
        for status, count in status_counts.items():
            if (
                not isinstance(status, str)
                or not status.isdecimal()
                or not _is_integer(count)
                or count < 0
            ):
                status_counts_valid = False
                break
            status_code = int(status)
            if status_code < 100 or status_code > 599:
                status_counts_valid = False
                break
            observed_requests += count
            if status_code >= 400:
                observed_errors += count
    expected_error_rate = (
        observed_errors / requests
        if _is_integer(requests) and requests > 0 and status_counts_valid
        else None
    )
    passed = (
        _is_integer(requests)
        and requests > 0
        and _is_integer(errors)
        and errors >= 0
        and _is_finite_number(error_rate)
        and 0.0 <= float(error_rate) <= 1.0
        and status_counts_valid
        and observed_requests == requests
        and observed_errors == errors
        and expected_error_rate is not None
        and math.isclose(float(error_rate), expected_error_rate, rel_tol=0.0, abs_tol=1e-12)
    )
    return {
        "value": {
            "requests": requests,
            "errors": errors,
            "error_rate": error_rate,
            "status_counts": status_counts,
        },
        "expected": {
            "requests_from_status_counts": observed_requests,
            "errors_from_status_counts": observed_errors,
            "error_rate": expected_error_rate,
        },
        "passed": passed,
    }


def _workflow_completion_gate(result: Mapping[str, object]) -> dict[str, object]:
    requests = result.get("requests")
    completed_requests = result.get("completed_requests")
    terminal_status_counts = result.get("terminal_status_counts")
    completion_samples = result.get("completion_samples_ms")
    duration_ms = result.get("duration_ms")
    samples_valid = (
        isinstance(completion_samples, list)
        and _is_integer(requests)
        and len(completion_samples) == requests
        and all(_is_finite_number(value) and float(value) >= 0.0 for value in completion_samples)
    )
    max_completion_ms = max(completion_samples) if samples_valid else None
    passed = (
        _is_integer(requests)
        and requests > 0
        and completed_requests == requests
        and terminal_status_counts == {"completed": requests}
        and samples_valid
        and _is_finite_number(duration_ms)
        and math.isclose(
            float(duration_ms),
            float(max_completion_ms),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    )
    return {
        "value": {
            "completed_requests": completed_requests,
            "terminal_status_counts": terminal_status_counts,
            "completion_samples": len(completion_samples)
            if isinstance(completion_samples, list)
            else None,
            "max_completion_ms": max_completion_ms,
        },
        "expected": {
            "completed_requests": requests,
            "terminal_status_counts": {"completed": requests} if _is_integer(requests) else None,
            "completion_samples": requests,
            "duration_ms": max_completion_ms,
        },
        "passed": passed,
    }


def _threshold_gates(
    result: Mapping[str, object],
    limits: Mapping[str, float],
) -> dict[str, object]:
    try:
        return dict(evaluate_thresholds(result, limits)["gates"])
    except (TypeError, ValueError):
        return {
            "metrics": {
                "passed": False,
                "error_code": "PERFORMANCE_METRICS_INVALID",
            },
        }


def validate_iteration_evidence(result: Mapping[str, object]) -> dict[str, object]:
    """Return fail-closed gates for one raw frozen-scenario result."""
    scenario = result.get("scenario")
    scenario_name = scenario if isinstance(scenario, str) else ""
    gates = _threshold_gates(
        result,
        SCENARIO_CANDIDATE_LIMITS.get(scenario_name, CORE_READ_LIMITS),
    )
    required_iterations = SCENARIO_REQUIRED_ITERATIONS.get(scenario_name)
    iteration = result.get("iteration")
    gates["load"] = _load_gate(result, scenario_name)
    gates["accounting"] = _accounting_gate(result)
    gates["iteration"] = {
        "value": iteration,
        "expected": sorted(required_iterations) if required_iterations is not None else None,
        "passed": _is_integer(iteration)
        and required_iterations is not None
        and iteration in required_iterations,
    }
    gates["commit"] = {
        "value": result.get("commit"),
        "passed": _valid_commit(result.get("commit")),
    }
    if scenario_name == "welding-e2e":
        gates["workflow_completion"] = _workflow_completion_gate(result)
    return gates


def _gates_passed(gates: Mapping[str, object]) -> bool:
    return bool(gates) and all(
        isinstance(gate, Mapping) and gate.get("passed") is True
        for gate in gates.values()
    )


def _summary_provenance(results: Sequence[Mapping[str, object]]) -> dict[str, object]:
    raw_commits = [result.get("commit") for result in results]
    valid_raw_commits = bool(raw_commits) and all(_valid_commit(commit) for commit in raw_commits)
    unique_commits = sorted({str(commit) for commit in raw_commits if _valid_commit(commit)})
    consistent = valid_raw_commits and len(unique_commits) == 1
    current_commit = _git_commit()
    current_available = _valid_commit(current_commit)
    matches_current = None
    if current_available:
        matches_current = consistent and unique_commits[0] == current_commit
    passed = consistent and matches_current is not False
    return {
        "status": "passed" if passed else "failed",
        "commit": unique_commits[0] if consistent else None,
        "raw_commits": unique_commits,
        "current_commit": current_commit if current_available else "unavailable",
        "current_commit_checked": current_available,
        "matches_current_commit": matches_current,
    }


def write_result(path: Path, result: Mapping[str, object]) -> Path:
    """Write deterministic machine-readable evidence to the requested location."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _request(
    url: str,
    timeout: float,
    method: str,
    body: bytes | None,
    headers: Mapping[str, str],
) -> tuple[float, int]:
    started = time.perf_counter()
    try:
        request_headers = {"User-Agent": "ml-platform-week11", **headers}
        request = Request(url, data=body, headers=request_headers, method=method)
        with urlopen(request, timeout=timeout) as response:
            response.read(1024)
            return (time.perf_counter() - started) * 1000.0, response.status
    except HTTPError as error:
        error.read(1024)
        return (time.perf_counter() - started) * 1000.0, error.code
    except Exception:
        return (time.perf_counter() - started) * 1000.0, 599


def run_http_scenario(
    url: str,
    concurrency: int,
    requests_per_worker: int,
    timeout: float = 10.0,
    method: str = "GET",
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Run a bounded HTTP load scenario without retaining request/response bodies."""
    if concurrency < 1 or requests_per_worker < 1:
        raise ValueError("concurrency and requests_per_worker must be positive")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if method not in {"GET", "POST"}:
        raise ValueError("method must be GET or POST")

    total = concurrency * requests_per_worker
    started = time.perf_counter()
    request_headers = dict(headers or {})
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        samples = list(
            pool.map(
                lambda _index: _request(
                    url,
                    timeout,
                    method,
                    body,
                    request_headers,
                ),
                range(total),
            ),
        )
    latencies = [latency for latency, _status in samples]
    status_counts: dict[str, int] = {}
    for _latency, status in samples:
        key = str(status)
        status_counts[key] = status_counts.get(key, 0) + 1
    errors = sum(count for status, count in status_counts.items() if int(status) >= 400)
    return {
        "concurrency": concurrency,
        "requests_per_worker": requests_per_worker,
        "requests": total,
        "errors": errors,
        "error_rate": errors / total,
        "duration_ms": (time.perf_counter() - started) * 1000.0,
        "status_counts": status_counts,
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "samples_ms": latencies,
    }


def _json_request(
    url: str,
    timeout: float,
    method: str,
    body: bytes | None,
    headers: Mapping[str, str],
) -> tuple[int, dict[str, object] | None]:
    try:
        request_headers = {"User-Agent": "ml-platform-week11", **headers}
        request = Request(url, data=body, headers=request_headers, method=method)
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(65536).decode("utf-8"))
            return response.status, payload if isinstance(payload, dict) else None
    except HTTPError as error:
        error.read(65536)
        return error.code, None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 599, None


def run_workflow_scenario(
    url: str,
    completion_url_template: str,
    requests_per_worker: int,
    *,
    timeout: float = 10.0,
    completion_timeout: float = 90.0,
    poll_interval: float = 0.2,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Submit workflows sequentially and measure each terminal completion."""
    if requests_per_worker < 1:
        raise ValueError("requests_per_worker must be positive")
    if timeout <= 0 or completion_timeout <= 0 or poll_interval <= 0:
        raise ValueError("timeouts and poll interval must be positive")
    if "{run_id}" not in completion_url_template:
        raise ValueError("completion URL template must contain {run_id}")

    request_headers = dict(headers or {})
    completion_samples: list[float] = []
    terminal_status_counts: dict[str, int] = {}
    submission_status_counts: dict[str, int] = {}
    started_all = time.perf_counter()
    for _index in range(requests_per_worker):
        started = time.perf_counter()
        submission_status, submission = _json_request(
            url,
            timeout,
            "POST",
            body,
            request_headers,
        )
        submission_key = str(submission_status)
        submission_status_counts[submission_key] = (
            submission_status_counts.get(submission_key, 0) + 1
        )
        run_id = submission.get("run_id") if submission is not None else None
        terminal_status = "submission_failed"
        if submission_status < 400 and isinstance(run_id, str) and run_id:
            completion_url = completion_url_template.format(run_id=quote(run_id, safe=""))
            deadline = time.monotonic() + completion_timeout
            while time.monotonic() < deadline:
                poll_status, payload = _json_request(
                    completion_url,
                    timeout,
                    "GET",
                    None,
                    request_headers,
                )
                if poll_status >= 400 or payload is None:
                    terminal_status = f"poll_http_{poll_status}"
                    break
                observed = payload.get("status")
                if observed in {"completed", "failed", "cancelled"}:
                    terminal_status = str(observed)
                    break
                time.sleep(poll_interval)
            else:
                terminal_status = "timeout"
        terminal_status_counts[terminal_status] = (
            terminal_status_counts.get(terminal_status, 0) + 1
        )
        completion_samples.append((time.perf_counter() - started) * 1000.0)

    completed_requests = terminal_status_counts.get("completed", 0)
    errors = requests_per_worker - completed_requests
    return {
        "concurrency": 1,
        "requests_per_worker": requests_per_worker,
        "requests": requests_per_worker,
        "completed_requests": completed_requests,
        "errors": errors,
        "error_rate": errors / requests_per_worker,
        "duration_ms": max(completion_samples),
        "wall_duration_ms": (time.perf_counter() - started_all) * 1000.0,
        "status_counts": {
            "200": completed_requests,
            "500": errors,
        },
        "submission_status_counts": submission_status_counts,
        "terminal_status_counts": terminal_status_counts,
        "p50_ms": percentile(completion_samples, 0.50),
        "p95_ms": percentile(completion_samples, 0.95),
        "p99_ms": percentile(completion_samples, 0.99),
        "samples_ms": completion_samples,
        "completion_samples_ms": completion_samples,
    }


def _git_commit() -> str:
    explicit = os.getenv("ACCEPTANCE_SOURCE_COMMIT", "").strip()
    if _valid_commit(explicit):
        return explicit
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unavailable"
    return completed.stdout.strip() if completed.returncode == 0 else "unavailable"


def summarize_results(input_dir: Path, output: Path) -> dict[str, object]:
    """Summarize every raw iteration without deleting failed samples."""
    results = []
    for path in sorted(input_dir.glob("*.json")):
        if path.resolve() == output.resolve():
            continue
        try:
            raw_result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            results.append(
                {
                    "path": path.name,
                    "candidate_gates": {
                        "evidence": {
                            "passed": False,
                            "error_code": "PERFORMANCE_EVIDENCE_INVALID",
                        },
                    },
                    "scenario": "unlabeled",
                    "iteration": None,
                },
            )
            continue
        if not isinstance(raw_result, dict):
            results.append(
                {
                    "path": path.name,
                    "candidate_gates": {
                        "evidence": {
                            "passed": False,
                            "error_code": "PERFORMANCE_EVIDENCE_NOT_OBJECT",
                        },
                    },
                    "scenario": "unlabeled",
                    "iteration": None,
                },
            )
            continue
        result = dict(raw_result)
        results.append(
            {
                **result,
                "path": path.name,
                "candidate_gates": validate_iteration_evidence(result),
            },
        )

    provenance = _summary_provenance(results)
    provenance_gate = {
        "value": provenance["raw_commits"],
        "expected_current_commit": provenance["current_commit"],
        "current_commit_checked": provenance["current_commit_checked"],
        "passed": provenance["status"] == "passed",
    }
    for item in results:
        item["candidate_gates"]["commit_consistency"] = dict(provenance_gate)

    scenarios: dict[str, list[dict[str, object]]] = {}
    for result in results:
        scenario = str(result.get("scenario", "unlabeled"))
        scenarios.setdefault(scenario, []).append(result)
    scenario_statuses = {}
    for name, iterations in scenarios.items():
        iteration_values = [item.get("iteration") for item in iterations]
        required_iterations = SCENARIO_REQUIRED_ITERATIONS.get(name)
        has_required_iterations = (
            required_iterations is not None
            and len(iterations) == len(required_iterations)
            and all(_is_integer(value) for value in iteration_values)
            and set(iteration_values) == required_iterations
        )
        gates_passed = all(
            _gates_passed(item["candidate_gates"])
            for item in iterations
        )
        scenario_statuses[name] = {
            "status": "passed" if has_required_iterations and gates_passed else "failed",
            "iterations": [item["path"] for item in iterations],
        }
    required_scenarios = set(SCENARIO_REQUIRED_ITERATIONS)
    status = "passed" if (
        required_scenarios.issubset(scenarios)
        and all(item["status"] == "passed" for item in scenario_statuses.values())
    ) else "failed"
    metrics = {}
    for name in ("p50_ms", "p95_ms", "p99_ms", "error_rate"):
        values = [
            float(item[name])
            for item in results
            if name in item and _is_finite_number(item[name])
        ]
        if values:
            metrics[name] = {
                "min": min(values),
                "median": statistics.median(values),
                "max": max(values),
            }
    result = {
        "status": status,
        "candidate_status": status,
        "commit": provenance["commit"],
        "provenance": provenance,
        "iterations": results,
        "scenarios": scenario_statuses,
        "metrics": metrics,
    }
    write_result(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--url", required=True)
    run.add_argument("--concurrency", type=int, default=20)
    run.add_argument("--requests-per-worker", type=int, default=100)
    run.add_argument("--warmup", type=int, default=0)
    run.add_argument("--scenario", required=True)
    run.add_argument("--iteration", type=int, required=True)
    run.add_argument("--method", choices=("GET", "POST"), default="GET")
    run.add_argument("--body-file", type=Path)
    run.add_argument("--bearer-env")
    run.add_argument("--api-key-env")
    run.add_argument("--completion-url-template")
    run.add_argument("--completion-timeout", type=float, default=90.0)
    run.add_argument("--completion-poll-interval", type=float, default=0.2)
    run.add_argument("--output", type=Path, required=True)
    summary = subparsers.add_parser("summarize")
    summary.add_argument("--input-dir", type=Path, required=True)
    summary.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "summarize":
        result = summarize_results(args.input_dir, args.output)
        return 0 if result["status"] == "passed" else 1

    body = args.body_file.read_bytes() if args.body_file else None
    headers = {"Content-Type": "application/json"} if body else {}
    if args.bearer_env:
        headers["Authorization"] = f"Bearer {os.environ[args.bearer_env]}"
    if args.api_key_env:
        headers["X-Inference-Api-Key"] = os.environ[args.api_key_env]
    if args.scenario == "welding-e2e":
        if args.concurrency != 1 or not args.completion_url_template:
            parser.error(
                "welding-e2e requires concurrency 1 and --completion-url-template",
            )
        if args.warmup:
            run_workflow_scenario(
                args.url,
                args.completion_url_template,
                args.warmup,
                completion_timeout=args.completion_timeout,
                poll_interval=args.completion_poll_interval,
                body=body,
                headers=headers,
            )
        result = run_workflow_scenario(
            args.url,
            args.completion_url_template,
            args.requests_per_worker,
            completion_timeout=args.completion_timeout,
            poll_interval=args.completion_poll_interval,
            body=body,
            headers=headers,
        )
    else:
        if args.warmup:
            run_http_scenario(
                args.url,
                args.concurrency,
                args.warmup,
                method=args.method,
                body=body,
                headers=headers,
            )
        result = run_http_scenario(
            args.url,
            args.concurrency,
            args.requests_per_worker,
            method=args.method,
            body=body,
            headers=headers,
        )
    result.update(
        {
            "scenario": args.scenario,
            "iteration": args.iteration,
            "commit": _git_commit(),
        },
    )
    write_result(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
