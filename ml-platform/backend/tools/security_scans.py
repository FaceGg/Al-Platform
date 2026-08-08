"""Redacted wrappers for Week 12 source, dependency, and secret scan gates."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Callable, Mapping, Sequence
from uuid import uuid4

import httpx
from app.events.domain import create_domain_event
from app.services.notification_channels import WebhookNotificationAdapter
from tools.redaction import redact_text


_SENSITIVE_KEY_MARKERS = (
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "api-key",
    "apikey",
    "access_key",
    "access-key",
    "accesskey",
)
REQUIRED_SCAN_GATES = frozenset(
    {
        "python_dependencies",
        "source_bandit",
        "frontend_dependencies",
        "filesystem_trivy",
        "container_image",
        "secret_gitleaks",
        "web_security",
    },
)
REQUIRED_SCAN_EVIDENCE_FILES = {
    "python_dependencies": "pip-audit.json",
    "source_bandit": "bandit.json",
    "frontend_dependencies": "npm-audit.json",
    "filesystem_trivy": "trivy-fs.json",
    "container_image": "trivy-image.json",
    "secret_gitleaks": "gitleaks.json",
    "web_security": "web.json",
}
WEB_SECURITY_GATE_NAMES = frozenset(
    {
        "outsider_hidden",
        "outsider_endpoint_hidden",
        "outsider_mutation_hidden",
        "viewer_read",
        "operator_read",
        "viewer_manage_denied",
        "operator_manage_denied",
        "editor_endpoint_test",
        "owner_endpoint_test",
        "ssrf_loopback",
        "ssrf_private",
        "ssrf_link_local",
        "ssrf_metadata",
        "ssrf_ipv6_loopback",
        "redirect_escape",
        "oversized_request",
        "notification_payload_limit",
        "notification_timeout",
    },
)
_FRONTEND_SOURCE_SUFFIXES = frozenset({".cjs", ".js", ".jsx", ".mjs", ".ts", ".tsx"})
_FRONTEND_IGNORED_DIRECTORIES = frozenset({"dist", "node_modules"})
_REACT_ROUTER_SERVER_PATTERNS = (
    re.compile(r"(?:react-router(?:-dom)?/server)"),
    re.compile(r"\b(?:createRequestHandler|createStaticHandler|createStaticRouter)\b"),
    re.compile(r"\b(?:HydratedRouter|ServerRouter|RSCStaticRouter|RSCHydratedRouter)\b"),
    re.compile(r"\b(?:prerender|ActionFunction)\b", re.IGNORECASE),
    re.compile(r"[\"']?ssr[\"']?\s*:\s*true\b", re.IGNORECASE),
    re.compile(
        r"\b(?:export\s+(?:async\s+)?(?:function|const)\s+action|"
        r"action\s*:\s*(?:(?:async\s+)?function\b|"
        r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>|"
        r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?=\s*[,}])))",
        re.IGNORECASE,
    ),
)
_ROUTE_ACTION_SHORTHAND_PATTERN = re.compile(
    r"\b(?:routes?|routeConfig)(?:\s*:\s*[^=;\n]+)?\s*=\s*\[[^\]]*\{[^{}]*\baction\s*(?=[,}])",
    re.IGNORECASE | re.DOTALL,
)
_TYPESCRIPT_TYPE_DECLARATION_START_PATTERN = re.compile(
    r"\b(?:export\s+)?(?:declare\s+)?(?:"
    r"interface\s+[A-Za-z_$][\w$]*(?:\s+extends\s+[^\r\n{}]+)?|"
    r"type\s+[A-Za-z_$][\w$]*(?:\s*<[^{}>]*>)?\s*=)"
    r"[^;\r\n{}]*\{",
)


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: object


@dataclass(frozen=True)
class RawJsonBody:
    """Preserve a deliberately oversized JSON request for the live API probe."""

    body: str


@dataclass(frozen=True)
class _ProbeResponse:
    status_code: int


class _ProbeHttpClient:
    def __init__(
        self,
        *,
        response: _ProbeResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or _ProbeResponse(202)
        self.error = error
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _ProbeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response


def redact_scan_output(value: str) -> str:
    """Redact credential-like strings while retaining useful scanner context."""
    return redact_text(value)


def _redact_command(command: Sequence[str]) -> list[str]:
    safe = []
    for index, item in enumerate(command):
        value = str(item)
        if index == 0:
            safe.append(Path(value).name)
        elif "://" in value:
            safe.append("[redacted-url]")
        else:
            safe.append(redact_scan_output(value))
    return safe


def _redact_json_value(value: object) -> object:
    if isinstance(value, str):
        return redact_scan_output(value)
    if isinstance(value, list):
        return [_redact_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): (
                _redact_json_value(item)
                if str(key) in REQUIRED_SCAN_GATES
                else (
                    "[redacted]"
                    if any(marker in str(key).casefold() for marker in _SENSITIVE_KEY_MARKERS)
                    else _redact_json_value(item)
                )
            )
            for key, item in value.items()
        }
    return value


def run_scan(command: list[str]) -> dict[str, object]:
    """Capture a scanner outcome without allowing command output to leak secrets."""
    try:
        completed = subprocess.run(
            [str(item) for item in command],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return {
            "command": _redact_command(command),
            "status": "failed",
            "returncode": None,
            "stdout": "",
            "stderr": redact_scan_output(str(error))[-10000:],
        }
    return {
        "command": _redact_command(command),
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": redact_scan_output(completed.stdout or "")[-10000:],
        "stderr": redact_scan_output(completed.stderr or "")[-10000:],
    }


def _write_redacted_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_value = _redact_json_value(value)
    path.write_text(
        json.dumps(safe_value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _persist_scan_evidence(path: Path, result: Mapping[str, object]) -> None:
    """Keep a distinct, redacted JSON artifact even when a scanner cannot start."""
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {"scanner_result": dict(result)}
    _write_redacted_json(path, value)


def _npm_audit_exception_failure(error_code: str) -> dict[str, object]:
    return {"status": "failed", "error_code": error_code}


def _read_exception(path: Path) -> Mapping[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _frontend_package_versions(frontend_directory: Path) -> Mapping[str, str] | None:
    try:
        lockfile = json.loads(
            (frontend_directory / "package-lock.json").read_text(encoding="utf-8"),
        )
        packages = lockfile["packages"]
        router = packages["node_modules/react-router"]["version"]
        router_dom = packages["node_modules/react-router-dom"]["version"]
    except (KeyError, OSError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(router, str) or not isinstance(router_dom, str):
        return None
    return {"react-router": router, "react-router-dom": router_dom}


def _source_without_typescript_type_declarations(source: str) -> str:
    """Mask type-only object declarations before scanning runtime router APIs."""
    masked = list(source)
    for match in _TYPESCRIPT_TYPE_DECLARATION_START_PATTERN.finditer(source):
        opening_brace = source.find("{", match.start(), match.end())
        depth = 0
        for index in range(opening_brace, len(source)):
            character = source[index]
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    masked[match.start() : index + 1] = " " * (index + 1 - match.start())
                    break
    return "".join(masked)


def _frontend_uses_react_router_server_api(frontend_directory: Path) -> bool:
    if not frontend_directory.is_dir():
        return True
    for path in frontend_directory.rglob("*"):
        try:
            relative_parts = path.relative_to(frontend_directory).parts
        except ValueError:
            return True
        if any(part in _FRONTEND_IGNORED_DIRECTORIES for part in relative_parts):
            continue
        if not path.is_file() or path.suffix not in _FRONTEND_SOURCE_SUFFIXES:
            continue
        if path.name.startswith("entry.server."):
            return True
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            return True
        runtime_source = _source_without_typescript_type_declarations(source)
        if (
            any(pattern.search(runtime_source) for pattern in _REACT_ROUTER_SERVER_PATTERNS)
            or _ROUTE_ACTION_SHORTHAND_PATTERN.search(runtime_source)
        ):
            return True
    return False


def evaluate_npm_audit_exception(
    audit_report: Mapping[str, object],
    *,
    exception_path: Path,
    frontend_directory: Path,
    today: date | None = None,
) -> dict[str, object]:
    """Allow only the reviewed, time-bound BrowserRouter advisory exception."""
    exception = _read_exception(exception_path)
    if exception is None:
        return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_INVALID")

    try:
        schema_version = exception["schema_version"]
        exception_id = exception["id"]
        owner = exception["owner"]
        reviewed_at = exception["reviewed_at"]
        expires_on = exception["expires_on"]
        package_versions = exception["package_versions"]
        advisory_sources = exception["advisory_sources"]
        mitigation = exception["mitigation"]
    except KeyError:
        return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_INVALID")
    if (
        schema_version != 1
        or not isinstance(exception_id, str)
        or not exception_id
        or not isinstance(owner, str)
        or not owner
        or not isinstance(reviewed_at, str)
        or not isinstance(expires_on, str)
        or not isinstance(package_versions, dict)
        or not isinstance(advisory_sources, list)
        or not isinstance(mitigation, str)
        or "BrowserRouter" not in mitigation
    ):
        return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_INVALID")
    try:
        review_date = date.fromisoformat(reviewed_at)
        expiry_date = date.fromisoformat(expires_on)
    except ValueError:
        return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_INVALID")
    current_date = today or date.today()
    if review_date > current_date or expiry_date < current_date:
        return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_EXPIRED")

    expected_versions = {"react-router", "react-router-dom"}
    if set(package_versions) != expected_versions or not all(
        isinstance(name, str) and isinstance(version, str) and version
        for name, version in package_versions.items()
    ):
        return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_INVALID")
    installed_versions = _frontend_package_versions(frontend_directory)
    if installed_versions != package_versions:
        return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_VERSION_MISMATCH")
    if _frontend_uses_react_router_server_api(frontend_directory):
        return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    vulnerabilities = audit_report.get("vulnerabilities")
    metadata = audit_report.get("metadata")
    if not isinstance(vulnerabilities, dict) or not isinstance(metadata, dict):
        return _npm_audit_exception_failure("NPM_AUDIT_REPORT_INVALID")
    expected_packages = set(package_versions)
    if set(vulnerabilities) != expected_packages:
        return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_ADVISORY_MISMATCH")
    if not all(type(source) is int for source in advisory_sources):
        return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_INVALID")
    expected_sources = set(advisory_sources)
    reported_sources: set[int] = set()
    for name in sorted(expected_packages):
        vulnerability = vulnerabilities.get(name)
        if not isinstance(vulnerability, dict) or vulnerability.get("severity") != "high":
            return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_ADVISORY_MISMATCH")
        via = vulnerability.get("via")
        if not isinstance(via, list):
            return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_ADVISORY_MISMATCH")
        for item in via:
            if isinstance(item, dict) and isinstance(item.get("source"), int):
                reported_sources.add(item["source"])
    vulnerability_counts = metadata.get("vulnerabilities")
    if (
        not isinstance(vulnerability_counts, dict)
        or vulnerability_counts.get("high") != len(expected_packages)
        or vulnerability_counts.get("critical") != 0
        or vulnerability_counts.get("total") != len(expected_packages)
        or reported_sources != expected_sources
    ):
        return _npm_audit_exception_failure("NPM_AUDIT_EXCEPTION_ADVISORY_MISMATCH")
    return {
        "status": "passed",
        "exception": {
            "id": exception_id,
            "owner": owner,
            "reviewed_at": reviewed_at,
            "expires_on": expires_on,
        },
    }


def _run_frontend_dependency_scan(
    command: list[str],
    *,
    exception_path: Path,
    frontend_directory: Path,
    evidence_path: Path,
) -> dict[str, object]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as error:
        result = {
            "command": _redact_command(command),
            "status": "failed",
            "returncode": None,
            "stdout": "",
            "stderr": redact_scan_output(str(error))[-10000:],
        }
        _persist_scan_evidence(evidence_path, result)
        return result
    result = {
        "command": _redact_command(command),
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": redact_scan_output(completed.stdout or "")[-10000:],
        "stderr": redact_scan_output(completed.stderr or "")[-10000:],
    }
    try:
        audit_report = json.loads(completed.stdout or "")
    except json.JSONDecodeError:
        result["error_code"] = "NPM_AUDIT_REPORT_INVALID"
        _persist_scan_evidence(evidence_path, result)
        return result
    _write_redacted_json(evidence_path, audit_report)
    if completed.returncode == 0:
        return result
    exception = evaluate_npm_audit_exception(
        audit_report,
        exception_path=exception_path,
        frontend_directory=frontend_directory,
    )
    if exception["status"] != "passed":
        result["error_code"] = exception["error_code"]
        return result
    result["status"] = "passed"
    result["exception"] = exception["exception"]
    return result


def run_all(
    output: str | Path,
    *,
    npm_audit_exception: Path | None = None,
) -> dict[str, object]:
    """Run required local scanner commands and persist one aggregate gate result."""
    image_ref = os.getenv("ACCEPTANCE_IMAGE", "")
    repository_root = Path(__file__).resolve().parents[3]
    frontend_directory = Path(__file__).resolve().parents[2] / "frontend"
    output_path = Path(output)
    evidence_directory = output_path.parent
    evidence_directory.mkdir(parents=True, exist_ok=True)
    report_paths = {
        "python_dependencies": evidence_directory / "pip-audit.json",
        "source_bandit": evidence_directory / "bandit.json",
        "frontend_dependencies": evidence_directory / "npm-audit.json",
        "filesystem_trivy": evidence_directory / "trivy-fs.json",
        "container_image": evidence_directory / "trivy-image.json",
        "secret_gitleaks": evidence_directory / "gitleaks.json",
    }

    frontend_command = [
        "npm",
        "--prefix",
        str(frontend_directory),
        "audit",
        "--audit-level=high",
        "--registry=https://registry.npmjs.org",
        "--json",
    ]

    def scanner_gate(name: str, command: list[str]) -> dict[str, object]:
        result = run_scan(command)
        _persist_scan_evidence(report_paths[name], result)
        return result

    frontend_result = (
        _run_frontend_dependency_scan(
            frontend_command,
            exception_path=npm_audit_exception,
            frontend_directory=frontend_directory,
            evidence_path=report_paths["frontend_dependencies"],
        )
        if npm_audit_exception is not None
        else scanner_gate("frontend_dependencies", frontend_command)
    )
    gates = {
        "python_dependencies": scanner_gate(
            "python_dependencies",
            [
                sys.executable,
                "-m",
                "pip_audit",
                "-r",
                "requirements.txt",
                "--format",
                "json",
                "--output",
                str(report_paths["python_dependencies"]),
            ],
        ),
        "source_bandit": scanner_gate(
            "source_bandit",
            [
                "bandit",
                "-r",
                "app",
                "-q",
                "-lll",
                "-f",
                "json",
                "-o",
                str(report_paths["source_bandit"]),
            ],
        ),
        "frontend_dependencies": frontend_result,
        "filesystem_trivy": scanner_gate(
            "filesystem_trivy",
            [
                "trivy",
                "fs",
                "--exit-code",
                "1",
                "--severity",
                "HIGH,CRITICAL",
                "--format",
                "json",
                "--output",
                str(report_paths["filesystem_trivy"]),
                str(repository_root),
            ],
        ),
        "container_image": (
            scanner_gate(
                "container_image",
                [
                    "trivy",
                    "image",
                    "--exit-code",
                    "1",
                    "--severity",
                    "HIGH,CRITICAL",
                    "--format",
                    "json",
                    "--output",
                    str(report_paths["container_image"]),
                    image_ref,
                ],
            )
            if image_ref
            else {"status": "failed", "error_code": "ACCEPTANCE_IMAGE_REQUIRED"}
        ),
        "secret_gitleaks": scanner_gate(
            "secret_gitleaks",
            [
                "gitleaks",
                "detect",
                "--no-banner",
                "--redact",
                "--report-format",
                "json",
                "--report-path",
                str(report_paths["secret_gitleaks"]),
                "--source",
                str(repository_root),
            ],
        ),
    }
    if not image_ref:
        _persist_scan_evidence(report_paths["container_image"], gates["container_image"])
    result = {
        "status": "passed" if all(item["status"] == "passed" for item in gates.values()) else "failed",
        "gates": gates,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def summarize_scans(input_dir: Path, output: Path) -> dict[str, object]:
    """Bind every raw scanner result into a single fail-closed status."""
    try:
        input_root = input_dir.resolve(strict=True)
    except OSError:
        input_root = None

    def read_evidence(path: Path) -> tuple[object | None, str | None]:
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            return None, "SECURITY_EVIDENCE_MISSING"
        except OSError:
            return None, "SECURITY_EVIDENCE_INVALID"
        if (
            input_root is None
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            return None, "SECURITY_EVIDENCE_INVALID"
        try:
            resolved_candidate = path.resolve(strict=True)
            resolved_candidate.relative_to(input_root)
            return json.loads(resolved_candidate.read_text(encoding="utf-8")), None
        except (OSError, ValueError, json.JSONDecodeError):
            return None, "SECURITY_EVIDENCE_INVALID"

    collected: dict[str, list[dict[str, object]]] = {}
    invalid_aggregate = False
    invalid_web_evidence = False
    for path in sorted(input_dir.rglob("*.json")):
        if path.absolute() == output.absolute():
            continue
        value, error_code = read_evidence(path)
        if error_code is not None:
            if path.name == "security.json":
                invalid_aggregate = True
            elif path.name == "web.json":
                invalid_web_evidence = True
            continue
        safe_value = (
            _redact_json_value(value)
            if isinstance(value, dict)
            else {"status": "failed"}
        )
        if path.name == "web.json":
            collected.setdefault("web_security", []).append(
                safe_value
                if _complete_web_gate(safe_value)
                else {
                    "status": "failed",
                    "error_code": "WEB_SECURITY_GATE_INCOMPLETE",
                }
            )
            continue
        nested_gates = safe_value.get("gates") if isinstance(safe_value, dict) else None
        if not isinstance(nested_gates, dict):
            continue
        for name, gate in nested_gates.items():
            if name in REQUIRED_SCAN_GATES and isinstance(gate, dict):
                collected.setdefault(name, []).append(gate)

    def evidence_error(relative_path: str) -> str | None:
        value, error_code = read_evidence(input_dir / relative_path)
        if error_code is not None:
            return error_code
        return None if isinstance(value, (dict, list)) else "SECURITY_EVIDENCE_INVALID"

    gates = {}
    for name in sorted(REQUIRED_SCAN_GATES):
        relative_path = REQUIRED_SCAN_EVIDENCE_FILES[name]
        candidates = collected.get(name, [])
        if invalid_aggregate and name != "web_security":
            gates[name] = {
                "status": "failed",
                "error_code": "SECURITY_EVIDENCE_INVALID",
                "evidence_path": relative_path,
            }
        elif invalid_web_evidence and name == "web_security":
            gates[name] = {
                "status": "failed",
                "error_code": "SECURITY_EVIDENCE_INVALID",
                "evidence_path": relative_path,
            }
        elif (error_code := evidence_error(relative_path)) is not None:
            gates[name] = {
                "status": "failed",
                "error_code": error_code,
                "evidence_path": relative_path,
            }
        elif len(candidates) != 1:
            gates[name] = {
                "status": "failed",
                "error_code": "SECURITY_GATE_MISSING" if not candidates else "SECURITY_GATE_DUPLICATE",
                "evidence_path": relative_path,
            }
        else:
            gates[name] = {**candidates[0], "evidence_path": relative_path}
    result = {
        "status": "passed" if all(
            item.get("status") == "passed" for item in gates.values()
        ) else "failed",
        "gates": gates,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _complete_web_gate(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"status", "gates"}:
        return False
    if value.get("status") != "passed":
        return False
    gates = value.get("gates")
    if not isinstance(gates, dict) or set(gates) != WEB_SECURITY_GATE_NAMES:
        return False
    return all(
        isinstance(gate, dict) and gate.get("status") == "passed"
        for gate in gates.values()
    )


def load_web_context(path: Path) -> dict[str, str]:
    """Load the ephemeral role tokens without serializing them into scan evidence."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "project_id",
            "endpoint_id",
            "user_ids",
            "tokens",
        }:
            raise ValueError
        tokens = value["tokens"]
        user_ids = value["user_ids"]
        if (
            value["schema_version"] != 1
            or not isinstance(value["project_id"], str)
            or not value["project_id"]
            or not isinstance(value["endpoint_id"], str)
            or not value["endpoint_id"]
            or not isinstance(tokens, dict)
            or not isinstance(user_ids, dict)
            or set(tokens) != {"owner", "editor", "operator", "viewer", "outsider"}
            or set(user_ids) != {"owner", "editor", "operator", "viewer", "outsider"}
            or not all(isinstance(token, str) and token for token in tokens.values())
            or not all(isinstance(user_id, str) and user_id for user_id in user_ids.values())
        ):
            raise ValueError
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise ValueError("WEB_SCAN_CONTEXT_INVALID") from None
    return {
        "WEB_SCAN_PROJECT_ID": value["project_id"],
        "WEB_SCAN_ENDPOINT_ID": value["endpoint_id"],
        **{
            f"WEB_SCAN_{role.upper()}_TOKEN": tokens[role]
            for role in ("owner", "editor", "operator", "viewer", "outsider")
        },
    }


