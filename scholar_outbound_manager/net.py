"""Network readiness helpers."""

from __future__ import annotations

import socket
import time


def wait_for_tcp_endpoint(
    host: str,
    port: int,
    timeout_seconds: float,
    interval_seconds: float = 0.05,
) -> bool:
    """Wait until one TCP endpoint accepts connections or a timeout expires."""
    if not host:
        raise ValueError("host must not be empty.")
    if port <= 0:
        raise ValueError("port must be greater than 0.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0.")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than 0.")

    deadline = time.monotonic() + timeout_seconds
    connect_timeout = min(interval_seconds, max(timeout_seconds, 0.001))
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=connect_timeout):
                return True
        except (ConnectionRefusedError, OSError, TimeoutError):
            time.sleep(interval_seconds)
    return False
