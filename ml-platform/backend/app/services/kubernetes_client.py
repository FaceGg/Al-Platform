"""Kubernetes client adapter for Week 13 (read-only discovery + bounded writes).

The official ``kubernetes`` package is imported lazily so environments without
it degrade to ``KUBERNETES_CLIENT_UNAVAILABLE`` instead of breaking the app.
Credential material (``env:``/``file:`` references) is resolved only at client
build time and never persisted, logged or echoed. ``FakeKubernetesClient``
keeps unit tests on the same code path without a real cluster.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import ssl
from typing import Any, Protocol
from urllib.parse import urlsplit

_ENV_REF_PATTERN = re.compile(r"^env:([A-Z][A-Z0-9_]*)$")
_TOKEN_PATTERN = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{8,}")
_LONG_SECRET_PATTERN = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
_MAX_URL_LENGTH = 2083
_METADATA_HOSTS = {"169.254.169.254"}

ENDPOINT_INVALID = "KUBERNETES_ENDPOINT_INVALID"
ENDPOINT_FORBIDDEN = "KUBERNETES_ENDPOINT_FORBIDDEN"
CREDENTIAL_MISSING = "KUBERNETES_CREDENTIAL_MISSING"
CREDENTIAL_INVALID = "KUBERNETES_CREDENTIAL_INVALID"
CONNECTIVITY_FAILED = "KUBERNETES_CONNECTIVITY_FAILED"
TIMEOUT = "KUBERNETES_TIMEOUT"
TLS_ERROR = "KUBERNETES_TLS_ERROR"
AUTH_FAILED = "KUBERNETES_AUTH_FAILED"
CLIENT_UNAVAILABLE = "KUBERNETES_CLIENT_UNAVAILABLE"
NAMESPACE_INVALID = "KUBERNETES_NAMESPACE_INVALID"
QUOTA_INVALID = "KUBERNETES_QUOTA_INVALID"


class KubernetesClientError(Exception):
    """Typed, redacted client error; ``code`` drives API error responses."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(redact_text(message) or code)
        self.code = code
        self.message = redact_text(message)


def redact_text(text: str) -> str:
    """Strip bearer tokens, long secret-like runs and URL query strings."""
    if not text:
        return ""
    redacted = _TOKEN_PATTERN.sub("Bearer [redacted]", text)
    redacted = _LONG_SECRET_PATTERN.sub("[redacted]", redacted)
    redacted = re.sub(r"\?[^\\s\"']+", "?[query-redacted]", redacted)
    return redacted


def _host_allowed(host: str, allowlist: list[str]) -> bool:
    for entry in allowlist:
        entry = entry.strip()
        if not entry:
            continue
        if entry.startswith("*."):
            suffix = entry[1:].lower()
            if host.lower().endswith(suffix):
                return True
        elif host.lower() == entry.lower():
            return True
    return False


def validate_endpoint(
    api_server_url: str,
    *,
    allowlist: list[str],
    allow_insecure: bool,
    insecure_tls: bool = False,
) -> str:
    """Validate a user-supplied API server URL and return the normalized URL.

    Fail-closed: empty allowlist rejects everything; insecure http requires the
    cluster flag AND the global switch; metadata addresses are always blocked.
    """
    if not api_server_url or len(api_server_url) > _MAX_URL_LENGTH:
        raise KubernetesClientError(ENDPOINT_INVALID, "API server URL missing or too long")
    parts = urlsplit(api_server_url.strip())
    scheme = (parts.scheme or "").lower()
    if scheme not in ("https", "http"):
        raise KubernetesClientError(ENDPOINT_INVALID, "API server URL must use http(s)")
    if parts.username or parts.password:
        raise KubernetesClientError(ENDPOINT_INVALID, "userinfo is not allowed in API server URL")
    if parts.query or parts.fragment:
        raise KubernetesClientError(ENDPOINT_INVALID, "query/fragment is not allowed in API server URL")
    host = parts.hostname
    if not host:
        raise KubernetesClientError(ENDPOINT_INVALID, "API server URL has no host")
    if scheme == "http" and not (allow_insecure and insecure_tls):
        raise KubernetesClientError(ENDPOINT_INVALID, "http endpoints require insecure_tls and the global switch")
    if host in _METADATA_HOSTS:
        raise KubernetesClientError(ENDPOINT_FORBIDDEN, "metadata addresses are forbidden")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and ip.is_loopback and scheme == "http" and not (allow_insecure and insecure_tls):
        raise KubernetesClientError(ENDPOINT_FORBIDDEN, "loopback http endpoint is forbidden")
    if not _host_allowed(host, allowlist):
        raise KubernetesClientError(ENDPOINT_FORBIDDEN, "API server host is not in the endpoint allowlist")
    return api_server_url.strip()