def _default_web_request(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: object | None,
) -> HttpResponse:
    try:
        request_headers = dict(headers)
        request_kwargs: dict[str, object] = {
            "headers": request_headers,
            "timeout": 5.0,
            "follow_redirects": False,
        }
        if isinstance(payload, RawJsonBody):
            request_headers.setdefault("Content-Type", "application/json")
            request_kwargs["content"] = payload.body.encode("utf-8")
        else:
            request_kwargs["json"] = payload
        response = httpx.request(
            method,
            url,
            **request_kwargs,
        )
        try:
            body: object = response.json()
        except ValueError:
            body = {}
        return HttpResponse(response.status_code, body)
    except httpx.HTTPError:
        return HttpResponse(0, {})


def _webhook_probe_event(payload: Mapping[str, object]):
    return create_domain_event(
        idempotency_key=f"week12-web-security-{uuid4().hex}",
        event_type="rollout.completed",
        severity="info",
        occurred_at=datetime.now(timezone.utc),
        project_id=None,
        actor_id=None,
        resource_type="web_security_gate",
        resource_id=None,
        payload=payload,
    )


def _webhook_adapter_probe(
    client: _ProbeHttpClient,
    *,
    max_payload_bytes: int = 65536,
) -> WebhookNotificationAdapter:
    return WebhookNotificationAdapter(
        {
            "url": "https://security-probe.example.invalid/events",
            "headers": {},
            "signature_mode": "none",
        },
        http_client=client,
        timeout_seconds=2,
        max_payload_bytes=max_payload_bytes,
        resolve=lambda _host, _port: ("8.8.8.8",),
        allowlist=(),
    )


