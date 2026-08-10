"""Redacted wrappers for Week 12 source, dependency, and secret scan gates."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
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
_FRONTEND_SOURCE_SUFFIXES = frozenset(
    {".cjs", ".cts", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx"},
)
_TYPESCRIPT_SOURCE_SUFFIXES = frozenset({".cts", ".mts", ".ts", ".tsx"})
_FRONTEND_IGNORED_DIRECTORIES = frozenset({"dist", "node_modules"})
_ACTION_MEMBER_SEPARATOR = r"(?:\s|/\*[\s\S]*?\*/|//[^\r\n]*(?:\r?\n|$))*"
_REACT_ROUTER_FACTORY_NAMES = frozenset(
    {"createBrowserRouter", "createHashRouter", "createMemoryRouter"},
)
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
        rf"[A-Za-z_$][\w$]*(?:(?:{_ACTION_MEMBER_SEPARATOR}(?:\?\.|\.)"
        rf"{_ACTION_MEMBER_SEPARATOR}[A-Za-z_$][\w$]*)|"
        rf"(?:{_ACTION_MEMBER_SEPARATOR}(?:\?\.)?{_ACTION_MEMBER_SEPARATOR}"
        r"\[[^\]\r\n]+\]))*(?=\s*[,}])))",
        re.IGNORECASE,
    ),
)
_ROUTE_ACTION_SHORTHAND_PATTERN = re.compile(
    r"\b(?:routes?|routeConfig)(?:\s*:\s*[^=;\n]+)?\s*=\s*\[[^\]]*\{[^{}]*\baction\s*(?=[,}])",
    re.IGNORECASE | re.DOTALL,
)
_ROUTE_ACTION_EXTRACTED_DECLARATION_PATTERN = re.compile(
    r"\b(?:const|let|var)\s+(?P<route>[A-Za-z_$][\w$]*)"
    r"(?:\s*:\s*[^=;\n]+)?\s*=\s*\{",
    re.IGNORECASE,
)
_ROUTE_ROOT_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:routes|routeConfig)(?:\s*:\s*[^=;\n]+)?\s*=\s*",
    re.IGNORECASE,
)
_JSX_ELEMENT_START_PATTERN = re.compile(
    r"<\s*(?P<tag>[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*)\b",
)
_REACT_ROUTER_NAMED_IMPORT_PATTERN = re.compile(
    rf"\bimport{_ACTION_MEMBER_SEPARATOR}\{{(?P<bindings>[^}}]*)\}}"
    rf"{_ACTION_MEMBER_SEPARATOR}from{_ACTION_MEMBER_SEPARATOR}"
    r"[\"']react-router(?:-dom)?[\"']",
    re.DOTALL,
)
_REACT_ROUTER_ROUTE_REEXPORT_PATTERN = re.compile(
    rf"\bexport{_ACTION_MEMBER_SEPARATOR}\{{(?P<bindings>[^}}]*)\}}"
    rf"{_ACTION_MEMBER_SEPARATOR}from{_ACTION_MEMBER_SEPARATOR}"
    r"[\"']react-router(?:-dom)?[\"']",
    re.DOTALL,
)
_REACT_ROUTER_NAMESPACE_IMPORT_PATTERN = re.compile(
    rf"\bimport{_ACTION_MEMBER_SEPARATOR}\*{_ACTION_MEMBER_SEPARATOR}as"
    rf"{_ACTION_MEMBER_SEPARATOR}[A-Za-z_$][\w$]*{_ACTION_MEMBER_SEPARATOR}from"
    rf"{_ACTION_MEMBER_SEPARATOR}[\"']react-router(?:-dom)?[\"']",
    re.DOTALL,
)
_REACT_ROUTER_DEFAULT_IMPORT_PATTERN = re.compile(
    rf"\bimport{_ACTION_MEMBER_SEPARATOR}(?!type\b)[A-Za-z_$][\w$]*"
    rf"{_ACTION_MEMBER_SEPARATOR}from{_ACTION_MEMBER_SEPARATOR}"
    r"[\"']react-router(?:-dom)?[\"']",
    re.DOTALL,
)
_REACT_ROUTER_MIXED_IMPORT_PATTERN = re.compile(
    rf"\bimport{_ACTION_MEMBER_SEPARATOR}(?!type\b)[A-Za-z_$][\w$]*"
    rf"{_ACTION_MEMBER_SEPARATOR},{_ACTION_MEMBER_SEPARATOR}"
    rf"(?:\{{[^}};]*\}}|\*{_ACTION_MEMBER_SEPARATOR}as"
    rf"{_ACTION_MEMBER_SEPARATOR}[A-Za-z_$][\w$]*){_ACTION_MEMBER_SEPARATOR}"
    rf"from{_ACTION_MEMBER_SEPARATOR}[\"']react-router(?:-dom)?[\"']",
    re.DOTALL,
)
_RUNTIME_MODULE_LOAD_PATTERN = re.compile(
    rf"\b(?P<loader>import|require){_ACTION_MEMBER_SEPARATOR}(?P<opening>\()",
    re.DOTALL,
)
_REACT_ROUTER_NAMESPACE_REEXPORT_PATTERN = re.compile(
    rf"\bexport{_ACTION_MEMBER_SEPARATOR}\*"
    rf"(?:{_ACTION_MEMBER_SEPARATOR}as{_ACTION_MEMBER_SEPARATOR}[A-Za-z_$][\w$]*)?"
    rf"{_ACTION_MEMBER_SEPARATOR}from{_ACTION_MEMBER_SEPARATOR}"
    r"[\"']react-router(?:-dom)?[\"']",
    re.DOTALL,
)
_LOCAL_NAMED_IMPORT_PATTERN = re.compile(
    rf"\bimport{_ACTION_MEMBER_SEPARATOR}\{{(?P<bindings>[^}}]*)\}}"
    rf"{_ACTION_MEMBER_SEPARATOR}from{_ACTION_MEMBER_SEPARATOR}"
    r"[\"'](?P<specifier>\.[^\"']+)[\"']",
    re.DOTALL,
)
_LOCAL_NAMED_REEXPORT_PATTERN = re.compile(
    rf"\bexport{_ACTION_MEMBER_SEPARATOR}\{{(?P<bindings>[^}}]*)\}}"
    rf"{_ACTION_MEMBER_SEPARATOR}from{_ACTION_MEMBER_SEPARATOR}"
    r"[\"'](?P<specifier>\.[^\"']+)[\"']",
    re.DOTALL,
)
_LOCAL_STAR_REEXPORT_PATTERN = re.compile(
    rf"\bexport{_ACTION_MEMBER_SEPARATOR}\*{_ACTION_MEMBER_SEPARATOR}from"
    rf"{_ACTION_MEMBER_SEPARATOR}[\"'](?P<specifier>\.[^\"']+)[\"']",
    re.DOTALL,
)
_LOCAL_NAMESPACE_IMPORT_PATTERN = re.compile(
    rf"\bimport{_ACTION_MEMBER_SEPARATOR}\*{_ACTION_MEMBER_SEPARATOR}as"
    rf"{_ACTION_MEMBER_SEPARATOR}[A-Za-z_$][\w$]*{_ACTION_MEMBER_SEPARATOR}from"
    rf"{_ACTION_MEMBER_SEPARATOR}"
    r"[\"'](?P<specifier>\.[^\"']+)[\"']",
    re.DOTALL,
)
_LOCAL_EXPORT_LIST_PATTERN = re.compile(
    rf"\bexport{_ACTION_MEMBER_SEPARATOR}\{{(?P<bindings>[^}}]*)\}}"
    rf"(?!{_ACTION_MEMBER_SEPARATOR}from\b)",
    re.DOTALL,
)
_NAMED_BINDING_PATTERN = re.compile(
    r"\s*(?P<type_only>type\s+)?(?P<imported>[A-Za-z_$][\w$]*)"
    r"(?:\s+as\s+(?P<local>[A-Za-z_$][\w$]*))?\s*\Z",
)
_ROUTE_COMPONENT_ALIAS_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:const|let|var)\s+(?P<alias>[A-Za-z_$][\w$]*)"
    r"(?:\s*:\s*[^=;\n]+)?\s*=\s*"
    rf"(?P<target>(?:\({_ACTION_MEMBER_SEPARATOR})*[A-Za-z_$][\w$]*"
    rf"(?:{_ACTION_MEMBER_SEPARATOR}\.{_ACTION_MEMBER_SEPARATOR}[A-Za-z_$][\w$]*)?"
    rf"(?:{_ACTION_MEMBER_SEPARATOR}\))*)",
)
_RUNTIME_ALIAS_BINDING_PATTERN = re.compile(
    r"\b(?:const|let|var)\s+(?P<alias>[A-Za-z_$][\w$]*)"
    r"(?:\s*:\s*[^=;\n]+)?\s*(?P<equals>=)\s*(?P<target>[^;]+)",
    re.DOTALL,
)
_RUNTIME_ALIAS_MUTATION_PATTERN = re.compile(
    r"(?<![=!<>])(?P<equals>=(?!=|>))",
)
_RUNTIME_ALIAS_RETURN_PATTERN = re.compile(r"\breturn\b")
_RUNTIME_ALIAS_OBJECT_PROPERTY_PATTERN = re.compile(
    r":\s*(?P<target>(?:\(\s*)*[A-Za-z_$][\w$]*"
    r"(?:\s*\.\s*[A-Za-z_$][\w$]*)?(?:\s*\))*)(?=\s*[,}])",
)
_RUNTIME_ALIAS_CALL_ARGUMENT_PATTERN = re.compile(
    r"(?:\(|,)\s*(?:\.\.\.\s*)?(?P<target>[A-Za-z_$][\w$]*"
    r"(?:\s*\.\s*[A-Za-z_$][\w$]*)?)(?=\s*(?:\(|[,\)\]\}]))",
)
_LOCAL_DEFAULT_EXPORT_PATTERN = re.compile(
    rf"\bexport{_ACTION_MEMBER_SEPARATOR}default{_ACTION_MEMBER_SEPARATOR}"
    rf"(?P<target>(?:\({_ACTION_MEMBER_SEPARATOR})*[A-Za-z_$][\w$]*"
    rf"(?:{_ACTION_MEMBER_SEPARATOR}\.{_ACTION_MEMBER_SEPARATOR}[A-Za-z_$][\w$]*)?"
    rf"(?:{_ACTION_MEMBER_SEPARATOR}\))*)",
)
_SOURCE_IDENTIFIER_PATTERN = re.compile(
    r"(?:[A-Za-z_$]|\\u(?:[0-9A-Fa-f]{4}|\{[0-9A-Fa-f]+\}))"
    r"(?:[A-Za-z0-9_$]|\\u(?:[0-9A-Fa-f]{4}|\{[0-9A-Fa-f]+\}))*",
)
_TYPESCRIPT_TYPE_ALIAS_START_PATTERN = re.compile(
    r"\b(?:export\s+)?(?:declare\s+)?type\s+[A-Za-z_$][\w$]*"
    r"(?:\s*<[^;\r\n=]*>)?\s*=",
)
_TYPESCRIPT_TYPE_DECLARATION_START_PATTERN = re.compile(
    r"\b(?:export\s+)?(?:declare\s+)?(?:"
    r"interface\s+[A-Za-z_$][\w$]*(?:\s+extends\s+[^\r\n{}]+)?|"
    r"type\s+[A-Za-z_$][\w$]*(?:\s*<[^{}>]*>)?\s*=)"
    r"[^;\r\n{}]*\{",
)
_TYPESCRIPT_TYPE_IMPORT_START_PATTERN = re.compile(
    rf"\bimport{_ACTION_MEMBER_SEPARATOR}type\b",
)
_TYPESCRIPT_TYPE_QUERY_START_PATTERN = re.compile(
    r"\btypeof\b",
)
_TYPESCRIPT_IMPORT_TYPE_QUERY_START_PATTERN = re.compile(
    rf"\bimport{_ACTION_MEMBER_SEPARATOR}\(",
)
_TYPESCRIPT_VARIABLE_TYPE_ANNOTATION_PREFIX_PATTERN = re.compile(
    r"\b(?:declare\s+)?(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*:\s*$",
)
_TYPESCRIPT_FUNCTION_PARAMETER_TYPE_ANNOTATION_PREFIX_PATTERN = re.compile(
    r"\b(?:declare\s+)?(?:async\s+)?function(?:\s*\*)?"
    r"(?:\s+[A-Za-z_$][\w$]*)?\s*\([^(){};\r\n]*"
    r"\b[A-Za-z_$][\w$]*\??\s*:\s*$",
)
_TYPESCRIPT_ARROW_PARAMETER_TYPE_ANNOTATION_PREFIX_PATTERN = re.compile(
    r"\(\s*[A-Za-z_$][\w$]*\??\s*:\s*$",
)
_TYPESCRIPT_IMPORT_ACTUAL_TYPE_ARGUMENT_PREFIX_PATTERN = re.compile(
    r"\b(?:[A-Za-z_$][\w$]*\s*\.\s*)?importActual\s*<\s*$",
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
            _process_command(command),
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


def _process_command(command: Sequence[object]) -> list[str]:
    """Resolve Windows command shims while preserving the logical command in evidence."""
    argv = [str(item) for item in command]
    if not argv or os.name != "nt":
        return argv
    executable = argv[0]
    if Path(executable).suffix:
        return argv
    resolved = shutil.which(executable)
    if resolved is None:
        return argv
    return [resolved, *argv[1:]]


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


def _pip_audit_exception_failure(error_code: str) -> dict[str, object]:
    return {"status": "failed", "error_code": error_code}


def _read_exception(path: Path) -> Mapping[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


_CRYPTOGRAPHY_EXCEPTION_ID = "cryptography-pkcs7-mlflow-constraint"
_CRYPTOGRAPHY_EXCEPTION_PACKAGES = {
    "cryptography": "49.0.0",
    "mlflow": "3.15.1",
}
_CRYPTOGRAPHY_EXCEPTION_ADVISORIES = {
    "PYSEC-2026-3552",
    "CVE-2026-69247",
}


def _requirements_use_frozen_cryptography_constraint(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    normalized = {
        line.split("#", 1)[0].strip().casefold()
        for line in lines
        if line.split("#", 1)[0].strip()
    }
    return {
        "cryptography==49.0.*",
        "mlflow==3.15.*",
    }.issubset(normalized)


def _application_uses_pkcs7(application_directory: Path) -> bool:
    """Fail closed when runtime source cannot be proven free of PKCS#7 use."""
    if not application_directory.is_dir():
        return True
    try:
        source_paths = sorted(application_directory.rglob("*.py"))
    except OSError:
        return True
    for source_path in source_paths:
        try:
            source = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return True
        if "pkcs7" in source.casefold():
            return True
    return False


