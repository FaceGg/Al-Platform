"""A-05 回归：算子出站 URL 统一 SSRF 校验（审计 2026-10-28 批次九）。"""

import sys
import unittest

sys.path.insert(0, ".")

from app.services.outbound import (
    OutboundUrlError,
    fetch_url_bytes,
    validate_outbound_url,
)


def _resolver(addresses):
    return lambda host, port: addresses


class TestValidateOutboundUrl(unittest.TestCase):
    def test_accepts_public_http_and_https(self):
        self.assertEqual(
            validate_outbound_url(
                "http://example.com/file.csv", resolve=_resolver(["93.184.216.34"]),
            ),
            "http://example.com/file.csv",
        )
        self.assertEqual(
            validate_outbound_url(
                "https://example.com/data.xlsx", resolve=_resolver(["93.184.216.34"]),
            ),
            "https://example.com/data.xlsx",
        )

    def test_rejects_non_http_schemes(self):
        for url in ("file:///etc/passwd", "ftp://example.com/x", "gopher://x"):
            with self.assertRaises(OutboundUrlError):
                validate_outbound_url(url, resolve=_resolver(["93.184.216.34"]))

    def test_rejects_loopback_and_private_targets(self):
        cases = [
            ("http://127.0.0.1:8000/api", None),
            ("http://localhost/file", _resolver(["127.0.0.1"])),
            ("http://10.1.2.3/x", None),
            ("http://192.168.1.5/x", None),
            ("http://169.254.169.254/latest/meta-data", None),
            ("http://example.com/x", _resolver(["10.0.0.9"])),  # DNS 重绑定至内网
        ]
        for url, resolver in cases:
            with self.assertRaises(OutboundUrlError, msg=url):
                validate_outbound_url(url, resolve=resolver)

    def test_rejects_metadata_hostnames(self):
        for host in ("metadata", "metadata.google.internal"):
            with self.assertRaises(OutboundUrlError):
                validate_outbound_url(
                    f"http://{host}/computeMetadata/v1",
                    resolve=_resolver(["93.184.216.34"]),
                )

    def test_rejects_credentials_and_invalid_input(self):
        for url in (
            "http://user:pass@example.com/x",
            "",
            "http://例え.jp/x",
            "http://example.com/#frag",
        ):
            with self.assertRaises(OutboundUrlError):
                validate_outbound_url(url, resolve=_resolver(["93.184.216.34"]))

    def test_unresolvable_host_is_rejected(self):
        def boom(host, port):
            raise OSError("dns")

        with self.assertRaises(OutboundUrlError):
            validate_outbound_url("http://no-such-host.invalid/x", resolve=boom)

    def test_fetch_validates_before_request(self):
        # 抓取入口先校验：内网目标在发出任何请求前即被拒
        with self.assertRaises(OutboundUrlError):
            fetch_url_bytes("http://127.0.0.1:9/never-reached")


class TestOperatorWiring(unittest.TestCase):
    def test_read_url_rejects_internal_target(self):
        import app.operators.io_operators  # noqa: F401  显式注册（独立子进程）
        from app.engine.registry import OperatorRegistry
        from tests.operator_test_utils import execute_operator

        with self.assertRaises(OutboundUrlError):
            execute_operator(
                OperatorRegistry.get("read_url"),
                {},
                {"url": "http://169.254.169.254/latest/meta-data"},
            )


if __name__ == "__main__":
    unittest.main()