def _controlled_webhook_probes() -> dict[str, dict[str, object]]:
    redirect_client = _ProbeHttpClient(response=_ProbeResponse(302))
    redirect = _webhook_adapter_probe(redirect_client).send(
        endpoint=None,  # type: ignore[arg-type]
        event=_webhook_probe_event({"deployment_id": "security-probe"}),
        delivery_key="redirect-probe",
    )

    payload_client = _ProbeHttpClient()
    payload_limit = _webhook_adapter_probe(payload_client, max_payload_bytes=128).send(
        endpoint=None,  # type: ignore[arg-type]
        event=_webhook_probe_event({"error_code": "x" * 512}),
        delivery_key="payload-probe",
    )

    timeout_client = _ProbeHttpClient(error=httpx.TimeoutException("controlled timeout"))
    timeout = _webhook_adapter_probe(timeout_client).send(
        endpoint=None,  # type: ignore[arg-type]
        event=_webhook_probe_event({"deployment_id": "security-probe"}),
        delivery_key="timeout-probe",
    )

    return {
        "redirect_escape": {
            "status": "passed"
            if (
                redirect.status == "failed"
                and redirect.error_code == "NOTIFICATION_PROVIDER_REJECTED"
                and len(redirect_client.calls) == 1
                and redirect_client.calls[0].get("follow_redirects") is False
            )
            else "failed",
        },
        "notification_payload_limit": {
            "status": "passed"
            if (
                payload_limit.status == "failed"
                and payload_limit.error_code == "NOTIFICATION_PAYLOAD_TOO_LARGE"
                and not payload_client.calls
            )
            else "failed",
        },
        "notification_timeout": {
            "status": "passed"
            if (
                timeout.status == "retry"
                and timeout.error_code == "NOTIFICATION_PROVIDER_UNAVAILABLE"
                and len(timeout_client.calls) == 1
                and timeout_client.calls[0].get("timeout") == 2
            )
            else "failed",
        },
    }


