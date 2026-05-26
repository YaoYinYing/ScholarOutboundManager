"""Builders for local Xray runtime configurations."""

from __future__ import annotations

import socket
from pathlib import Path

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import XrayConfig
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.xray.outbound_builder import build_xray_outbound


def build_local_socks_inbound(
    listen_host: str,
    listen_port: int,
    tag: str = "scholar-probe-socks-in",
) -> dict[str, object]:
    """Build one local SOCKS inbound for isolated probing."""
    if not listen_host:
        raise ValueError("listen_host must not be empty.")
    if listen_port <= 0:
        raise ValueError("listen_port must be greater than 0.")
    return {
        "tag": tag,
        "listen": listen_host,
        "port": listen_port,
        "protocol": "socks",
        "settings": {
            "auth": "noauth",
            "udp": False,
        },
    }


def build_runtime_config_from_outbound(
    outbound: dict[str, object],
    listen_host: str,
    listen_port: int,
    inbound_tag: str = "scholar-probe-socks-in",
) -> dict[str, object]:
    """Build one complete Xray runtime configuration from a generated outbound."""
    outbound_tag = outbound.get("tag")
    if not isinstance(outbound_tag, str) or not outbound_tag:
        raise ValueError("Runtime outbound must include a non-empty tag.")

    return {
        "log": {
            "loglevel": "warning",
        },
        "inbounds": [
            build_local_socks_inbound(
                listen_host=listen_host,
                listen_port=listen_port,
                tag=inbound_tag,
            )
        ],
        "outbounds": [outbound],
        "routing": {
            "rules": [
                {
                    "type": "field",
                    "inboundTag": [inbound_tag],
                    "outboundTag": outbound_tag,
                }
            ]
        },
    }


def build_runtime_config_for_candidate(
    candidate: CandidateProxy,
    xray_config: XrayConfig,
    outbound_tag: str = "scholar-probe-out",
    inbound_tag: str = "scholar-probe-socks-in",
) -> tuple[dict[str, object], int]:
    """Build a runtime configuration and selected local SOCKS port for one candidate."""
    if xray_config.local_socks_port < 0:
        raise ValueError("local_socks_port must not be negative.")

    listen_port = xray_config.local_socks_port
    if listen_port == 0:
        listen_port = _find_free_tcp_port(xray_config.local_socks_host)

    outbound = build_xray_outbound(candidate, outbound_tag)
    runtime_config = build_runtime_config_from_outbound(
        outbound=outbound,
        listen_host=xray_config.local_socks_host,
        listen_port=listen_port,
        inbound_tag=inbound_tag,
    )
    return runtime_config, listen_port


def write_runtime_config(path: str | Path, config: dict[str, object]) -> None:
    """Write a runtime configuration atomically as JSON."""
    atomic_write_json(path, config)


def _find_free_tcp_port(host: str) -> int:
    """Allocate one currently free TCP port on the requested host."""
    if not host:
        raise ValueError("listen_host must not be empty.")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        port = sock.getsockname()[1]
    return int(port)
