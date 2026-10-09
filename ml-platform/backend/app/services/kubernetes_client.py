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
GONE = "KUBERNETES_GONE"
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
        if status == 410:
            return KubernetesClientError(GONE, "watch resource version expired (410)")
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
        self._batch = k8s_client.BatchV1Api(api_client)
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

    # ---- Week 14 job surface ----
    def get_job(self, name: str, namespace: str | None = None) -> dict | None:
        """Read one Job; namespace-scoped read first, cluster fallback for old callers."""
        if namespace:
            try:
                result = self._batch.read_namespaced_job(
                    name, namespace, _request_timeout=self._request_timeout
                )
            except Exception as error:  # noqa: BLE001
                if getattr(error, "status", None) == 404:
                    return None
                raise _map_exception(error) from error
            return _job_status_to_dict(result)
        try:
            result = self._batch.list_job_for_all_namespaces(
                field_selector=f"metadata.name={name}", _request_timeout=self._request_timeout
            )
        except Exception as error:  # noqa: BLE001
            raise _map_exception(error) from error
        if not result.items:
            return None
        return _job_status_to_dict(result.items[0])

    def create_job(self, manifest: dict) -> dict:
        from kubernetes import client as k8s_client

        spec = manifest["spec"]
        container = spec["template"]["spec"]["containers"][0]
        selector = spec.get("selector")
        body = k8s_client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=k8s_client.V1ObjectMeta(
                name=manifest["metadata"]["name"],
                namespace=manifest["metadata"]["namespace"],
                labels=dict(manifest["metadata"].get("labels") or {}),
            ),
            spec=k8s_client.V1JobSpec(
                backoff_limit=spec["backoffLimit"],
                active_deadline_seconds=spec.get("activeDeadlineSeconds"),
                ttl_seconds_after_finished=spec.get("ttlSecondsAfterFinished"),
                manual_selector=True if selector else None,
                selector=k8s_client.V1LabelSelector(match_labels=dict(selector["matchLabels"]))
                if selector
                else None,
                template=k8s_client.V1PodTemplateSpec(
                    metadata=k8s_client.V1ObjectMeta(
                        labels=dict(spec["template"]["metadata"]["labels"])
                    ),
                    spec=k8s_client.V1PodSpec(
                        restart_policy="Never",
                        automount_service_account_token=False,
                        containers=[
                            k8s_client.V1Container(
                                name=container["name"],
                                image=container["image"],
                                command=container.get("command"),
                                args=container.get("args"),
                                env=[
                                    k8s_client.V1EnvVar(name=entry["name"], value=entry["value"])
                                    for entry in container.get("env", [])
                                ],
                                resources=k8s_client.V1ResourceRequirements(
                                    requests=dict(container["resources"]["requests"])
                                ),
                            )
                        ],
                    ),
                ),
            ),
        )
        try:
            result = self._batch.create_namespaced_job(
                manifest["metadata"]["namespace"], body, _request_timeout=self._request_timeout
            )
        except Exception as error:  # noqa: BLE001
            raise _map_exception(error) from error
        return {
            "name": result.metadata.name,
            "namespace": result.metadata.namespace,
            "resource_version": result.metadata.resource_version,
        }

    def delete_job(self, name: str, namespace: str | None = None) -> None:
        target_ns = namespace
        if target_ns is None:
            job = self.get_job(name)
            if job is None:
                return
            target_ns = job["namespace"]
        try:
            self._batch.delete_namespaced_job(
                name,
                target_ns,
                propagation_policy="Foreground",
                _request_timeout=self._request_timeout,
            )
        except Exception as error:  # noqa: BLE001
            status = getattr(error, "status", None)
            if status == 404:
                return
            raise _map_exception(error) from error

    def list_job_pods(self, job_name: str, namespace: str | None = None, label_selector: str | None = None) -> list[dict]:
        # Our generated pods reliably carry linkraft.io/operation-id; the legacy
        # job-name label was removed in K8s 1.27, so it is only a fallback.
        selectors = (
            [label_selector]
            if label_selector
            else [f"batch.kubernetes.io/job-name={job_name}", f"job-name={job_name}"]
        )
        last_error: Exception | None = None
        for selector in selectors:
            try:
                if namespace:
                    result = self._core.list_namespaced_pod(
                        namespace, label_selector=selector, _request_timeout=self._request_timeout
                    )
                else:
                    result = self._core.list_pod_for_all_namespaces(
                        label_selector=selector, _request_timeout=self._request_timeout
                    )
            except Exception as error:  # noqa: BLE001
                last_error = error
                continue
            pods = [
                {
                    "name": item.metadata.name,
                    "namespace": item.metadata.namespace,
                    "phase": item.status.phase if item.status else "",
                }
                for item in result.items
            ]
            if pods:
                return pods
        if last_error is not None:
            raise _map_exception(last_error) from last_error
        return []

    def read_pod_log(self, pod_name: str, cursor: int, limit_bytes: int, namespace: str | None = None) -> str:
        target_ns = namespace
        if target_ns is None:
            try:
                pods = self._core.list_pod_for_all_namespaces(
                    field_selector=f"metadata.name={pod_name}", _request_timeout=self._request_timeout
                )
                if not pods.items:
                    return ""
                target_ns = pods.items[0].metadata.namespace
            except Exception as error:  # noqa: BLE001
                raise _map_exception(error) from error
        try:
            text = self._core.read_namespaced_pod_log(
                pod_name,
                target_ns,
                _preload_content=True,
                _request_timeout=self._request_timeout,
            )
        except Exception as error:  # noqa: BLE001
            status = getattr(error, "status", None)
            if status == 400 and "container" in str(getattr(error, "reason", "")).lower():
                return ""
            raise _map_exception(error) from error
        return str(text or "")[cursor : cursor + limit_bytes]

    # ---- Week 15 notebook session surface ----
    def create_service(self, manifest: dict) -> dict:
        from kubernetes import client as k8s_client

        spec = manifest["spec"]
        ports = [
            k8s_client.V1ServicePort(
                name=entry.get("name"),
                port=entry["port"],
                target_port=entry.get("targetPort", entry["port"]),
                protocol=entry.get("protocol", "TCP"),
            )
            for entry in spec.get("ports", [])
        ]
        body = k8s_client.V1Service(
            metadata=k8s_client.V1ObjectMeta(
                name=manifest["metadata"]["name"],
                namespace=manifest["metadata"]["namespace"],
                labels=dict(manifest["metadata"].get("labels") or {}),
            ),
            spec=k8s_client.V1ServiceSpec(
                type=spec.get("type", "ClusterIP"),
                selector=dict(spec.get("selector") or {}),
                ports=ports,
            ),
        )
        try:
            result = self._core.create_namespaced_service(
                manifest["metadata"]["namespace"], body, _request_timeout=self._request_timeout
            )
        except Exception as error:  # noqa: BLE001
            raise _map_exception(error) from error
        return {"name": result.metadata.name, "namespace": result.metadata.namespace}

    def delete_service(self, name: str, namespace: str | None = None) -> None:
        if namespace is None:
            return
        try:
            self._core.delete_namespaced_service(
                name, namespace, _request_timeout=self._request_timeout
            )
        except Exception as error:  # noqa: BLE001
            if getattr(error, "status", None) == 404:
                return
            raise _map_exception(error) from error

    def proxy_service_request(
        self,
        *,
        namespace: str,
        service: str,
        port: int,
        subpath: str,
        method: str = "GET",
        headers: dict | None = None,
        body: bytes | None = None,
    ) -> dict:
        """Reverse-proxy one HTTP request through the K8s API service proxy."""
        clean_subpath = subpath.lstrip("/")
        path = f"/api/v1/namespaces/{namespace}/services/{service}:{port}/proxy"
        if clean_subpath:
            path = f"{path}/{clean_subpath}"
        try:
            (data, status, headers) = self._core.api_client.call_api(
                path,
                method.upper(),
                header_params={k: v for k, v in (headers or {}).items() if not k.lower().startswith("x-linkraft")},
                response_type="object",
                auth_settings=["BearerToken"],
                body=body if body is not None and method.upper() in ("POST", "PUT", "PATCH") else None,
                _preload_content=False,
                _request_timeout=self._request_timeout,
            )
            payload = data.read() if hasattr(data, "read") else (data or b"")
            data.close() if hasattr(data, "close") else None
        except Exception as error:  # noqa: BLE001
            status = getattr(error, "status", None)
            if status is not None:
                return {"status": int(status), "body": b"", "headers": {}}
            raise _map_exception(error) from error
        return {"status": int(status), "body": payload or b"", "headers": dict(headers or {})}


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

    # ---- Week 14 job surface ----
    def _jobs_init(self) -> None:
        if not hasattr(self, "jobs"):
            self.jobs: dict[str, dict] = {}
            self.pod_logs: dict[str, str] = {}
            self.job_events: list[str] = []
        if not hasattr(self, "job_pods"):
            self.job_pods: list[dict] | None = None

    def create_job(self, manifest: dict) -> dict:
        self._jobs_init()
        self._maybe_fail("create_job")
        name = manifest["metadata"]["name"]
        if name in self.jobs:
            raise KubernetesClientError(CONNECTIVITY_FAILED, f"job {name} already exists")
        self.jobs[name] = _fake_k8s_job(name, manifest)
        self.job_events.append(f"create:{name}")
        return dict(self.jobs[name])

    def get_job(self, name: str, namespace: str | None = None) -> dict | None:
        self._jobs_init()
        self.call_log.append("get_job")
        job = self.jobs.get(name)
        if job is None or job.get("deleted"):
            return None
        return dict(job)

    def delete_job(self, name: str, namespace: str | None = None) -> None:
        self._jobs_init()
        self._maybe_fail("delete_job")
        if name in self.jobs:
            self.jobs[name]["deleted"] = True
            self.jobs[name]["active"] = 0
            self.jobs[name]["resource_version"] = str(int(self.jobs[name].get("resource_version", "1")) + 1)
            self.job_events.append(f"delete:{name}")

    def list_job_pods(self, job_name: str, namespace: str | None = None, label_selector: str | None = None) -> list[dict]:
        self._jobs_init()
        self.call_log.append("list_job_pods")
        if self.job_pods is not None:
            return list(self.job_pods)
        return [{"name": f"{job_name}-pod-1", "phase": "Succeeded" if self.jobs.get(job_name, {}).get("succeeded") else "Running"}]

    def read_pod_log(self, pod_name: str, cursor: int, limit_bytes: int, namespace: str | None = None) -> str:
        self._jobs_init()
        text = self.pod_logs.get(pod_name, "")
        return text[cursor : cursor + limit_bytes]

    # ---- Week 15 notebook session surface ----
    def create_service(self, manifest: dict) -> dict:
        self._jobs_init()
        if not hasattr(self, "services"):
            self.services: dict[str, dict] = {}
            self.proxy_responses: list[dict] = []
        self._maybe_fail("create_service")
        name = manifest["metadata"]["name"]
        self.services[name] = {"namespace": manifest["metadata"]["namespace"], "manifest": manifest}
        self.job_events.append(f"create-service:{name}")
        return {"name": name, "namespace": manifest["metadata"]["namespace"]}

    def delete_service(self, name: str, namespace: str | None = None) -> None:
        self._jobs_init()
        if not hasattr(self, "services"):
            self.services = {}
        if name in self.services:
            del self.services[name]
            self.job_events.append(f"delete-service:{name}")

    def proxy_service_request(
        self,
        *,
        namespace: str,
        service: str,
        port: int,
        subpath: str,
        method: str = "GET",
        headers: dict | None = None,
        body: bytes | None = None,
    ) -> dict:
        self._jobs_init()
        if not hasattr(self, "services"):
            self.services = {}
        self.call_log.append(f"proxy:{service}")
        if service not in self.services:
            return {"status": 404, "body": b"service not found", "headers": {}}
        queued = getattr(self, "proxy_responses", [])
        if queued:
            return dict(queued.pop(0))
        return {"status": 200, "body": b"notebook-ready", "headers": {"Content-Type": "text/plain"}}