def evaluate_pip_audit_exception(
    audit_report: Mapping[str, object],
    *,
    exception_path: Path,
    requirements_path: Path,
    application_directory: Path,
    today: date | None = None,
) -> dict[str, object]:
    """Allow only the reviewed MLflow/cryptography compatibility exception."""
    if not isinstance(audit_report, dict):
        return _pip_audit_exception_failure("PIP_AUDIT_REPORT_INVALID")
    exception = _read_exception(exception_path)
    if exception is None:
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_INVALID")
    try:
        schema_version = exception["schema_version"]
        exception_id = exception["id"]
        owner = exception["owner"]
        reviewed_at = exception["reviewed_at"]
        expires_on = exception["expires_on"]
        package_versions = exception["package_versions"]
        advisory_ids = exception["advisory_ids"]
        mitigation = exception["mitigation"]
    except KeyError:
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_INVALID")
    if (
        schema_version != 1
        or exception_id != _CRYPTOGRAPHY_EXCEPTION_ID
        or not isinstance(owner, str)
        or not owner
        or not isinstance(reviewed_at, str)
        or not isinstance(expires_on, str)
        or package_versions != _CRYPTOGRAPHY_EXCEPTION_PACKAGES
        or not isinstance(advisory_ids, list)
        or not all(isinstance(advisory_id, str) for advisory_id in advisory_ids)
        or set(advisory_ids) != _CRYPTOGRAPHY_EXCEPTION_ADVISORIES
        or len(advisory_ids) != len(_CRYPTOGRAPHY_EXCEPTION_ADVISORIES)
        or not isinstance(mitigation, str)
        or "MLflow 3.15.1" not in mitigation
        or "cryptography<50" not in mitigation
        or "PKCS#7" not in mitigation
    ):
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_INVALID")
    try:
        review_date = date.fromisoformat(reviewed_at)
        expiry_date = date.fromisoformat(expires_on)
    except ValueError:
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_INVALID")
    current_date = today or date.today()
    if review_date > current_date or expiry_date < current_date:
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_EXPIRED")
    if not _requirements_use_frozen_cryptography_constraint(requirements_path):
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_VERSION_MISMATCH")
    if _application_uses_pkcs7(application_directory):
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_SCOPE_VIOLATION")

    dependencies = audit_report.get("dependencies")
    if not isinstance(dependencies, list):
        return _pip_audit_exception_failure("PIP_AUDIT_REPORT_INVALID")
    by_name: dict[str, Mapping[str, object]] = {}
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            return _pip_audit_exception_failure("PIP_AUDIT_REPORT_INVALID")
        name = dependency.get("name")
        version = dependency.get("version")
        vulnerabilities = dependency.get("vulns")
        if (
            not isinstance(name, str)
            or not name
            or name.casefold() in by_name
            or not isinstance(version, str)
            or not isinstance(vulnerabilities, list)
        ):
            return _pip_audit_exception_failure("PIP_AUDIT_REPORT_INVALID")
        by_name[name.casefold()] = dependency
    expected_names = set(_CRYPTOGRAPHY_EXCEPTION_PACKAGES)
    if not expected_names.issubset(by_name):
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_VERSION_MISMATCH")
    if any(
        dependency.get("vulns")
        for name, dependency in by_name.items()
        if name != "cryptography"
    ):
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_ADVISORY_MISMATCH")

    cryptography = by_name["cryptography"]
    mlflow = by_name["mlflow"]
    if (
        cryptography.get("version") != _CRYPTOGRAPHY_EXCEPTION_PACKAGES["cryptography"]
        or mlflow.get("version") != _CRYPTOGRAPHY_EXCEPTION_PACKAGES["mlflow"]
        or mlflow.get("vulns") != []
    ):
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_VERSION_MISMATCH")
    vulnerabilities = cryptography.get("vulns")
    if not isinstance(vulnerabilities, list) or len(vulnerabilities) != 1:
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_ADVISORY_MISMATCH")
    vulnerability = vulnerabilities[0]
    if not isinstance(vulnerability, dict):
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_ADVISORY_MISMATCH")
    aliases = vulnerability.get("aliases")
    fixes = vulnerability.get("fix_versions")
    if (
        vulnerability.get("id") != "PYSEC-2026-3552"
        or not isinstance(aliases, list)
        or "CVE-2026-69247" not in aliases
        or not isinstance(fixes, list)
        or "50.0.0" not in fixes
    ):
        return _pip_audit_exception_failure("PIP_AUDIT_EXCEPTION_ADVISORY_MISMATCH")
    return {
        "status": "passed",
        "exception": {
            "id": exception_id,
            "owner": owner,
            "reviewed_at": reviewed_at,
            "expires_on": expires_on,
        },
    }


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


