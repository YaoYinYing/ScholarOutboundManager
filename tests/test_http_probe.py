"""Tests for low-level HTTP probing through SOCKS5."""

from __future__ import annotations

import socket
import socketserver
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from select import select
from typing import Iterator

from scholar_outbound_manager.probe.http_probe import HttpProbeTarget
from scholar_outbound_manager.probe.http_probe import SocksEndpoint
from scholar_outbound_manager.probe.http_probe import probe_http_via_socks


class _ProbeHTTPRequestHandler(BaseHTTPRequestHandler):
    """Serve deterministic responses for probe tests."""

    body = "hello through socks"
    status_code = 200
    content_type = "text/html; charset=utf-8"
    delay_seconds = 0.0

    def do_GET(self) -> None:  # noqa: N802
        """Handle one GET request."""
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        body = self.body.encode("utf-8")
        self.send_response(self.status_code)
        self.send_header("Content-Type", self.content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Suppress test server logging."""
        del format, args


class _ThreadingTestHTTPServer(ThreadingHTTPServer):
    """HTTP server with `allow_reuse_address` enabled for tests."""

    allow_reuse_address = True


class _ConfigurableSocksServer(socketserver.ThreadingTCPServer):
    """SOCKS5 server with configurable handshake behavior for tests."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        method: int = 0x00,
        reply_code: int = 0x00,
        handshake_delay: float = 0.0,
    ) -> None:
        self.method = method
        self.reply_code = reply_code
        self.handshake_delay = handshake_delay
        super().__init__(server_address, _SocksProxyHandler)


class _SocksProxyHandler(socketserver.BaseRequestHandler):
    """Handle one SOCKS5 client connection."""

    def handle(self) -> None:
        """Perform the SOCKS5 handshake and relay data."""
        try:
            self.request.settimeout(1.0)
            if self.server.handshake_delay:
                time.sleep(self.server.handshake_delay)

            greeting_head = _recv_exact(self.request, 2)
            version = greeting_head[0]
            nmethods = greeting_head[1]
            _recv_exact(self.request, nmethods)
            if version != 0x05:
                return
            self.request.sendall(bytes([0x05, self.server.method]))
            if self.server.method != 0x00:
                return

            request_head = _recv_exact(self.request, 4)
            atyp = request_head[3]
            host = _read_address(self.request, atyp)
            port = int.from_bytes(_recv_exact(self.request, 2), "big")
            if self.server.reply_code != 0x00:
                self.request.sendall(b"\x05" + bytes([self.server.reply_code]) + b"\x00\x01\x00\x00\x00\x00\x00\x00")
                return

            upstream = socket.create_connection((host, port), timeout=1.0)
            upstream.settimeout(1.0)
            try:
                self.request.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
                _relay_bidirectional(self.request, upstream)
            finally:
                upstream.close()
        except (ConnectionError, OSError):
            return


def test_probe_http_via_socks_returns_200_and_body(capsys) -> None:
    """Probe a local HTTP server through a fake SOCKS5 proxy."""
    with _http_server() as http_url:
        with _socks_server() as socks:
            response = probe_http_via_socks(
                target=HttpProbeTarget(url=http_url),
                socks=socks,
                timeout_seconds=1.0,
            )

    captured = capsys.readouterr()
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert "hello through socks" in response.body_prefix
    assert response.error is None
    assert captured.out == ""
    assert captured.err == ""


def test_probe_http_via_socks_rejects_unsupported_scheme() -> None:
    """Return an error for unsupported URL schemes."""
    response = probe_http_via_socks(
        target=HttpProbeTarget(url="ftp://example.invalid/resource"),
        socks=SocksEndpoint(host="127.0.0.1", port=1080),
        timeout_seconds=1.0,
    )

    assert response.error is not None
    assert response.status_code is None


def test_probe_http_via_socks_rejects_empty_socks_host() -> None:
    """Return an error for empty SOCKS hosts."""
    response = probe_http_via_socks(
        target=HttpProbeTarget(url="http://example.invalid"),
        socks=SocksEndpoint(host="", port=1080),
        timeout_seconds=1.0,
    )

    assert response.error is not None


def test_probe_http_via_socks_rejects_non_positive_socks_port() -> None:
    """Return an error for invalid SOCKS ports."""
    response = probe_http_via_socks(
        target=HttpProbeTarget(url="http://example.invalid"),
        socks=SocksEndpoint(host="127.0.0.1", port=0),
        timeout_seconds=1.0,
    )

    assert response.error is not None


def test_probe_http_via_socks_rejects_non_positive_timeout() -> None:
    """Return an error for non-positive timeouts."""
    response = probe_http_via_socks(
        target=HttpProbeTarget(url="http://example.invalid"),
        socks=SocksEndpoint(host="127.0.0.1", port=1080),
        timeout_seconds=0,
    )

    assert response.error is not None


def test_probe_http_via_socks_limits_body_prefix_bytes() -> None:
    """Limit the response body prefix to the requested byte count."""
    with _http_server(body="abcdefghij") as http_url:
        with _socks_server() as socks:
            response = probe_http_via_socks(
                target=HttpProbeTarget(url=http_url, max_body_bytes=4),
                socks=socks,
                timeout_seconds=1.0,
            )

    assert response.body_prefix == "abcd"


def test_probe_http_via_socks_rejects_non_noauth_method() -> None:
    """Return an error when the SOCKS server rejects no-auth."""
    with _http_server() as http_url:
        with _socks_server(method=0x02) as socks:
            response = probe_http_via_socks(
                target=HttpProbeTarget(url=http_url),
                socks=socks,
                timeout_seconds=1.0,
            )

    assert response.error is not None
    assert "no-auth" in response.error