class JobClientProtocol(Protocol):
    """Week 14 surface: batch Job lifecycle against one cluster namespace."""

    def create_job(self, manifest: dict) -> dict: ...

    def get_job(self, name: str, namespace: str | None = None) -> dict | None: ...

    def delete_job(self, name: str, namespace: str | None = None) -> None: ...

    def list_job_pods(self, job_name: str, namespace: str | None = None, label_selector: str | None = None) -> list[dict]: ...

    def read_pod_log(self, pod_name: str, cursor: int, limit_bytes: int, namespace: str | None = None) -> str: ...


def _job_status_to_dict(job) -> dict:
    """Map a kubernetes batch V1Job to the platform's plain job dict."""
    conditions = []
    for condition in (job.status.conditions if job.status else None) or []:
        conditions.append(
            {
                "type": condition.type,
                "reason": condition.reason,
                "message": condition.message or "",
            }
        )
    return {
        "name": job.metadata.name,
        "namespace": job.metadata.namespace,
        "labels": dict(job.metadata.labels or {}),
        "succeeded": job.status.succeeded or 0 if job.status else 0,
        "failed": job.status.failed or 0 if job.status else 0,
        "active": job.status.active or 0 if job.status else 0,
        "conditions": conditions,
        "resource_version": job.metadata.resource_version,
        "deleted": False,
    }


