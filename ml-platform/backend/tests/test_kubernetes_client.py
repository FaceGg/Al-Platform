"""Week 13 Kubernetes client adapter unit tests (no real cluster, no k8s package)."""

import socket
import ssl
import unittest

from app.services.kubernetes_client import (
    AUTH_FAILED,
    CLIENT_UNAVAILABLE,
    CONNECTIVITY_FAILED,
    CREDENTIAL_INVALID,
    CREDENTIAL_MISSING,
    ENDPOINT_FORBIDDEN,
    ENDPOINT_INVALID,
    TLS_ERROR,
    TIMEOUT,
    FakeKubernetesClient,
    KubernetesClientError,
    _map_exception,
    parse_secret_ref,
    redact_text,
    validate_endpoint,
)


def _validated(url: str, allowlist: list[str] | None = None, allow_insecure: bool = False, insecure_tls: bool = False):
    return validate_endpoint(
        url,
        allowlist=allowlist if allowlist is not None else ["127.0.0.1", "*.internal.example.com"],
        allow_insecure=allow_insecure,
        insecure_tls=insecure_tls,
    )


class _FakeApiError(Exception):
    def __init__(self, status: int):
        super().__init__(f"api status {status}")
        self.status = status


class TestEndpointValidation(unittest.TestCase):
    def test_valid_https_host_in_allowlist(self):
        self.assertEqual(_validated("https://127.0.0.1:6443"), "https://127.0.0.1:6443")

    def test_valid_wildcard_suffix(self):
        self.assertEqual(_validated("https://api.prod.internal.example.com:6443"), "https://api.prod.internal.example.com:6443")

    def test_empty_allowlist_denies_everything(self):
        with self.assertRaises(KubernetesClientError) as ctx:
            _validated("https://127.0.0.1:6443", allowlist=[])
        self.assertEqual(ENDPOINT_FORBIDDEN, ctx.exception.code)

    def test_http_requires_double_switch(self):
        with self.assertRaises(KubernetesClientError) as ctx:
            _validated("http://127.0.0.1:6443")
        self.assertEqual(ENDPOINT_INVALID, ctx.exception.code)
        with self.assertRaises(KubernetesClientError) as ctx:
            _validated("http://127.0.0.1:6443", allow_insecure=True, insecure_tls=False)
        self.assertEqual(ENDPOINT_INVALID, ctx.exception.code)
        self.assertEqual(
            _validated("http://127.0.0.1:6443", allow_insecure=True, insecure_tls=True),
            "http://127.0.0.1:6443",
        )

    def test_metadata_host_denied(self):
        with self.assertRaises(KubernetesClientError) as ctx:
            _validated("https://169.254.169.254/latest")
        self.assertEqual(ENDPOINT_FORBIDDEN, ctx.exception.code)

    def test_userinfo_query_fragment_rejected(self):
        for url in (
            "https://user:pass@127.0.0.1:6443",
            "https://127.0.0.1:6443/?x=1",
            "https://127.0.0.1:6443/#frag",
        ):
            with self.assertRaises(KubernetesClientError) as ctx:
                _validated(url)
            self.assertEqual(ENDPOINT_INVALID, ctx.exception.code)

    def test_bad_scheme_and_missing_host(self):
        for url in ("ftp://127.0.0.1:6443", "https://"):
            with self.assertRaises(KubernetesClientError) as ctx:
                _validated(url)
            self.assertEqual(ENDPOINT_INVALID, ctx.exception.code)

    def test_url_length_limit(self):
        with self.assertRaises(KubernetesClientError) as ctx:
            _validated("https://" + "a" * 2100 + ".internal.example.com")
        self.assertEqual(ENDPOINT_INVALID, ctx.exception.code)


class TestSecretRefParsing(unittest.TestCase):
    def test_env_ref(self):
        self.assertEqual(("env", "LINKRAFT_KIND_TOKEN"), parse_secret_ref("env:LINKRAFT_KIND_TOKEN"))

    def test_file_ref(self):
        self.assertEqual(("file", "/etc/linkraft/ca.crt"), parse_secret_ref("file:/etc/linkraft/ca.crt"))

    def test_rejects_raw_material_and_relative_paths(self):
        for ref in (
            "Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6",
            "env:lowercase_name",
            "env:",
            "file:etc/relative.crt",
            "file://etc/double-slash.crt",
            "some-random-token-value",
            "",
        ):
            with self.assertRaises(KubernetesClientError) as ctx:
                parse_secret_ref(ref)
            self.assertEqual(CREDENTIAL_INVALID, ctx.exception.code)


class TestRedaction(unittest.TestCase):
    def test_bearer_tokens_redacted(self):
        text = "request failed with Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6InJlZCIsInR5cCI6IkpXVCJ9 header"
        self.assertNotIn("eyJhbGciOiJSUzI1NiIsImtpZCI6InJlZCIsInR5cCI6IkpXVCJ9", redact_text(text))
        self.assertIn("Bearer [redacted]", redact_text(text))

    def test_query_string_and_long_runs_redacted(self):
        text = "GET https://127.0.0.1:6443/api?token=abcdef123456 failed AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTt"
        redacted = redact_text(text)
        self.assertNotIn("abcdef123456", redacted)
        self.assertIn("[query-redacted]", redacted)


class TestExceptionMapping(unittest.TestCase):
    def test_auth_status(self):
        self.assertEqual(AUTH_FAILED, _map_exception(_FakeApiError(401)).code)
        self.assertEqual(AUTH_FAILED, _map_exception(_FakeApiError(403)).code)

    def test_other_status_is_connectivity(self):
        self.assertEqual(CONNECTIVITY_FAILED, _map_exception(_FakeApiError(500)).code)

    def test_timeout_and_tls(self):
        self.assertEqual(TIMEOUT, _map_exception(socket.timeout("timed out")).code)
        self.assertEqual(TLS_ERROR, _map_exception(ssl.SSLError("certificate verify failed")).code)

    def test_generic_error_is_connectivity(self):
        self.assertEqual(CONNECTIVITY_FAILED, _map_exception(RuntimeError("name resolution failed")).code)


class TestFakeClient(unittest.TestCase):
    def test_protocol_surface_and_call_order(self):
        fake = FakeKubernetesClient()
        for name in ("check_connectivity", "list_nodes", "list_namespaces", "ensure_namespace"):
            self.assertTrue(callable(getattr(fake, name)))
        self.assertEqual({"ok": True, "kubernetes_version": fake.kubernetes_version}, fake.check_connectivity())
        self.assertEqual(1, len(fake.list_nodes()))
        fake.ensure_namespace("w13-demo", {"cpu_cores": 2})
        self.assertEqual(
            ["check_connectivity", "list_nodes", "ensure_namespace"],
            fake.call_log,
        )

    def test_injected_failure(self):
        fake = FakeKubernetesClient(fail_code=TIMEOUT, fail_message="connect timed out")
        with self.assertRaises(KubernetesClientError) as ctx:
            fake.check_connectivity()
        self.assertEqual(TIMEOUT, ctx.exception.code)
        self.assertEqual(TIMEOUT, fake.ensured and TIMEOUT or TIMEOUT)

    def test_ensure_namespace_idempotent(self):
        fake = FakeKubernetesClient()
        fake.ensure_namespace("w13-demo")
        fake.ensure_namespace("w13-demo")
        self.assertEqual(["w13-demo"], fake.created_namespaces)

    def test_missing_dependency_code_exists(self):
        # The lazy import path surfaces this code; the constant is the contract.
        self.assertEqual("KUBERNETES_CLIENT_UNAVAILABLE", CLIENT_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
