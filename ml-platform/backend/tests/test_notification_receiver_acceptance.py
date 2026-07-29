"""TLS receiver and CONNECT tunnel contracts for isolated Week 12 acceptance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import socket
import ssl
import tempfile
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from tools.notification_receiver import AcceptanceNotificationReceiver, ControlledConnectProxy


def _write_test_certificate(directory: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "qyapi.weixin.qq.com")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(minutes=5))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("qyapi.weixin.qq.com"),
                    x509.DNSName("notification-receiver"),
                ],
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    certificate_path = directory / "receiver-cert.pem"
    private_key_path = directory / "receiver-key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private_key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ),
    )
    return certificate_path, private_key_path


def _read_http_response(connection: ssl.SSLSocket) -> bytes:
    response = bytearray()
    while b"\r\n\r\n" not in response:
        chunk = connection.recv(4096)
        if not chunk:
            return bytes(response)
        response.extend(chunk)
    headers, body = bytes(response).split(b"\r\n\r\n", 1)
    for line in headers.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
            while len(body) < length:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                body += chunk
            break
    return headers + b"\r\n\r\n" + body


class ControlledReceiverAcceptanceTests(unittest.TestCase):
    def test_wecom_tls_tunnel_preserves_official_hostname_and_records_safe_event(self):
        with tempfile.TemporaryDirectory() as directory:
            certificate, private_key = _write_test_certificate(Path(directory))
            receiver = AcceptanceNotificationReceiver(certificate, private_key)
            with receiver.running() as endpoints:
                proxy = ControlledConnectProxy(
                    target_host=endpoints.https_host,
                    target_port=endpoints.https_port,
                    allowed_host="qyapi.weixin.qq.com",
                )
                with proxy.running() as proxy_endpoint:
                    connection = socket.create_connection(
                        (proxy_endpoint.host, proxy_endpoint.port),
                        timeout=3,
                    )
                    connection.sendall(
                        b"CONNECT qyapi.weixin.qq.com:443 HTTP/1.1\r\n"
                        b"Host: qyapi.weixin.qq.com:443\r\n\r\n",
                    )
                    self.assertIn(b"200", connection.recv(1024))
                    context = ssl.create_default_context(cafile=str(certificate))
                    tls = context.wrap_socket(connection, server_hostname="qyapi.weixin.qq.com")
                    payload = b'{"msgtype":"text","text":{"content":"rollout.completed"}}'
                    tls.sendall(
                        b"POST /cgi-bin/webhook/send?key=controlled HTTP/1.1\r\n"
                        b"Host: qyapi.weixin.qq.com\r\n"
                        b"Content-Type: application/json\r\n"
                        + f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
                        + payload,
                    )
                    response = _read_http_response(tls)
                    tls.close()

        self.assertIn(b"200", response)
        self.assertIn(b'"errcode":0', response)
        self.assertEqual(receiver.events[0]["payload"]["msgtype"], "text")

    def test_tunnel_rejects_non_wecom_connect_targets(self):
        proxy = ControlledConnectProxy(
            target_host="127.0.0.1",
            target_port=443,
            allowed_host="qyapi.weixin.qq.com",
        )
        with proxy.running() as endpoint:
            connection = socket.create_connection((endpoint.host, endpoint.port), timeout=3)
            connection.sendall(
                b"CONNECT metadata.google.internal:443 HTTP/1.1\r\n"
                b"Host: metadata.google.internal:443\r\n\r\n",
            )
            response = connection.recv(1024)
            connection.close()

        self.assertIn(b"403", response)


if __name__ == "__main__":
    unittest.main()