def parse_secret_ref(secret_ref: str) -> tuple[str, str]:
    """Validate a credential reference; returns ("env", NAME) or ("file", path)."""
    if not secret_ref:
        raise KubernetesClientError(CREDENTIAL_INVALID, "credential reference is empty")
    match = _ENV_REF_PATTERN.match(secret_ref)
    if match:
        return "env", match.group(1)
    if secret_ref.startswith("file:"):
        path = secret_ref[5:]
        if not path.startswith("/") or path.startswith("//") or "\\" in path or " " in path or ".." in path:
            raise KubernetesClientError(CREDENTIAL_INVALID, "file credential reference must be an absolute clean path")
        return "file", path
    raise KubernetesClientError(CREDENTIAL_INVALID, "credential reference must use env:NAME or file:/absolute/path")


def resolve_credential(secret_ref: str) -> tuple[str, str]:
    """Resolve a credential reference at call time; never log or persist the value."""
    kind, value = parse_secret_ref(secret_ref)
    if kind == "env":
        material = os.environ.get(value)
        if material is None:
            raise KubernetesClientError(CREDENTIAL_MISSING, f"environment variable {value} is not set")
        return "token", material.strip()
    try:
        with open(value, "r", encoding="utf-8") as handle:
            material = handle.read()
    except FileNotFoundError as error:
        raise KubernetesClientError(CREDENTIAL_MISSING, f"credential file {value} does not exist") from error
    except OSError as error:
        raise KubernetesClientError(CREDENTIAL_INVALID, f"credential file {value} is not readable") from error
    return "file", material.strip()


class KubernetesClientProtocol(Protocol):
    """Week 13 surface: read-only discovery plus one idempotent write."""

    def check_connectivity(self) -> dict: ...

    def list_nodes(self) -> list[dict]: ...

    def list_namespaces(self) -> list[str]: ...

    def ensure_namespace(self, name: str, quota_json: dict | None = None) -> dict: ...


def _map_exception(error: Exception) -> KubernetesClientError:
    if isinstance(error, KubernetesClientError):
        return error
    status = getattr(error, "status", None)
    if isinstance(error, (socket.timeout, TimeoutError)):
        return KubernetesClientError(TIMEOUT, str(error))
    if isinstance(error, ssl.SSLError):
        return KubernetesClientError(TLS_ERROR, str(error))
    if isinstance(status, int):
        if status in (401, 403):
            return KubernetesClientError(AUTH_FAILED, f"cluster rejected credentials (status {status})")
        return KubernetesClientError(CONNECTIVITY_FAILED, f"cluster request failed (status {status})")
    return KubernetesClientError(CONNECTIVITY_FAILED, str(error))


def build_kubernetes_client(
    cluster,
    credential_ref,
    *,
    connect_timeout_seconds: float,
    read_timeout_seconds: float,
):
    """Build a real client from a cluster row + credential ref row.

    Resolves the credential reference at call time; the official client is
    imported lazily so missing dependencies surface as a typed error.
    """
    try:
        from kubernetes import client as k8s_client
    except ImportError as error:  # pragma: no cover - exercised only without the package
        raise KubernetesClientError(CLIENT_UNAVAILABLE, f"kubernetes package is not importable: {error}") from error

    kind, material = resolve_credential(credential_ref.secret_ref)
    configuration = k8s_client.Configuration()
    configuration.host = cluster.api_server_url
    configuration.verify_ssl = not cluster.insecure_tls
    if kind == "token":
        configuration.api_key = {"authorization": material}
        configuration.api_key_prefix = {"authorization": "Bearer"}
    else:
        configuration.ssl_ca_cert = credential_ref.secret_ref[5:]
    api = k8s_client.ApiClient(configuration)
    return RealKubernetesClient(api, connect_timeout_seconds, read_timeout_seconds)


