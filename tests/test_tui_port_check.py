"""Tests for Route port checks."""

from __future__ import annotations

import json
import socket
from pathlib import Path

from scholar_outbound_manager.tui.port_check import check_route_port


def test_invalid_port_rejected() -> None:
    result = check_route_port("127.0.0.1", 0, managed_service_name="svc")

    assert result.status == "invalid"


def test_free_port_returns_free() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        host, port = sock.getsockname()
    result = check_route_port(host, port, managed_service_name="svc")

    assert result.status == "free"
    assert result.reusable is True


def test_external_occupied_port_returns_external_process() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        host, port = sock.getsockname()
        result = check_route_port(host, port, managed_service_name="svc")

    assert result.status == "occupied_by_external_process"
    assert result.reusable is False


def test_managed_sidecar_metadata_marks_port_reusable(tmp_path: Path) -> None:
    metadata_path = tmp_path / "managed.json"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        host, port = sock.getsockname()
        metadata_path.write_text(
            json.dumps({"listen_host": host, "listen_port": port}),
            encoding="utf-8",
        )
        result = check_route_port(
            host,
            port,
            managed_service_name="scholar-outbound-sidecar.service",
            runtime_metadata_path=metadata_path,
        )

    assert result.status == "occupied_by_managed_sidecar"
    assert result.reusable is True
    assert result.owner == "scholar-outbound-sidecar.service"
