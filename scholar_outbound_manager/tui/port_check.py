"""Port availability checks for the TUI Route workbench."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class PortCheckResult:
    host: str
    port: int
    status: str
    message: str
    owner: str | None
    reusable: bool


def check_route_port(
    host: str,
    port: int,
    *,
    managed_service_name: str,
    runtime_metadata_path: Path | None = None,
) -> PortCheckResult:
    """Check whether one route port is usable for the managed sidecar."""

    if not host.strip():
        return PortCheckResult(host=host, port=port, status="invalid", message="Listen host must not be empty.", owner=None, reusable=False)
    if port <= 0 or port > 65535:
        return PortCheckResult(host=host, port=port, status="invalid", message="Listen port must be between 1 and 65535.", owner=None, reusable=False)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        return PortCheckResult(
            host=host,
            port=port,
            status="free",
            message="Port is free for the managed sidecar.",
            owner=None,
            reusable=True,
        )
    except PermissionError:
        return PortCheckResult(
            host=host,
            port=port,
            status="unknown",
            message="Port check could not bind due to local permission limits.",
            owner=None,
            reusable=False,
        )
    except OSError:
        managed_owner = _managed_owner_from_metadata(runtime_metadata_path, host=host, port=port, managed_service_name=managed_service_name)
        if managed_owner is not None:
            return PortCheckResult(
                host=host,
                port=port,
                status="occupied_by_managed_sidecar",
                message="Port is already occupied by the managed sidecar and can be reused.",
                owner=managed_owner,
                reusable=True,
            )
        return PortCheckResult(
            host=host,
            port=port,
            status="occupied_by_external_process",
            message="Port is occupied by another local process.",
            owner=None,
            reusable=False,
        )
    except Exception:
        return PortCheckResult(
            host=host,
            port=port,
            status="unknown",
            message="Port ownership could not be determined.",
            owner=None,
            reusable=False,
        )


def _managed_owner_from_metadata(
    runtime_metadata_path: Path | None,
    *,
    host: str,
    port: int,
    managed_service_name: str,
) -> str | None:
    if runtime_metadata_path is None or not runtime_metadata_path.exists():
        return None
    try:
        payload = json.loads(runtime_metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    payload_host = payload.get("listen_host")
    payload_port = payload.get("listen_port")
    if payload_host == host and payload_port == port:
        return managed_service_name
    plan = payload.get("plan")
    if isinstance(plan, dict):
        for entry in plan.get("entries", []):
            if not isinstance(entry, dict):
                continue
            if entry.get("listen_host") == host and entry.get("listen_port") == port:
                return managed_service_name
    return None


__all__ = ["PortCheckResult", "check_route_port"]