class RealKubernetesClient:
    """Thin wrapper mapping official-client exceptions to typed errors."""

    def __init__(self, api_client, connect_timeout_seconds: float, read_timeout_seconds: float):
        from kubernetes import client as k8s_client

        self._core = k8s_client.CoreV1Api(api_client)
        self._request_timeout = (connect_timeout_seconds, read_timeout_seconds)

    def check_connectivity(self) -> dict:
        try:
            (_data, status, _headers) = self._core.api_client.call_api(
                "/version",
                "GET",
                response_type="object",
                auth_settings=["BearerToken"],
                _request_timeout=self._request_timeout,
            )
        except Exception as error:  # noqa: BLE001 - mapped below
            raise _map_exception(error) from error
        if status != 200:
            raise KubernetesClientError(CONNECTIVITY_FAILED, f"version endpoint returned status {status}")
        data = _data if isinstance(_data, dict) else {}
        return {
            "ok": True,
            "kubernetes_version": str(data.get("gitVersion", ""))[:32] or None,
        }

    def list_nodes(self) -> list[dict]:
        try:
            result = self._core.list_node(_request_timeout=self._request_timeout)
        except Exception as error:  # noqa: BLE001
            raise _map_exception(error) from error
        nodes = []
        for item in result.items[:100]:
            capacity = item.status.capacity or {}
            allocatable = item.status.allocatable or {}
            nodes.append(
                {
                    "hostname": item.metadata.name,
                    "arch": (item.status.node_info.architecture if item.status.node_info else "") or "",
                    "cpu_cores": capacity.get("cpu", ""),
                    "memory": capacity.get("memory", ""),
                    "gpu": allocatable.get("nvidia.com/gpu", "0"),
                    "labels": dict(item.metadata.labels or {}),
                }
            )
        return nodes

    def list_namespaces(self) -> list[str]:
        try:
            result = self._core.list_namespace(_request_timeout=self._request_timeout)
        except Exception as error:  # noqa: BLE001
            raise _map_exception(error) from error
        return [item.metadata.name for item in result.items]

    def ensure_namespace(self, name: str, quota_json: dict | None = None) -> dict:
        from kubernetes import client as k8s_client

        def to_hard(quota: dict) -> dict:
            # Translate platform quota keys to Kubernetes resource names.
            translated = {}
            for key, value in quota.items():
                if key == "cpu_cores":
                    translated["cpu"] = str(value)
                elif key == "memory_mb":
                    translated["memory"] = f"{value}Mi"
                elif key == "max_pods":
                    translated["pods"] = str(value)
            return translated

        try:
            namespaces = {item.metadata.name for item in self._core.list_namespace(
                _request_timeout=self._request_timeout
            ).items}
            if name not in namespaces:
                self._core.create_namespace(
                    body=k8s_client.V1Namespace(metadata=k8s_client.V1ObjectMeta(name=name)),
                    _request_timeout=self._request_timeout,
                )
            hard = to_hard(quota_json or {})
            if hard:
                quota_name = f"{name}-linkraft-quota"
                quotas = {
                    quota.metadata.name
                    for quota in self._core.list_namespaced_resource_quota(
                        name, _request_timeout=self._request_timeout
                    ).items
                }
                body = k8s_client.V1ResourceQuota(
                    metadata=k8s_client.V1ObjectMeta(name=quota_name),
                    spec=k8s_client.V1ResourceQuotaSpec(hard=hard),
                )
                if quota_name in quotas:
                    self._core.replace_namespaced_resource_quota(
                        quota_name, name, body, _request_timeout=self._request_timeout
                    )
                else:
                    self._core.create_namespaced_resource_quota(
                        name, body, _request_timeout=self._request_timeout
                    )
        except Exception as error:  # noqa: BLE001
            raise _map_exception(error) from error
        return {"name": name, "ensured": True, "quota_applied": bool(quota_json)}


class FakeKubernetesClient:
    """Programmable test double: inject outcomes, assert call order, no cluster."""

    def __init__(
        self,
        *,
        kubernetes_version: str = "v1.30.0",
        nodes: list[dict] | None = None,
        namespaces: list[str] | None = None,
        fail_code: str | None = None,
        fail_message: str = "",
        created_namespaces: list[str] | None = None,
    ):
        self.kubernetes_version = kubernetes_version
        self.nodes = nodes if nodes is not None else [
            {
                "hostname": "kind-control-plane",
                "arch": "amd64",
                "cpu_cores": "16",
                "memory": "32Gi",
                "gpu": "0",
                "labels": {"kubernetes.io/os": "linux"},
            }
        ]
        self.namespaces = list(namespaces or ["default", "kube-system"])
        self.fail_code = fail_code
        self.fail_message = fail_message
        self.created_namespaces = list(created_namespaces or [])
        self.call_log: list[str] = []
        self.ensured: list[tuple[str, dict | None]] = []

    def _maybe_fail(self, action: str) -> None:
        self.call_log.append(action)
        if self.fail_code:
            raise KubernetesClientError(self.fail_code, self.fail_message or self.fail_code)

    def check_connectivity(self) -> dict:
        self._maybe_fail("check_connectivity")
        return {"ok": True, "kubernetes_version": self.kubernetes_version}

    def list_nodes(self) -> list[dict]:
        self._maybe_fail("list_nodes")
        return list(self.nodes)

    def list_namespaces(self) -> list[str]:
        self._maybe_fail("list_namespaces")
        return list(self.namespaces)

    def ensure_namespace(self, name: str, quota_json: dict | None = None) -> dict:
        self._maybe_fail("ensure_namespace")
        if name not in self.created_namespaces and name not in self.namespaces:
            self.created_namespaces.append(name)
        self.ensured.append((name, quota_json))
        return {"name": name, "ensured": True, "quota_applied": bool(quota_json)}
