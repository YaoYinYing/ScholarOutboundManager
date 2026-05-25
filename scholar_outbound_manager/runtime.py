"""High-level helpers for preparing local runtime artifacts."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import XrayConfig
from scholar_outbound_manager.xray.runtime_config import build_runtime_config_for_candidate
from scholar_outbound_manager.xray.runtime_config import write_runtime_config


def prepare_candidate_runtime(
    candidate: CandidateProxy,
    xray_config: XrayConfig,
    config_name: str = "candidate_runtime.json",
) -> dict[str, object]:
    """Prepare and write one candidate runtime configuration without starting Xray."""
    runtime_config, local_socks_port = build_runtime_config_for_candidate(
        candidate=candidate,
        xray_config=xray_config,
    )
    runtime_dir = Path(xray_config.runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_config_path = runtime_dir / config_name
    write_runtime_config(runtime_config_path, runtime_config)
    return {
        "runtime_config_path": str(runtime_config_path),
        "local_socks_host": xray_config.local_socks_host,
        "local_socks_port": local_socks_port,
        "outbound_tag": "scholar-probe-out",
    }
