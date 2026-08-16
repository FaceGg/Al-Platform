"""Redacted notification receivers for isolated acceptance tests."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
import select
import socket
import socketserver
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

from tools.redaction import redact_text


_SENSITIVE_MARKERS = (
    "secret",
    "token",
    "password",
    "authorization",
    "api_key",
    "api-key",
    "apikey",
    "access_key",
    "access-key",
    "accesskey",
    "credential",
    "records",
    "predictions",
    "storage_uri",
    "traceback",
)
class NotificationReceiver:
    """Capture bounded, safe notification envelopes from local acceptance flows."""

    def __init__(self, max_events: int = 100, max_body_bytes: int = 65536):
        if max_events < 1 or max_body_bytes < 1:
            raise ValueError("max_events and max_body_bytes must be positive")
        self.events: list[dict[str, Any]] = []
        self.max_events = max_events
        self.max_body_bytes = max_body_bytes
        self._lock = threading.Lock()

    @staticmethod
    def _safe(value: Any, depth: int = 0) -> Any:
        if depth >= 16:
            return "[truncated]"
        if isinstance(value, dict):
            return {
                str(key): (
                    "[redacted]"
                    if any(marker in str(key).lower() for marker in _SENSITIVE_MARKERS)
                    else NotificationReceiver._safe(item, depth + 1)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [NotificationReceiver._safe(item, depth + 1) for item in value[:100]]
        if isinstance(value, str):
            return redact_text(value)
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return "[unsupported]"

    def _record(self, path: str, payload: Any) -> None:
        event = {"path": urlsplit(path).path, "payload": self._safe(payload)}
        with self._lock:
            self.events.append(event)
            overflow = len(self.events) - self.max_events
            if overflow > 0:
                del self.events[:overflow]

    def assert_event_type(self, event_type: str) -> None:
        with self._lock:
            found = any(
                isinstance(event["payload"], dict)
                and event["payload"].get("event_type") == event_type
                for event in self.events
            )
        if not found:
            raise AssertionError(f"notification event type not received: {event_type}")

    @contextmanager
    def running(self) -> Iterator[str]:
        """Run a temporary loopback server and yield its receiver endpoint."""
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 (HTTP handler protocol)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length < 0:
                    self.send_response(400)
                    self.end_headers()
                    return
                if length > owner.max_body_bytes:
                    self.send_response(413)
                    self.end_headers()
                    return
                payload = self.rfile.read(length)
                try:
                    parsed = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    parsed = {"invalid": True}
                owner._record(self.path, parsed)
                self.send_response(202)
                self.end_headers()

            def log_message(self, *_args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/events"
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()


@dataclass(frozen=True)
class AcceptanceReceiverEndpoints:
    """Bound addresses for the TLS delivery endpoint and read-only event view."""

    https_host: str
    https_port: int
    events_host: str
    events_port: int

    @property
    def events_url(self) -> str:
        return f"http://{self.events_host}:{self.events_port}/events"


@dataclass(frozen=True)
class ProxyEndpoint:
    host: str
    port: int


class AcceptanceNotificationReceiver:
    """Serve one TLS delivery endpoint plus an isolated read-only event endpoint."""

    def __init__(
        self,
        certificate: Path,
        private_key: Path,
        *,
        host: str = "0.0.0.0",
        https_port: int = 443,
        events_port: int = 8080,
        max_events: int = 100,
        max_body_bytes: int = 65536,
    ) -> None:
        self.certificate = Path(certificate)
        self.private_key = Path(private_key)
        self.host = host
        self.https_port = https_port
        self.events_port = events_port
        self._receiver = NotificationReceiver(
            max_events=max_events,
            max_body_bytes=max_body_bytes,
        )

    @property
    def events(self) -> list[dict[str, Any]]:
        return self._receiver.events

    def _post_handler(self, handler: BaseHTTPRequestHandler) -> None:
        try:
            length = int(handler.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 0:
            handler.send_response(400)
            handler.end_headers()
            return
        if length > self._receiver.max_body_bytes:
            handler.send_response(413)
            handler.end_headers()
            return
        raw_payload = handler.rfile.read(length)
        try:
            payload = json.loads(raw_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"invalid": True}
        self._receiver._record(handler.path, payload)
        response = (
            {"errcode": 0}
            if urlsplit(handler.path).path.startswith("/cgi-bin/")
            else {"status": "accepted"}
        )
        encoded = json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(encoded)))
        handler.end_headers()
        handler.wfile.write(encoded)

    def _events_handler(self, handler: BaseHTTPRequestHandler) -> None:
        if urlsplit(handler.path).path != "/events":
            handler.send_response(404)
            handler.end_headers()
            return
        with self._receiver._lock:
            payload = {"events": list(self._receiver.events)}
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(encoded)))
        handler.end_headers()
        handler.wfile.write(encoded)

    @contextmanager
    def running(self) -> Iterator[AcceptanceReceiverEndpoints]:
        owner = self

        class DeliveryHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 (HTTP handler protocol)
                owner._post_handler(self)

            def log_message(self, *_args: object) -> None:
                return

        class EventsHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (HTTP handler protocol)
                owner._events_handler(self)

            def log_message(self, *_args: object) -> None:
                return

        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.load_cert_chain(str(self.certificate), str(self.private_key))
        delivery_server = ThreadingHTTPServer((self.host, self.https_port), DeliveryHandler)
        delivery_server.socket = tls_context.wrap_socket(
            delivery_server.socket,
            server_side=True,
        )
        events_server = ThreadingHTTPServer((self.host, self.events_port), EventsHandler)
        delivery_thread = threading.Thread(
            target=delivery_server.serve_forever,
            daemon=True,
        )
        events_thread = threading.Thread(
            target=events_server.serve_forever,
            daemon=True,
        )
        delivery_thread.start()
        events_thread.start()
        try:
            delivery_host, delivery_port = delivery_server.server_address[:2]
            events_host, events_port = events_server.server_address[:2]
            if delivery_host in {"0.0.0.0", "::"}:
                delivery_host = "127.0.0.1"
            if events_host in {"0.0.0.0", "::"}:
                events_host = "127.0.0.1"
            yield AcceptanceReceiverEndpoints(
                str(delivery_host),
                int(delivery_port),
                str(events_host),
                int(events_port),
            )
        finally:
            delivery_server.shutdown()
            events_server.shutdown()
            delivery_thread.join(timeout=3)
            events_thread.join(timeout=3)
            delivery_server.server_close()
            events_server.server_close()

    def serve_forever(self) -> None:
        with self.running():
            threading.Event().wait()


class ControlledConnectProxy:
    """Tunnel only a declared official host to the isolated TLS receiver."""

    def __init__(
        self,
        *,
        target_host: str,
        target_port: int,
        allowed_host: str,
        host: str = "0.0.0.0",
        listen_port: int = 3128,
    ) -> None:
        self.target_host = target_host
        self.target_port = target_port
        self.allowed_host = allowed_host.rstrip(".").casefold()
        self.host = host
        self.listen_port = listen_port

    def _accept_target(self, request_line: bytes) -> bool:
        try:
            method, authority, version = request_line.decode("ascii").strip().split(" ")
            host, separator, port = authority.rpartition(":")
            return (
                method == "CONNECT"
                and version.startswith("HTTP/")
                and separator == ":"
                and host.rstrip(".").casefold() == self.allowed_host
                and port == "443"
            )
        except (UnicodeDecodeError, ValueError):
            return False

    @staticmethod
    def _discard_headers(reader: Any) -> bool:
        for _ in range(100):
            line = reader.readline(8192)
            if not line or line == b"\r\n":
                return line == b"\r\n"
            if len(line) >= 8192:
                return False
        return False

    @staticmethod
    def _relay(client: socket.socket, upstream: socket.socket) -> None:
        sockets = (client, upstream)
        try:
            while True:
                readable, _, _ = select.select(sockets, (), (), 1.0)
                for source in readable:
                    payload = source.recv(65536)
                    if not payload:
                        return
                    (upstream if source is client else client).sendall(payload)
        finally:
            upstream.close()

    @contextmanager
    def running(self) -> Iterator[ProxyEndpoint]:
        owner = self

        class ProxyServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        class ProxyHandler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                request_line = self.rfile.readline(8192)
                if not owner._accept_target(request_line) or not owner._discard_headers(self.rfile):
                    self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                    self.wfile.flush()
                    return
                try:
                    upstream = socket.create_connection(
                        (owner.target_host, owner.target_port),
                        timeout=10,
                    )
                except OSError:
                    self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                    self.wfile.flush()
                    return
                self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self.wfile.flush()
                owner._relay(self.connection, upstream)

        server = ProxyServer((self.host, self.listen_port), ProxyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address[:2]
            if host in {"0.0.0.0", "::"}:
                host = "127.0.0.1"
            yield ProxyEndpoint(str(host), int(port))
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

    def serve_forever(self) -> None:
        with self.running():
            threading.Event().wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve")
    serve.add_argument("--https-port", type=int, default=443)
    serve.add_argument("--events-port", type=int, default=8080)
    serve.add_argument("--certificate", type=Path, required=True)
    serve.add_argument("--private-key", type=Path, required=True)
    proxy = subparsers.add_parser("proxy")
    proxy.add_argument("--listen-port", type=int, default=3128)
    proxy.add_argument("--target-host", required=True)
    proxy.add_argument("--target-port", type=int, default=443)
    proxy.add_argument("--allowed-host", required=True)
    args = parser.parse_args(argv)
    if args.command == "serve":
        AcceptanceNotificationReceiver(
            args.certificate,
            args.private_key,
            https_port=args.https_port,
            events_port=args.events_port,
        ).serve_forever()
    else:
        ControlledConnectProxy(
            target_host=args.target_host,
            target_port=args.target_port,
            allowed_host=args.allowed_host,
            listen_port=args.listen_port,
        ).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