def _source_without_typescript_type_declarations(
    source: str,
    *,
    is_typescript: bool,
) -> str:
    """Mask TypeScript-only syntax before scanning runtime router APIs."""
    masked = list(source)
    index = 0
    quote: str | None = None
    while index < len(source):
        character = source[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {'"', "'", "`"}:
            quote = character
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            index = len(source) if comment_end < 0 else comment_end + 2
            continue
        if not is_typescript:
            index += 1
            continue
        type_import = _TYPESCRIPT_TYPE_IMPORT_START_PATTERN.match(source, index)
        if type_import is not None:
            end = _typescript_statement_end(source, type_import.start())
            if end is None:
                index = type_import.end()
                continue
            masked[type_import.start() : end + 1] = " " * (
                end + 1 - type_import.start()
            )
            index = end + 1
            continue
        type_query = _TYPESCRIPT_TYPE_QUERY_START_PATTERN.match(source, index)
        if type_query is not None:
            opening_parenthesis = _typescript_type_query_opening_parenthesis(
                source,
                type_query.end(),
            )
            closing_parenthesis = (
                _matching_parenthesis(source, opening_parenthesis)
                if opening_parenthesis is not None
                else None
            )
            if (
                closing_parenthesis is not None
                and _is_definite_typescript_type_position(
                    source,
                    type_query.start(),
                    closing_parenthesis,
                )
            ):
                masked[type_query.start() : closing_parenthesis + 1] = " " * (
                    closing_parenthesis + 1 - type_query.start()
                )
                index = closing_parenthesis + 1
                continue
        import_type_query = _TYPESCRIPT_IMPORT_TYPE_QUERY_START_PATTERN.match(
            source,
            index,
        )
        if (
            import_type_query is not None
        ):
            opening_parenthesis = source.find(
                "(",
                import_type_query.start(),
                import_type_query.end(),
            )
            closing_parenthesis = (
                _matching_parenthesis(source, opening_parenthesis)
                if opening_parenthesis >= 0
                else None
            )
            if (
                closing_parenthesis is not None
                and _is_definite_typescript_import_type_query(
                    source,
                    import_type_query.start(),
                    closing_parenthesis,
                )
            ):
                masked[
                    import_type_query.start() : closing_parenthesis + 1
                ] = " " * (closing_parenthesis + 1 - import_type_query.start())
                index = closing_parenthesis + 1
                continue
        type_alias = _TYPESCRIPT_TYPE_ALIAS_START_PATTERN.match(source, index)
        if type_alias is not None:
            end = _typescript_type_alias_end(source, type_alias.end())
            if end is None:
                index = type_alias.end()
                continue
            masked[type_alias.start() : end + 1] = " " * (
                end + 1 - type_alias.start()
            )
            index = end + 1
            continue
        match = _TYPESCRIPT_TYPE_DECLARATION_START_PATTERN.match(source, index)
        if match is None:
            index += 1
            continue
        opening_brace = source.find("{", match.start(), match.end())
        closing_brace = _matching_brace(source, opening_brace)
        if closing_brace is None:
            index = match.end()
            continue
        masked[match.start() : closing_brace + 1] = " " * (
            closing_brace + 1 - match.start()
        )
        index = closing_brace + 1
    return "".join(masked)


def _typescript_type_query_opening_parenthesis(source: str, index: int) -> int | None:
    """Return the import-call opening parenthesis for a `typeof import` query."""
    import_start = _skip_source_space_and_comments(source, index, len(source))
    if import_start is None or not source.startswith("import", import_start):
        return None
    import_end = import_start + len("import")
    if (
        import_end < len(source)
        and (source[import_end].isalnum() or source[import_end] in "_$")
    ):
        return None
    opening_parenthesis = _skip_source_space_and_comments(
        source,
        import_end,
        len(source),
    )
    if opening_parenthesis is None or opening_parenthesis >= len(source):
        return None
    return opening_parenthesis if source[opening_parenthesis] == "(" else None


def _is_definite_typescript_type_position(
    source: str,
    index: int,
    closing_parenthesis: int,
) -> bool:
    """Return whether a query begins in one supported TypeScript type position."""
    prefix = _source_without_comments_and_strings(source[:index])
    if _TYPESCRIPT_VARIABLE_TYPE_ANNOTATION_PREFIX_PATTERN.search(prefix):
        return True
    if _TYPESCRIPT_FUNCTION_PARAMETER_TYPE_ANNOTATION_PREFIX_PATTERN.search(prefix):
        return True
    if _is_definite_typescript_arrow_parameter_type_position(
        source,
        prefix,
        index,
        closing_parenthesis,
    ):
        return True
    if not _TYPESCRIPT_IMPORT_ACTUAL_TYPE_ARGUMENT_PREFIX_PATTERN.search(prefix):
        return False
    generic_closing = _skip_source_space_and_comments(
        source,
        closing_parenthesis + 1,
        len(source),
    )
    if generic_closing is None or generic_closing >= len(source):
        return False
    if source[generic_closing] != ">":
        return False
    call_start = _skip_source_space_and_comments(
        source,
        generic_closing + 1,
        len(source),
    )
    return call_start is not None and call_start < len(source) and source[call_start] == "("


def _is_definite_typescript_arrow_parameter_type_position(
    source: str,
    prefix: str,
    index: int,
    closing_parenthesis: int,
) -> bool:
    """Recognize a single typed arrow parameter only when its `=>` is present."""
    if not _TYPESCRIPT_ARROW_PARAMETER_TYPE_ANNOTATION_PREFIX_PATTERN.search(prefix):
        return False
    query_end = closing_parenthesis + 1
    if source.startswith("import", index):
        member_separator = _skip_source_space_and_comments(
            source,
            query_end,
            len(source),
        )
        if member_separator is None or member_separator >= len(source):
            return False
        if source[member_separator] != ".":
            return False
        member_start = _skip_source_space_and_comments(
            source,
            member_separator + 1,
            len(source),
        )
        if member_start is None:
            return False
        member = _SOURCE_IDENTIFIER_PATTERN.match(source, member_start)
        if member is None:
            return False
        query_end = member.end()
    parameter_closing = _skip_source_space_and_comments(
        source,
        query_end,
        len(source),
    )
    if parameter_closing is None or parameter_closing >= len(source):
        return False
    if source[parameter_closing] != ")":
        return False
    arrow_start = _skip_source_space_and_comments(
        source,
        parameter_closing + 1,
        len(source),
    )
    return arrow_start is not None and source.startswith("=>", arrow_start)


def _is_definite_typescript_import_type_query(
    source: str,
    import_start: int,
    closing_parenthesis: int,
) -> bool:
    """Recognize only member import type queries in a supported type position."""
    if not _is_definite_typescript_type_position(
        source,
        import_start,
        closing_parenthesis,
    ):
        return False
    member_separator = _skip_source_space_and_comments(
        source,
        closing_parenthesis + 1,
        len(source),
    )
    if member_separator is None or member_separator >= len(source):
        return False
    if source[member_separator] != ".":
        return False
    member_start = _skip_source_space_and_comments(
        source,
        member_separator + 1,
        len(source),
    )
    return (
        member_start is not None
        and _SOURCE_IDENTIFIER_PATTERN.match(source, member_start) is not None
    )


def _typescript_statement_end(source: str, index: int) -> int | None:
    """Find a top-level TypeScript import statement boundary."""
    depths = {"{": 0, "(": 0, "[": 0}
    quote: str | None = None
    cursor = index
    while cursor < len(source):
        character = source[cursor]
        if quote is not None:
            if character == "\\":
                cursor += 2
                continue
            if character == quote:
                quote = None
            cursor += 1
            continue
        if character in {'"', "'", chr(96)}:
            quote = character
            cursor += 1
            continue
        if source.startswith("//", cursor):
            newline = source.find("\n", cursor + 2)
            if newline < 0:
                return len(source) - 1
            cursor = newline + 1
            continue
        if source.startswith("/*", cursor):
            comment_end = source.find("*/", cursor + 2)
            if comment_end < 0:
                return None
            cursor = comment_end + 2
            continue
        if character in depths:
            depths[character] += 1
        elif character in {"}", ")", "]"}:
            opening = {"}": "{", ")": "(", "]": "["}[character]
            if depths[opening] == 0:
                return None
            depths[opening] -= 1
        elif not any(depths.values()):
            if character == ";":
                return cursor
            if character == "\n":
                previous = source[cursor - 1] if cursor else ""
                if previous not in "=?:|&,+-*/":
                    return cursor - 1
        cursor += 1
    return len(source) - 1 if not any(depths.values()) else None


def _typescript_type_alias_end(source: str, index: int) -> int | None:
    """Find the end of a TypeScript type alias without parsing runtime code."""
    depths = {"{": 0, "(": 0, "[": 0}
    quote: str | None = None
    while index < len(source):
        character = source[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {'"', "'", chr(96)}:
            quote = character
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            if comment_end < 0:
                return None
            index = comment_end + 2
            continue
        if character in depths:
            depths[character] += 1
        elif character in {"}", ")", "]"}:
            opening = {"}": "{", ")": "(", "]": "["}[character]
            depths[opening] -= 1
            if depths[opening] < 0:
                return None
        elif character == ";" and not any(depths.values()):
            return index
        elif character == "\n" and not any(depths.values()):
            previous = source[index - 1] if index else ""
            next_index = index + 1
            while next_index < len(source) and source[next_index].isspace():
                next_index += 1
            following = source[next_index] if next_index < len(source) else ""
            if previous not in "|&=," and following not in "|&":
                return index - 1
        index += 1
    return len(source) - 1 if not any(depths.values()) else None


def _skip_source_space_and_comments(
    source: str,
    index: int,
    end: int,
) -> int | None:
    while index < end:
        if source[index].isspace():
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = end if newline < 0 or newline >= end else newline + 1
            continue
        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            if comment_end < 0 or comment_end >= end:
                return None
            index = comment_end + 2
            continue
        break
    return index


def _matching_brace(source: str, opening_brace: int) -> int | None:
    """Find an object-literal boundary without counting braces inside strings/comments."""
    depth = 0
    index = opening_brace
    quote: str | None = None
    while index < len(source):
        character = source[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {'"', "'", "`"}:
            quote = character
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            if comment_end < 0:
                return None
            index = comment_end + 2
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _matching_parenthesis(source: str, opening_parenthesis: int) -> int | None:
    depth = 0
    index = opening_parenthesis
    quote: str | None = None
    while index < len(source):
        character = source[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {'"', "'", chr(96)}:
            quote = character
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            if comment_end < 0:
                return None
            index = comment_end + 2
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
            if depth < 0:
                return None
        index += 1
    return None


def _matching_bracket(source: str, opening_bracket: int) -> int | None:
    depth = 0
    index = opening_bracket
    quote: str | None = None
    while index < len(source):
        character = source[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {'"', "'", "`"}:
            quote = character
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            if comment_end < 0:
                return None
            index = comment_end + 2
            continue
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _top_level_array_elements(
    source: str,
    opening_bracket: int,
    closing_bracket: int,
) -> list[tuple[int, int]] | None:
    elements: list[tuple[int, int]] = []
    depth = 0
    element_start = opening_bracket + 1
    index = element_start
    quote: str | None = None
    while index < closing_bracket:
        character = source[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {'"', "'", "`"}:
            quote = character
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = closing_bracket if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            if comment_end < 0:
                return None
            index = comment_end + 2
            continue
        if character in "{[(":
            depth += 1
        elif character in "}])":
            depth -= 1
            if depth < 0:
                return None
        elif character == "," and depth == 0:
            elements.append((element_start, index))
            element_start = index + 1
        index += 1
    if quote is not None or depth != 0:
        return None
    elements.append((element_start, closing_bracket))
    return elements


def _object_has_top_level_action_shorthand(
    source: str,
    opening_brace: int,
    closing_brace: int,
) -> bool:
    """Recognize a top-level route `action` property regardless of its value syntax."""
    depth = 0
    member_start = opening_brace + 1
    index = member_start
    quote: str | None = None
    while index < closing_brace:
        character = source[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if depth == 0:
            member_key_start = _skip_source_space_and_comments(
                source,
                member_start,
                index,
            )
            if member_key_start is None:
                return True
            if (
                member_key_start == index
                and (
                    source.startswith("...", index)
                    or source[index] in {"'", '"', "`", "["}
                )
            ):
                return True
            if member_key_start == index:
                identifier_match = _SOURCE_IDENTIFIER_PATTERN.match(source, index)
                if (
                    source[index] == "\\"
                    or (
                        identifier_match is not None
                        and "\\" in identifier_match.group(0)
                    )
                ):
                    return True
        if character in {'"', "'", "`"}:
            quote = character
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = closing_brace if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            if comment_end < 0:
                return True
            index = comment_end + 2
            continue
        if character in "{[(":
            depth += 1
        elif character in "}])":
            depth -= 1
        elif character == "," and depth == 0:
            member_start = index + 1
        elif depth == 0:
            action_start = index
            if member_key_start == index:
                modifier_match = re.match(
                    r"(?:async|get|set)\b",
                    source[index:closing_brace],
                )
                if modifier_match is not None:
                    action_start = _skip_source_space_and_comments(
                        source,
                        index + modifier_match.end(),
                        closing_brace,
                    )
                    if (
                        action_start is None
                        or action_start == closing_brace
                        or source[action_start] in {"\\", "'", '"', "`", "["}
                    ):
                        return True
                if source[action_start] == "*":
                    action_start = _skip_source_space_and_comments(
                        source,
                        action_start + 1,
                        closing_brace,
                    )
                    if action_start is None or action_start == closing_brace:
                        return True
            if (
                member_key_start == index
                and source.startswith("action", action_start)
                and (action_start == member_start or not (source[action_start - 1].isalnum() or source[action_start - 1] in "_$"))
                and (action_start + 6 == closing_brace or not (source[action_start + 6].isalnum() or source[action_start + 6] in "_$"))
            ):
                suffix = _skip_source_space_and_comments(
                    source,
                    action_start + 6,
                    closing_brace,
                )
                if suffix is None:
                    return True
                if suffix == closing_brace or source[suffix] in {",", ":", "(", "<"}:
                    return True
            if (
                member_key_start == index
                and source.startswith("children", index)
                and (index + 8 == closing_brace or not (source[index + 8].isalnum() or source[index + 8] in "_$"))
            ):
                separator = _skip_source_space_and_comments(
                    source,
                    index + 8,
                    closing_brace,
                )
                if separator is None or separator == closing_brace or source[separator] != ":":
                    return True
                child_start = _skip_source_space_and_comments(
                    source,
                    separator + 1,
                    closing_brace,
                )
                if child_start is None or child_start == closing_brace or source[child_start] != "[":
                    return True
                child_end = _matching_bracket(source, child_start)
                if child_end is None or child_end >= closing_brace:
                    return True
                if _route_array_uses_action(source, child_start, child_end):
                    return True
                index = child_end
        index += 1
    return False


def _source_uses_extracted_route_action_shorthand(source: str) -> bool:
    for match in _ROUTE_ACTION_EXTRACTED_DECLARATION_PATTERN.finditer(source):
        opening_brace = match.end() - 1
        closing_brace = _matching_brace(source, opening_brace)
        if closing_brace is None:
            return True
        if not _object_has_top_level_action_shorthand(
            source,
            opening_brace,
            closing_brace,
        ):
            continue
        route = match.group("route")
        route_reference = re.compile(
            r"\b(?:routes?|routeConfig)(?:\s*:\s*[^=;\n]+)?\s*=\s*\[[^\]]*\b"
            + re.escape(route)
            + r"\b",
            re.IGNORECASE | re.DOTALL,
        )
        if route_reference.search(source, closing_brace + 1):
            return True
    return False


def _declared_route_object(
    source: str,
    route_name: str,
) -> tuple[int, int] | None:
    for match in _ROUTE_ACTION_EXTRACTED_DECLARATION_PATTERN.finditer(source):
        if match.group("route") != route_name:
            continue
        opening_brace = match.end() - 1
        closing_brace = _matching_brace(source, opening_brace)
        if closing_brace is None:
            return (-1, -1)
        return opening_brace, closing_brace
    return None


def _route_array_uses_action(
    source: str,
    opening_bracket: int,
    closing_bracket: int,
) -> bool:
    elements = _top_level_array_elements(source, opening_bracket, closing_bracket)
    if elements is None:
        return True
    for element_start, element_end in elements:
        start = _skip_source_space_and_comments(source, element_start, element_end)
        if start is None:
            return True
        if start == element_end:
            continue
        if source[start] == "{":
            closing_brace = _matching_brace(source, start)
            if closing_brace is None or closing_brace >= element_end:
                return True
            if _object_has_top_level_action_shorthand(source, start, closing_brace):
                return True
            continue
        route_match = re.match(r"[A-Za-z_$][\w$]*", source[start:element_end])
        if route_match is None:
            return True
        declaration = _declared_route_object(source, route_match.group(0))
        if declaration is None:
            return True
        opening_brace, closing_brace = declaration
        if opening_brace < 0 or _object_has_top_level_action_shorthand(
            source,
            opening_brace,
            closing_brace,
        ):
            return True
    return False


def _source_uses_route_object_action(
    source: str,
    *,
    router_factory_aliases: frozenset[str] = frozenset(),
) -> bool:
    for match in _ROUTE_ROOT_ASSIGNMENT_PATTERN.finditer(source):
        opening_bracket = _skip_source_space_and_comments(
            source,
            match.end(),
            len(source),
        )
        while opening_bracket is not None and opening_bracket < len(source) and source[opening_bracket] == "(":
            opening_bracket = _skip_source_space_and_comments(
                source,
                opening_bracket + 1,
                len(source),
            )
        if opening_bracket is None or opening_bracket == len(source) or source[opening_bracket] != "[":
            return True
        closing_bracket = _matching_bracket(source, opening_bracket)
        if closing_bracket is None or _route_array_uses_action(
            source,
            opening_bracket,
            closing_bracket,
        ):
            return True
    factory_names = _REACT_ROUTER_FACTORY_NAMES | set(router_factory_aliases)
    factory_pattern = re.compile(
        r"\b(?:"
        + "|".join(re.escape(name) for name in sorted(factory_names))
        + rf")(?:{_ACTION_MEMBER_SEPARATOR}\))*"
        + rf"(?:{_ACTION_MEMBER_SEPARATOR}<[^{{}}>]*>)?"
        + rf"{_ACTION_MEMBER_SEPARATOR}(?:\?\.)?{_ACTION_MEMBER_SEPARATOR}\(",
        re.IGNORECASE,
    )
    for match in factory_pattern.finditer(source):
        opening_bracket = _skip_source_space_and_comments(
            source,
            match.end(),
            len(source),
        )
        if opening_bracket is None or opening_bracket == len(source) or source[opening_bracket] != "[":
            return True
        closing_bracket = _matching_bracket(source, opening_bracket)
        if closing_bracket is None or _route_array_uses_action(
            source,
            opening_bracket,
            closing_bracket,
        ):
            return True
    return False


def _parse_named_bindings(bindings: str) -> list[tuple[str, str]] | None:
    cleaned: list[str] = []
    index = 0
    while index < len(bindings):
        if bindings.startswith("//", index):
            newline = bindings.find("\n", index + 2)
            index = len(bindings) if newline < 0 else newline
            cleaned.append(" ")
            continue
        if bindings.startswith("/*", index):
            comment_end = bindings.find("*/", index + 2)
            if comment_end < 0:
                return None
            cleaned.append(" ")
            index = comment_end + 2
            continue
        cleaned.append(bindings[index])
        index += 1

    values = []
    parts = "".join(cleaned).split(",")
    for index, value in enumerate(parts):
        if not value.strip():
            if index == len(parts) - 1:
                continue
            return None
        match = _NAMED_BINDING_PATTERN.fullmatch(value)
        if match is None:
            return None
        if match.group("type_only") is not None:
            continue
        imported = match.group("imported")
        values.append((imported, match.group("local") or imported))
    return values


def _bindings_are_type_only(bindings: str) -> bool:
    """Return true only when every export-list binding is explicitly type-only."""
    cleaned: list[str] = []
    index = 0
    while index < len(bindings):
        if bindings.startswith("//", index):
            newline = bindings.find("\n", index + 2)
            index = len(bindings) if newline < 0 else newline
            cleaned.append(" ")
            continue
        if bindings.startswith("/*", index):
            comment_end = bindings.find("*/", index + 2)
            if comment_end < 0:
                return False
            cleaned.append(" ")
            index = comment_end + 2
            continue
        cleaned.append(bindings[index])
        index += 1

    parts = "".join(cleaned).split(",")
    if not parts or all(not part.strip() for part in parts):
        return False
    for part in parts:
        if not part.strip():
            return False
        match = _NAMED_BINDING_PATTERN.fullmatch(part)
        if match is None or match.group("type_only") is None:
            return False
    return True


def _route_alias_target_matches(target: str, aliases: set[str]) -> bool:
    """Conservatively propagate direct, parenthesized, and bound aliases."""
    normalized = re.sub(r"/\*[\s\S]*?\*/|//[^\r\n]*(?:\r?\n|$)", "", target)
    normalized = re.sub(r"\s+", "", normalized).lstrip("(").rstrip(")")
    candidates = {normalized}
    if normalized.endswith(".bind"):
        candidates.add(normalized.removesuffix(".bind"))
    return any(
        candidate in aliases or candidate.rsplit(".", 1)[-1] in aliases
        for candidate in candidates
    )


def _react_router_named_import_aliases(
    source: str,
    imported_names: frozenset[str],
) -> tuple[frozenset[str], bool]:
    aliases: set[str] = set()
    for match in _REACT_ROUTER_NAMED_IMPORT_PATTERN.finditer(source):
        bindings = _parse_named_bindings(match.group("bindings"))
        if bindings is None:
            return frozenset(), True
        aliases.update(
            local
            for imported, local in bindings
            if imported in imported_names
        )
    return frozenset(aliases), False


def _expanded_react_router_runtime_aliases(
    source: str,
    imported_names: frozenset[str],
) -> tuple[frozenset[str], bool]:
    aliases, invalid_import = _react_router_named_import_aliases(source, imported_names)
    if invalid_import:
        return frozenset(), True
    expanded_aliases = set(aliases)
    while True:
        before = len(expanded_aliases)
        for match in _ROUTE_COMPONENT_ALIAS_ASSIGNMENT_PATTERN.finditer(source):
            if _route_alias_target_matches(match.group("target"), expanded_aliases):
                expanded_aliases.add(match.group("alias"))
        if len(expanded_aliases) == before:
            break
    return frozenset(expanded_aliases), False


def _react_router_route_reexports(source: str) -> frozenset[str]:
    aliases = set()
    for match in _REACT_ROUTER_ROUTE_REEXPORT_PATTERN.finditer(source):
        bindings = _parse_named_bindings(match.group("bindings"))
        if bindings is None:
            continue
        for imported, exported in bindings:
            if imported == "Route":
                aliases.add(exported)
    return frozenset(aliases)


def _all_react_router_route_reexports(
    sources: Mapping[Path, str],
) -> dict[Path, frozenset[str]]:
    """Resolve local named and star barrels to a fixed point for Route aliases."""
    reexports = {
        path: set(_react_router_route_reexports(source))
        for path, source in sources.items()
    }
    while True:
        changed = False
        for path, source in sources.items():
            aliases = reexports[path]
            for match in _LOCAL_NAMED_REEXPORT_PATTERN.finditer(source):
                target = _resolve_local_frontend_source(
                    path,
                    match.group("specifier"),
                    sources,
                )
                if target is None:
                    continue
                bindings = _parse_named_bindings(match.group("bindings"))
                if bindings is None:
                    continue
                for imported, exported in bindings:
                    if imported in reexports[target] and exported not in aliases:
                        aliases.add(exported)
                        changed = True
            for match in _LOCAL_STAR_REEXPORT_PATTERN.finditer(source):
                target = _resolve_local_frontend_source(
                    path,
                    match.group("specifier"),
                    sources,
                )
                if target is None:
                    continue
                for exported in reexports[target]:
                    if exported not in aliases:
                        aliases.add(exported)
                        changed = True
        if not changed:
            break
    return {path: frozenset(aliases) for path, aliases in reexports.items()}


def _has_unsafe_local_frontend_bindings(
    sources: Mapping[Path, str],
) -> bool:
    """Reject local binding forms the conservative scanner cannot prove safe."""
    for path, source in sources.items():
        for match in _LOCAL_EXPORT_LIST_PATTERN.finditer(source):
            if not _bindings_are_type_only(match.group("bindings")):
                return True
        for pattern in (_LOCAL_NAMED_IMPORT_PATTERN, _LOCAL_NAMED_REEXPORT_PATTERN):
            for match in pattern.finditer(source):
                if _parse_named_bindings(match.group("bindings")) is None:
                    return True
                if _resolve_local_frontend_source(
                    path,
                    match.group("specifier"),
                    sources,
                ) is None:
                    return True
        for match in _LOCAL_STAR_REEXPORT_PATTERN.finditer(source):
            if _resolve_local_frontend_source(
                path,
                match.group("specifier"),
                sources,
            ) is None:
                return True
        if _LOCAL_NAMESPACE_IMPORT_PATTERN.search(source):
            return True
    return False


def _resolve_local_frontend_source(
    source_path: Path,
    specifier: str,
    sources: Mapping[Path, str],
) -> Path | None:
    base_path = source_path.parent / specifier
    candidates = []
    if base_path.suffix:
        candidates.append(base_path)
    else:
        candidates.extend(
            base_path.with_suffix(suffix)
            for suffix in sorted(_FRONTEND_SOURCE_SUFFIXES)
        )
        candidates.extend(
            base_path / f"index{suffix}"
            for suffix in sorted(_FRONTEND_SOURCE_SUFFIXES)
        )
    resolved_candidates: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved in sources:
            resolved_candidates.add(resolved)
    if len(resolved_candidates) != 1:
        return None
    return next(iter(resolved_candidates))


def _imported_react_router_route_aliases(
    source_path: Path,
    source: str,
    sources: Mapping[Path, str],
    reexports: Mapping[Path, frozenset[str]],
) -> frozenset[str]:
    aliases = set()
    for match in _LOCAL_NAMED_IMPORT_PATTERN.finditer(source):
        target = _resolve_local_frontend_source(
            source_path,
            match.group("specifier"),
            sources,
        )
        if target is None:
            continue
        exported_aliases = reexports.get(target, frozenset())
        bindings = _parse_named_bindings(match.group("bindings"))
        if bindings is None:
            continue
        for imported, local in bindings:
            if imported in exported_aliases:
                aliases.add(local)
    return frozenset(aliases)


def _source_uses_jsx_route_action(
    source: str,
    *,
    imported_route_components: frozenset[str] = frozenset(),
) -> bool:
    """Reject JSX Route action props and unresolved JSX attribute spreads."""
    route_components = {"Route"}
    route_components.update(imported_route_components)
    direct_route_aliases, invalid_import = _react_router_named_import_aliases(
        source,
        frozenset({"Route"}),
    )
    if invalid_import:
        return True
    route_components.update(direct_route_aliases)
    while True:
        before = len(route_components)
        for match in _ROUTE_COMPONENT_ALIAS_ASSIGNMENT_PATTERN.finditer(source):
            if _route_alias_target_matches(match.group("target"), route_components):
                route_components.add(match.group("alias"))
        if len(route_components) == before:
            break
    for match in _JSX_ELEMENT_START_PATTERN.finditer(source):
        tag = re.sub(r"\s+", "", match.group("tag"))
        component_name = tag.rsplit(".", 1)[-1]
        if (
            tag not in route_components
            and component_name not in route_components
            and not component_name.endswith("Route")
        ):
            continue
        index = match.end()
        braces = 0
        quote: str | None = None
        attribute_boundary = True
        while index < len(source):
            character = source[index]
            if quote is not None:
                if character == "\\":
                    index += 2
                    continue
                if character == quote:
                    quote = None
                index += 1
                continue
            if character.isspace():
                if braces == 0:
                    attribute_boundary = True
                index += 1
                continue
            if character in {'"', "'", "`"}:
                quote = character
                index += 1
                continue
            if source.startswith("//", index):
                newline = source.find("\n", index + 2)
                if braces == 0:
                    attribute_boundary = True
                index = len(source) if newline < 0 else newline + 1
                continue
            if source.startswith("/*", index):
                comment_end = source.find("*/", index + 2)
                if comment_end < 0:
                    return True
                if braces == 0:
                    attribute_boundary = True
                index = comment_end + 2
                continue
            if character == "{":
                if braces == 0 and source.startswith("{...", index):
                    return True
                braces += 1
                index += 1
                continue
            if character == "}":
                if braces == 0:
                    return True
                braces -= 1
                index += 1
                continue
            if character == ">" and braces == 0:
                break
            if (
                braces == 0
                and attribute_boundary
                and source.startswith("action", index)
                and (index + 6 == len(source) or not (source[index + 6].isalnum() or source[index + 6] in "_$"))
            ):
                separator = _skip_source_space_and_comments(source, index + 6, len(source))
                if separator is None or separator == len(source) or source[separator] != "=":
                    return True
                return True
            if braces == 0:
                attribute_boundary = False
            index += 1
        else:
            return True
    return False


def _expanded_react_router_factory_aliases(
    source: str,
) -> tuple[frozenset[str], bool]:
    return _expanded_react_router_runtime_aliases(
        source,
        _REACT_ROUTER_FACTORY_NAMES,
    )


def _runtime_alias_identifiers(source: str) -> set[str]:
    return {
        identifier.group(0)
        for identifier in _SOURCE_IDENTIFIER_PATTERN.finditer(source)
    }


def _normalized_runtime_binding_target(target: str) -> str:
    normalized = re.sub(
        r"/\*[\s\S]*?\*/|//[^\r\n]*(?:\r?\n|$)|\s+",
        "",
        target,
    )
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1]
    return normalized


def _source_without_comments_and_strings(source: str) -> str:
    """Mask comments and literals while preserving code offsets and punctuation."""
    masked = list(source)
    index = 0
    while index < len(source):
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            end = len(source) if end < 0 else end
            masked[index:end] = " " * (end - index)
            index = end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = len(source) if end < 0 else end + 2
            masked[index:end] = " " * (end - index)
            index = end
            continue
        if source[index] not in {'"', "'", chr(96)}:
            index += 1
            continue
        quote = source[index]
        end = index + 1
        interpolation = False
        while end < len(source):
            if source[end] == "\\":
                end += 2
                continue
            if quote == chr(96) and source.startswith("${", end):
                interpolation = True
            if source[end] == quote:
                end += 1
                break
            end += 1
        if not interpolation:
            masked[index:end] = " " * (end - index)
        index = end
    return "".join(masked)


def _previous_code_index(source: str, index: int) -> int | None:
    cursor = index - 1
    while cursor >= 0 and source[cursor].isspace():
        cursor -= 1
    return cursor if cursor >= 0 else None


def _next_code_index(source: str, index: int) -> int | None:
    cursor = index
    while cursor < len(source) and source[cursor].isspace():
        cursor += 1
    return cursor if cursor < len(source) else None


def _type_only_export_ranges(source: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for pattern in (_LOCAL_EXPORT_LIST_PATTERN, _REACT_ROUTER_ROUTE_REEXPORT_PATTERN):
        for match in pattern.finditer(source):
            if _bindings_are_type_only(match.group("bindings")):
                ranges.append((match.start(), match.end()))
    return ranges


def _runtime_alias_token_is_modeled(
    source: str,
    start: int,
    end: int,
    alias: str,
    *,
    factory_aliases: frozenset[str],
    modeled_ranges: list[tuple[int, int]],
    type_only_export_ranges: list[tuple[int, int]],
) -> bool:
    if any(range_start <= start and end <= range_end for range_start, range_end in modeled_ranges):
        return True
    if any(range_start <= start and end <= range_end for range_start, range_end in type_only_export_ranges):
        return True

    previous = _previous_code_index(source, start)
    following = _next_code_index(source, end)
    if previous is not None and source[previous] == "<":
        return True
    if (
        previous is not None
        and source[previous] == "/"
        and previous > 0
        and source[previous - 1] == "<"
    ):
        return True
    if (
        following is not None
        and source[following] == ":"
        and previous is not None
        and source[previous] in "{,"
    ):
        return True
    if alias in factory_aliases and following is not None:
        call_index = following
        if source.startswith("?.", call_index):
            call_index = _next_code_index(source, call_index + 2)
        if call_index is not None and source[call_index] == "(":
            return previous is None or source[previous] in "=(:,;[{"
    return False


def _source_uses_unmodeled_runtime_alias_expression(
    source: str,
    *,
    runtime_aliases: set[str],
    factory_aliases: frozenset[str],
    modeled_ranges: list[tuple[int, int]],
) -> bool:
    """Reject runtime aliases nested in expressions outside the modeled subset."""
    if not runtime_aliases:
        return False
    masked = _source_without_comments_and_strings(source)
    type_only_export_ranges = _type_only_export_ranges(source)
    for match in _SOURCE_IDENTIFIER_PATTERN.finditer(masked):
        alias = match.group(0)
        if alias not in runtime_aliases:
            continue
        if not _runtime_alias_token_is_modeled(
            source,
            match.start(),
            match.end(),
            alias,
            factory_aliases=factory_aliases,
            modeled_ranges=modeled_ranges,
            type_only_export_ranges=type_only_export_ranges,
        ):
            return True
    return False


def _assignment_value(source: str, index: int) -> str:
    """Return one assignment expression without spilling into later JSX/code."""
    start = index
    depths = {"{": 0, "(": 0, "[": 0}
    quote: str | None = None
    while index < len(source):
        character = source[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {'"', "'", chr(96)}:
            quote = character
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            if newline < 0:
                return source[start:]
            index = newline + 1
            continue
        if source.startswith("/*", index):
            comment_end = source.find("*/", index + 2)
            if comment_end < 0:
                return source[start:]
            index = comment_end + 2
            continue
        if character in depths:
            depths[character] += 1
        elif character in {"}", ")", "]"}:
            opening = {"}": "{", ")": "(", "]": "["}[character]
            if depths[opening] == 0:
                return source[start:index]
            depths[opening] -= 1
        elif not any(depths.values()):
            if character in ";,>":
                return source[start:index]
            if character in "\r\n":
                previous = source[index - 1] if index else ""
                if previous not in "=?:|&,+-*/":
                    return source[start:index]
        index += 1
    return source[start:]


def _is_explicit_runtime_binding(
    target: str,
    runtime_aliases: set[str],
    factory_aliases: frozenset[str],
) -> bool:
    normalized = _normalized_runtime_binding_target(target)
    if normalized in runtime_aliases:
        return True
    return any(
        re.fullmatch(
            rf"{re.escape(factory_alias)}(?:<[^<>]*>)?\([\s\S]*\)",
            normalized,
        )
        is not None
        for factory_alias in factory_aliases
    )


def _read_static_module_literal(
    expression: str,
    index: int,
) -> tuple[str, int] | None:
    if index >= len(expression) or expression[index] not in {'"', "'", chr(96)}:
        return None
    quote = expression[index]
    index += 1
    value: list[str] = []
    while index < len(expression):
        character = expression[index]
        if character == "\\" or (quote != chr(96) and character in "\r\n"):
            return None
        if quote == chr(96) and expression.startswith(chr(36) + "{", index):
            return None
        if character == quote:
            return "".join(value), index + 1
        value.append(character)
        index += 1
    return None


def _static_module_specifier(expression: str) -> str | None:
    index = _skip_source_space_and_comments(expression, 0, len(expression))
    if index is None:
        return None
    parts: list[str] = []
    while index < len(expression):
        literal = _read_static_module_literal(expression, index)
        if literal is None:
            return None
        value, index = literal
        parts.append(value)
        index = _skip_source_space_and_comments(expression, index, len(expression))
        if index is None:
            return None
        if index == len(expression):
            return "".join(parts)
        if expression[index] != "+":
            return None
        index = _skip_source_space_and_comments(expression, index + 1, len(expression))
        if index is None:
            return None
    return "".join(parts)


def _is_react_router_module_specifier(specifier: str) -> bool:
    return specifier in {"react-router", "react-router-dom"} or specifier.startswith(
        ("react-router/", "react-router-dom/"),
    )


def _source_uses_unsafe_module_load(
    source: str,
    *,
    type_query_import_starts: set[int],
) -> bool:
    for match in _RUNTIME_MODULE_LOAD_PATTERN.finditer(source):
        if (
            match.group("loader") == "import"
            and match.start("loader") in type_query_import_starts
        ):
            continue
        opening = match.start("opening")
        closing = _matching_parenthesis(source, opening)
        if closing is None:
            return True
        specifier = _static_module_specifier(source[opening + 1 : closing])
        if specifier is None or _is_react_router_module_specifier(specifier):
            return True
    return False


def _source_uses_unmodeled_react_router_runtime_binding(
    source: str,
) -> bool:
    """Fail closed when an import binding is outside the conservative analyzer."""
    # The TypeScript preprocessor masks every complete `typeof import(...)` query.
    # Avoid rescanning its high-backtracking generic pattern here; incomplete
    # queries and JavaScript runtime imports remain visible and fail closed below.
    type_query_import_starts: set[int] = set()
    if (
        _REACT_ROUTER_NAMESPACE_IMPORT_PATTERN.search(source)
        or _REACT_ROUTER_DEFAULT_IMPORT_PATTERN.search(source)
        or _REACT_ROUTER_MIXED_IMPORT_PATTERN.search(source)
        or _source_uses_unsafe_module_load(
            source,
            type_query_import_starts=type_query_import_starts,
        )
        or _REACT_ROUTER_NAMESPACE_REEXPORT_PATTERN.search(source)
    ):
        return True

    for match in _REACT_ROUTER_ROUTE_REEXPORT_PATTERN.finditer(source):
        bindings = _parse_named_bindings(match.group("bindings"))
        if bindings is None:
            return True
        if any(
            imported in _REACT_ROUTER_FACTORY_NAMES
            or (imported == "Route" and exported == "default")
            for imported, exported in bindings
        ):
            return True

    route_aliases, invalid_route_import = _expanded_react_router_runtime_aliases(
        source,
        frozenset({"Route"}),
    )
    factory_aliases, invalid_factory_import = _expanded_react_router_factory_aliases(source)
    if invalid_route_import or invalid_factory_import:
        return True
    runtime_aliases = set(route_aliases) | set(factory_aliases)
    if not runtime_aliases:
        return False

    modeled_assignment_offsets = set()
    modeled_alias_ranges = []
    react_router_import_ranges = [
        (match.start(), match.end())
        for match in _REACT_ROUTER_NAMED_IMPORT_PATTERN.finditer(source)
    ]
    react_router_reexport_ranges = [
        (match.start(), match.end())
        for match in _REACT_ROUTER_ROUTE_REEXPORT_PATTERN.finditer(source)
    ]
    for match in _RUNTIME_ALIAS_BINDING_PATTERN.finditer(source):
        target = match.group("target")
        if runtime_aliases.isdisjoint(_runtime_alias_identifiers(target)):
            continue
        if _is_explicit_runtime_binding(
            target,
            runtime_aliases,
            factory_aliases,
        ):
            modeled_assignment_offsets.add(match.start("equals"))
            if _normalized_runtime_binding_target(target) in runtime_aliases:
                modeled_alias_ranges.append(
                    (match.start("target"), match.end("target")),
                )
            continue
        return True

    for match in _RUNTIME_ALIAS_MUTATION_PATTERN.finditer(source):
        if match.start("equals") in modeled_assignment_offsets:
            continue
        if not runtime_aliases.isdisjoint(
            _runtime_alias_identifiers(_assignment_value(source, match.end())),
        ):
            return True

    for match in _RUNTIME_ALIAS_RETURN_PATTERN.finditer(source):
        target = _assignment_value(source, match.end())
        if _normalized_runtime_binding_target(target).startswith("<"):
            continue
        if not runtime_aliases.isdisjoint(_runtime_alias_identifiers(target)):
            return True

    if any(
        not runtime_aliases.isdisjoint(
            _runtime_alias_identifiers(match.group("target")),
        )
        for match in _RUNTIME_ALIAS_OBJECT_PROPERTY_PATTERN.finditer(source)
    ):
        return True

    for match in _RUNTIME_ALIAS_CALL_ARGUMENT_PATTERN.finditer(source):
        if any(
            start <= match.start("target") and match.end("target") <= end
            for start, end in modeled_alias_ranges + react_router_import_ranges
        ):
            continue
        if not runtime_aliases.isdisjoint(
            _runtime_alias_identifiers(match.group("target")),
        ):
            return True

    if any(
        not runtime_aliases.isdisjoint(
            _runtime_alias_identifiers(match.group("target")),
        )
        for match in _LOCAL_DEFAULT_EXPORT_PATTERN.finditer(source)
    ):
        return True
    if _source_uses_unmodeled_runtime_alias_expression(
        source,
        runtime_aliases=runtime_aliases,
        factory_aliases=factory_aliases,
        modeled_ranges=(
            modeled_alias_ranges
            + react_router_import_ranges
            + react_router_reexport_ranges
        ),
    ):
        return True
    return False


def _is_reparse_or_link(metadata: object) -> bool:
    return bool(
        stat.S_ISLNK(getattr(metadata, "st_mode", 0))
        or getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _safe_frontend_source_path(
    path: Path,
    frontend_directory: Path,
    frontend_root: Path,
) -> Path | None:
    try:
        parts = path.relative_to(frontend_directory).parts
    except ValueError:
        return None
    current = frontend_directory
    resolved: Path | None = None
    for index, part in enumerate(parts):
        current /= part
        try:
            metadata = os.lstat(current)
            resolved = current.resolve(strict=True)
            resolved.relative_to(frontend_root)
        except (OSError, ValueError):
            return None
        if _is_reparse_or_link(metadata):
            return None
        if index < len(parts) - 1:
            if not stat.S_ISDIR(metadata.st_mode):
                return None
        elif stat.S_ISDIR(metadata.st_mode):
            continue
        elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            return None
    return resolved


def _frontend_uses_react_router_server_api(frontend_directory: Path) -> bool:
    if not frontend_directory.is_dir():
        return True
    try:
        frontend_metadata = os.lstat(frontend_directory)
        frontend_root = frontend_directory.resolve(strict=True)
    except OSError:
        return True
    if (
        not stat.S_ISDIR(frontend_metadata.st_mode)
        or _is_reparse_or_link(frontend_metadata)
    ):
        return True
    sources: dict[Path, str] = {}
    try:
        paths = frontend_directory.rglob("*")
        for path in paths:
            try:
                candidate_parts = path.relative_to(frontend_directory).parts
            except ValueError:
                return True
            if any(part in _FRONTEND_IGNORED_DIRECTORIES for part in candidate_parts):
                continue
            resolved_path = _safe_frontend_source_path(
                path,
                frontend_directory,
                frontend_root,
            )
            if resolved_path is None:
                return True
            relative_parts = resolved_path.relative_to(frontend_root).parts
            if path.name.startswith("entry.server."):
                return True
            if path.suffix not in _FRONTEND_SOURCE_SUFFIXES:
                continue
            try:
                source = resolved_path.read_text(encoding="utf-8")
            except OSError:
                return True
            try:
                sources[resolved_path] = _source_without_typescript_type_declarations(
                    source,
                    is_typescript=(path.suffix in _TYPESCRIPT_SOURCE_SUFFIXES),
                )
            except OSError:
                return True
    except OSError:
        return True
    if _has_unsafe_local_frontend_bindings(sources):
        return True
    reexports = _all_react_router_route_reexports(sources)
    for path, runtime_source in sources.items():
        if _source_uses_unmodeled_react_router_runtime_binding(
            runtime_source,
        ):
            return True
        factory_aliases, invalid_factory_import = _expanded_react_router_factory_aliases(
            runtime_source,
        )
        if invalid_factory_import:
            return True
        if (
            any(pattern.search(runtime_source) for pattern in _REACT_ROUTER_SERVER_PATTERNS)
            or _ROUTE_ACTION_SHORTHAND_PATTERN.search(runtime_source)
            or _source_uses_extracted_route_action_shorthand(runtime_source)
            or _source_uses_route_object_action(
                runtime_source,
                router_factory_aliases=factory_aliases,
            )
            or _source_uses_jsx_route_action(
                runtime_source,
                imported_route_components=_imported_react_router_route_aliases(
                    path,
                    runtime_source,
                    sources,
                    reexports,
                ),
            )
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
        completed = subprocess.run(
            _process_command(command),
            capture_output=True,
            text=True,
            check=False,
        )
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


def _run_pip_dependency_scan(
    command: list[str],
    *,
    exception_path: Path,
    requirements_path: Path,
    application_directory: Path,
    evidence_path: Path,
) -> dict[str, object]:
    try:
        completed = subprocess.run(
            _process_command(command),
            capture_output=True,
            text=True,
            check=False,
        )
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
        audit_report = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result["error_code"] = "PIP_AUDIT_REPORT_INVALID"
        _persist_scan_evidence(evidence_path, result)
        return result
    if not isinstance(audit_report, dict):
        result["error_code"] = "PIP_AUDIT_REPORT_INVALID"
        _persist_scan_evidence(evidence_path, result)
        return result
    _write_redacted_json(evidence_path, audit_report)
    if completed.returncode == 0:
        return result
    exception = evaluate_pip_audit_exception(
        audit_report,
        exception_path=exception_path,
        requirements_path=requirements_path,
        application_directory=application_directory,
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
    pip_audit_exception: Path | None = None,
) -> dict[str, object]:
    """Run required local scanner commands and persist one aggregate gate result."""
    image_ref = os.getenv("ACCEPTANCE_IMAGE", "")
    repository_root = Path(__file__).resolve().parents[3]
    frontend_directory = Path(__file__).resolve().parents[2] / "frontend"
    output_path = Path(output)
    evidence_directory = output_path.parent
    evidence_directory.mkdir(parents=True, exist_ok=True)
    backend_directory = Path(__file__).resolve().parents[1]
    requirements_path = backend_directory / "requirements.txt"
    application_directory = backend_directory / "app"
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
    python_command = [
        sys.executable,
        "-m",
        "pip_audit",
        "-r",
        "requirements.txt",
        "--format",
        "json",
        "--output",
        str(report_paths["python_dependencies"]),
    ]
    python_result = (
        _run_pip_dependency_scan(
            python_command,
            exception_path=pip_audit_exception,
            requirements_path=requirements_path,
            application_directory=application_directory,
            evidence_path=report_paths["python_dependencies"],
        )
        if pip_audit_exception is not None
        else scanner_gate("python_dependencies", python_command)
    )
    gates = {
        "python_dependencies": python_result,
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

    canonical_security = input_dir / "security.json"
    canonical_web = input_dir / "web.json"
    aggregate_value, aggregate_error = read_evidence(canonical_security)
    web_value, web_error = read_evidence(canonical_web)
    aggregate_gates = (
        aggregate_value.get("gates")
        if isinstance(aggregate_value, dict)
        else None
    )
    aggregate_gate_names = REQUIRED_SCAN_GATES - {"web_security"}

    def valid_security_aggregate(value: object) -> bool:
        if not isinstance(value, dict) or set(value) != {"status", "gates"}:
            return False
        gates = value.get("gates")
        if not isinstance(gates, dict) or set(gates) != aggregate_gate_names:
            return False
        statuses = []
        for name in aggregate_gate_names:
            gate = gates[name]
            if not isinstance(gate, dict) or gate.get("status") not in {"passed", "failed"}:
                return False
            statuses.append(gate["status"])
        expected_status = "passed" if all(status == "passed" for status in statuses) else "failed"
        return value.get("status") == expected_status

    invalid_aggregate = aggregate_error is not None or not valid_security_aggregate(aggregate_value)
    invalid_web_evidence = web_error is not None or not isinstance(web_value, dict)

    for path in sorted(input_dir.rglob("security.json")):
        if path.absolute() == canonical_security.absolute():
            continue
        value, error_code = read_evidence(path)
        if error_code is not None or not isinstance(value, dict):
            invalid_aggregate = True
    for path in sorted(input_dir.rglob("web.json")):
        if path.absolute() == canonical_web.absolute():
            continue
        value, error_code = read_evidence(path)
        if error_code is not None or not isinstance(value, dict):
            invalid_web_evidence = True

    def evidence_error(relative_path: str) -> str | None:
        value, error_code = read_evidence(input_dir / relative_path)
        if error_code is not None:
            return error_code
        return None if isinstance(value, (dict, list)) else "SECURITY_EVIDENCE_INVALID"

    gates = {}
    for name in sorted(REQUIRED_SCAN_GATES):
        relative_path = REQUIRED_SCAN_EVIDENCE_FILES[name]
        if invalid_aggregate and name != "web_security":
            gates[name] = {
                "status": "failed",
                "error_code": aggregate_error or "SECURITY_EVIDENCE_INVALID",
                "evidence_path": relative_path,
            }
        elif invalid_web_evidence and name == "web_security":
            gates[name] = {
                "status": "failed",
                "error_code": web_error or "SECURITY_EVIDENCE_INVALID",
                "evidence_path": relative_path,
            }
        elif (error_code := evidence_error(relative_path)) is not None:
            gates[name] = {
                "status": "failed",
                "error_code": error_code,
                "evidence_path": relative_path,
            }
        elif name == "web_security":
            safe_web = _redact_json_value(web_value)
            gates[name] = {
                **(
                    safe_web
                    if _complete_web_gate(safe_web)
                    else {
                        "status": "failed",
                        "error_code": "WEB_SECURITY_GATE_INCOMPLETE",
                    }
                ),
                "evidence_path": relative_path,
            }
        elif not isinstance(aggregate_gates.get(name), dict):
            gates[name] = {
                "status": "failed",
                "error_code": "SECURITY_GATE_MISSING",
                "evidence_path": relative_path,
            }
        else:
            gates[name] = {
                **_redact_json_value(aggregate_gates[name]),
                "evidence_path": relative_path,
            }
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
    all_scans.add_argument("--pip-audit-exception", type=Path)
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
            pip_audit_exception=args.pip_audit_exception,
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