def run_web_gate(
    base_url: str,
    *,
    environment: Mapping[str, str] | None = None,
    request: Callable[[str, str, Mapping[str, str], object | None], HttpResponse] | None = None,
) -> dict[str, object]:
    """Exercise frozen notification authorization and SSRF boundaries safely."""
    values = os.environ if environment is None else environment
    required = {
        "project_id": values.get("WEB_SCAN_PROJECT_ID", ""),
        "endpoint_id": values.get("WEB_SCAN_ENDPOINT_ID", ""),
        "owner_token": values.get("WEB_SCAN_OWNER_TOKEN", ""),
        "editor_token": values.get("WEB_SCAN_EDITOR_TOKEN", ""),
        "operator_token": values.get("WEB_SCAN_OPERATOR_TOKEN", ""),
        "viewer_token": values.get("WEB_SCAN_VIEWER_TOKEN", ""),
        "outsider_token": values.get("WEB_SCAN_OUTSIDER_TOKEN", ""),
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        return {
            "status": "failed",
            "gates": {
                "identity_context": {
                    "status": "failed",
                    "code": "WEB_SCAN_CONTEXT_MISSING",
                    "missing": missing,
                },
            },
        }

    call = request or _default_web_request
    root = base_url.rstrip("/")
    endpoint_collection = (
        f"{root}/api/projects/{required['project_id']}/notification-endpoints"
    )
    endpoint_test = f"{endpoint_collection}/{required['endpoint_id']}/test"

    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def result(response: HttpResponse, expected: set[int]) -> dict[str, object]:
        return {
            "status": "passed" if response.status_code in expected else "failed",
            "status_code": response.status_code,
            "expected_statuses": sorted(expected),
        }

    def endpoint_test_result(response: HttpResponse) -> dict[str, object]:
        gate = result(response, {200})
        body = response.body
        if (
            gate["status"] != "passed"
            or not isinstance(body, Mapping)
            or set(body) != {"status", "error_code"}
            or body.get("status") != "sent"
            or body.get("error_code") is not None
        ):
            gate["status"] = "failed"
        return gate

    def blocked_webhook(url: str) -> dict[str, object]:
        response = call(
            "POST",
            endpoint_collection,
            headers(required["owner_token"]),
            {
                "kind": "webhook",
                "name": "week12-security-probe",
                "config": {"url": url, "headers": {}, "signature_mode": "none"},
            },
        )
        return result(response, {422})

    oversized_request = RawJsonBody(
        json.dumps(
            {
                "kind": "in_app",
                "name": "week12-oversized-request",
                "config": {
                    "recipient_user_ids": ["00000000-0000-0000-0000-000000000001"],
                },
            },
            separators=(",", ":"),
        )
        + (" " * 1_048_577)
    )

    gates = {
        "outsider_hidden": result(
            call("GET", endpoint_collection, headers(required["outsider_token"]), None),
            {404},
        ),
        "outsider_endpoint_hidden": result(
            call("POST", endpoint_test, headers(required["outsider_token"]), None),
            {404},
        ),
        "outsider_mutation_hidden": result(
            call(
                "POST",
                endpoint_collection,
                headers(required["outsider_token"]),
                {
                    "kind": "in_app",
                    "name": "week12-outsider-probe",
                    "config": {
                        "recipient_user_ids": ["00000000-0000-0000-0000-000000000001"],
                    },
                },
            ),
            {404},
        ),
        "viewer_read": result(
            call("GET", endpoint_collection, headers(required["viewer_token"]), None),
            {200},
        ),
        "operator_read": result(
            call("GET", endpoint_collection, headers(required["operator_token"]), None),
            {200},
        ),
        "viewer_manage_denied": result(
            call("POST", endpoint_test, headers(required["viewer_token"]), None),
            {403},
        ),
        "operator_manage_denied": result(
            call("POST", endpoint_test, headers(required["operator_token"]), None),
            {403},
        ),
        "editor_endpoint_test": endpoint_test_result(
            call("POST", endpoint_test, headers(required["editor_token"]), None),
        ),
        "owner_endpoint_test": endpoint_test_result(
            call("POST", endpoint_test, headers(required["owner_token"]), None),
        ),
        "ssrf_loopback": blocked_webhook("https://127.0.0.1/notification"),
        "ssrf_private": blocked_webhook("https://10.0.0.1/notification"),
        "ssrf_link_local": blocked_webhook("https://169.254.1.1/notification"),
        "ssrf_metadata": blocked_webhook(
            "https://169.254.169.254/latest/meta-data",
        ),
        "ssrf_ipv6_loopback": blocked_webhook("https://[::1]/notification"),
        "oversized_request": result(
            call(
                "POST",
                endpoint_collection,
                headers(required["owner_token"]),
                oversized_request,
            ),
            {413},
        ),
        **_controlled_webhook_probes(),
    }
    return {
        "status": "passed" if all(gate["status"] == "passed" for gate in gates.values()) else "failed",
        "gates": gates,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    all_scans = subparsers.add_parser("all")
    all_scans.add_argument("--output", type=Path, required=True)
    all_scans.add_argument("--npm-audit-exception", type=Path)
    summary = subparsers.add_parser("summarize")
    summary.add_argument("--input-dir", type=Path, required=True)
    summary.add_argument("--output", type=Path, required=True)
    web = subparsers.add_parser("web")
    web.add_argument("--base-url", required=True)
    web.add_argument("--context", type=Path)
    web.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "all":
        result = run_all(
            args.output,
            npm_audit_exception=args.npm_audit_exception,
        )
    elif args.command == "summarize":
        result = summarize_scans(args.input_dir, args.output)
    else:
        try:
            environment = load_web_context(args.context) if args.context else None
            result = run_web_gate(args.base_url, environment=environment)
        except ValueError:
            result = {
                "status": "failed",
                "gates": {
                    "identity_context": {
                        "status": "failed",
                        "code": "WEB_SCAN_CONTEXT_INVALID",
                    },
                },
            }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
