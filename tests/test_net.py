"""Tests for TCP endpoint readiness helpers."""

from __future__ import annotations

import socket
import threading

import pytest

from scholar_outbound_manager.net import wait_for_tcp_endpoint


def test_wait_for_tcp_endpoint_returns_true_for_listening_server(capsys) -> None:
    """Return True when a local TCP server accepts connections."""
    with _listening_socket() as server_socket:
        host, port = server_socket.getsockname()
        ready = wait_for_tcp_endpoint(host, port, 0.5)
    captured = capsys.readouterr()

    assert ready is True
    assert captured.out == ""
    assert captured.err == ""


def test_wait_for_tcp_endpoint_returns_false_for_closed_port() -> None:
    """Return False when the port does not become ready in time."""
    port = _find_unused_local_port()

    ready = wait_for_tcp_endpoint("127.0.0.1", port, 0.1, interval_seconds=0.02)

    assert ready is False


def test_wait_for_tcp_endpoint_rejects_empty_host() -> None:
    """Reject empty hosts."""
    with pytest.raises(ValueError, match="host"):
        wait_for_tcp_endpoint("", 1080, 1.0)


def test_wait_for_tcp_endpoint_rejects_non_positive_port() -> None:
    """Reject invalid ports."""
    with pytest.raises(ValueError, match="port"):
        wait_for_tcp_endpoint("127.0.0.1", 0, 1.0)


def test_wait_for_tcp_endpoint_rejects_non_positive_timeout() -> None:
    """Reject invalid timeouts."""
    with pytest.raises(ValueError, match="timeout_seconds"):
        wait_for_tcp_endpoint("127.0.0.1", 1080, 0)


def test_wait_for_tcp_endpoint_rejects_non_positive_interval() -> None:
    """Reject invalid polling intervals."""
    with pytest.raises(ValueError, match="interval_seconds"):
        wait_for_tcp_endpoint("127.0.0.1", 1080, 1.0, interval_seconds=0)


class _listening_socket:
    """Context manager for a temporary local listening socket."""

    def __enter__(self) -> socket.socket:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self._thread = threading.Thread(target=self._accept_once, daemon=True)
        self._thread.start()
        return self._sock

    def __exit__(self, exc_type, exc, tb) -> None:
        self._sock.close()
        self._thread.join(timeout=1.0)

    def _accept_once(self) -> None:
        try:
            conn, _ = self._sock.accept()
            conn.close()
        except OSError:
            pass


def _find_unused_local_port() -> int:
    """Reserve and release one local port for readiness-negative tests."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