def _job_labels(project_id: str, operation_id: str, revision: int, role: str = "job") -> dict:
    labels = {
        "app.kubernetes.io/managed-by": "linkraft",
        "linkraft.io/project-id": str(project_id).replace("-", "")[:32],
        "linkraft.io/operation-id": str(operation_id).replace("-", "")[:32],
        "linkraft.io/revision": str(revision),
    }
    if role != "job":
        labels["linkraft.io/role"] = role
    return labels


def build_job_manifest(
    *,
    job_name: str,
    namespace: str,
    image_ref: str,
    command: list[str],
    args: list[str],
    env: dict,
    resources: dict,
    timeout_seconds: int,
    labels: dict,
    ttl_seconds_finished: int,
) -> dict:
    """Deterministic, security-hardened batch Job manifest.

    Rejects privileged / hostPath / hostNetwork / hostPID / hostPort shapes by
    construction: the generator simply never emits them.
    """
    back = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name, "namespace": namespace, "labels": dict(labels)},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": timeout_seconds,
            "ttlSecondsAfterFinished": ttl_seconds_finished,
            "selector": {"matchLabels": {"linkraft.io/operation-id": labels["linkraft.io/operation-id"]}},
            "template": {
                "metadata": {"labels": dict(labels)},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "containers": [
                        {
                            "name": "linkraft-job",
                            "image": image_ref,
                            "command": list(command),
                            "args": list(args),
                            "env": [{"name": k, "value": v} for k, v in sorted(env.items())],
                            "resources": {
                                "requests": {
                                    "cpu": str(resources.get("cpu_cores", 1)),
                                    "memory": f"{resources.get('memory_gb', 1)}Gi",
                                }
                            },
                        }
                    ],
                },
            },
        },
    }
    return back


def _fake_k8s_job(job_name: str, manifest: dict) -> dict:
    return {
        "name": job_name,
        "namespace": manifest["metadata"]["namespace"],
        "labels": manifest["metadata"]["labels"],
        "succeeded": 0,
        "failed": 0,
        "active": 1,
        "conditions": [],
        "resource_version": "1",
        "deleted": False,
    }