def test_probe_http_via_socks_rejects_failed_reply_code() -> None:
    """Return an error when the SOCKS server rejects CONNECT."""
    with _http_server() as http_url:
        with _socks_server(reply_code=0x05) as socks:
            response = probe_http_via_socks(
                target=HttpProbeTarget(url=http_url),
                socks=socks,
                timeout_seconds=1.0,
            )

    assert response.error is not None
    assert "reply code" in response.error


def test_probe_http_via_socks_handles_missing_socks_server() -> None:
    """Return an error when the SOCKS server is not reachable."""
    unused_port = _find_unused_local_port()
    response = probe_http_via_socks(
        target=HttpProbeTarget(url="http://127.0.0.1:1"),
        socks=SocksEndpoint(host="127.0.0.1", port=unused_port),
        timeout_seconds=0.2,
    )

    assert response.error is not None
    assert response.timed_out is False


def test_probe_http_via_socks_reports_timeout() -> None:
    """Return a timed-out response instead of raising."""
    with _http_server(delay_seconds=0.5) as http_url:
        with _socks_server() as socks:
            response = probe_http_via_socks(
                target=HttpProbeTarget(url=http_url),
                socks=socks,
                timeout_seconds=0.1,
            )

    assert response.timed_out is True
    assert response.error is not None


def test_probe_http_via_socks_returns_http_404() -> None:
    """Treat HTTP 404 as a valid transport response."""
    with _http_server(status_code=404, body="missing") as http_url:
        with _socks_server() as socks:
            response = probe_http_via_socks(
                target=HttpProbeTarget(url=http_url),
                socks=socks,
                timeout_seconds=1.0,
            )

    assert response.status_code == 404
    assert response.error is None


def test_probe_http_via_socks_rejects_missing_url_host() -> None:
    """Return an error when the URL host is missing."""
    response = probe_http_via_socks(
        target=HttpProbeTarget(url="http:///missing-host"),
        socks=SocksEndpoint(host="127.0.0.1", port=1080),
        timeout_seconds=1.0,
    )

    assert response.error is not None


def test_probe_http_via_socks_reports_ssl_error_against_plain_http_server() -> None:
    """Return an SSL error when HTTPS is tunneled to a non-TLS target."""
    with _http_server() as http_url:
        https_url = http_url.replace("http://", "https://")
        with _socks_server() as socks:
            response = probe_http_via_socks(
                target=HttpProbeTarget(url=https_url),
                socks=socks,
                timeout_seconds=1.0,
            )

    assert response.error is not None
    assert "SSL error" in response.error


def test_probe_http_via_socks_response_has_no_raw_uri_field() -> None:
    """Keep raw URI material out of the response model."""
    response = probe_http_via_socks(
        target=HttpProbeTarget(url="http://example.invalid"),
        socks=SocksEndpoint(host="", port=1080),
        timeout_seconds=1.0,
    )

    assert "raw_uri" not in HttpProbeTarget.__annotations__
    assert "raw_uri" not in type(response).__annotations__


@contextmanager
def _http_server(
    *,
    body: str = "hello through socks",
    status_code: int = 200,
    content_type: str = "text/html; charset=utf-8",
    delay_seconds: float = 0.0,
) -> Iterator[str]:
    """Run one local HTTP server for the duration of a test."""
    handler_class = type(
        "ConfiguredProbeHTTPRequestHandler",
        (_ProbeHTTPRequestHandler,),
        {
            "body": body,
            "status_code": status_code,
            "content_type": content_type,
            "delay_seconds": delay_seconds,
        },
    )
    server = _ThreadingTestHTTPServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/resource"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)


@contextmanager
def _socks_server(
    *,
    method: int = 0x00,
    reply_code: int = 0x00,
    handshake_delay: float = 0.0,
) -> Iterator[SocksEndpoint]:
    """Run one local fake SOCKS5 server for the duration of a test."""
    server = _ConfigurableSocksServer(
        ("127.0.0.1", 0),
        method=method,
        reply_code=reply_code,
        handshake_delay=handshake_delay,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield SocksEndpoint(host=host, port=port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    """Receive exactly the requested number of bytes."""
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise ConnectionError("peer closed connection")
        chunks.extend(chunk)
    return bytes(chunks)


def _find_unused_local_port() -> int:
    """Reserve and release one local port for negative-connect tests."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_address(sock: socket.socket, atyp: int) -> str:
    """Read one SOCKS destination address."""
    if atyp == 0x03:
        length = _recv_exact(sock, 1)[0]
        return _recv_exact(sock, length).decode("idna")
    if atyp == 0x01:
        return socket.inet_ntoa(_recv_exact(sock, 4))
    if atyp == 0x04:
        return socket.inet_ntop(socket.AF_INET6, _recv_exact(sock, 16))
    raise ConnectionError("unsupported atyp")


def _relay_bidirectional(client: socket.socket, upstream: socket.socket) -> None:
    """Relay bytes between the client and upstream sockets until closure."""
    sockets = [client, upstream]
    while sockets:
        readable, _, _ = select(sockets, [], [], 1.0)
        if not readable:
            continue
        for current in readable:
            try:
                data = current.recv(4096)
            except OSError:
                data = b""
            if not data:
                if current in sockets:
                    sockets.remove(current)
                try:
                    if current is client:
                        upstream.shutdown(socket.SHUT_WR)
                    else:
                        client.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                continue
            destination = upstream if current is client else client
            destination.sendall(data)
