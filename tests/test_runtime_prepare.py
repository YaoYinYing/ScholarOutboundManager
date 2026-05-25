"""Tests for high-level runtime preparation helpers."""

from __future__ import annotations

import json
from pathlib import Path

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import XrayConfig
from scholar_outbound_manager.runtime import prepare_candidate_runtime


def test_prepare_candidate_runtime_writes_config(tmp_path) -> None:
    """Write one runtime config file for a candidate."""
    runtime_dir = tmp_path / "runtime"
    summary = prepare_candidate_runtime(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(runtime_dir),
    )

    assert (runtime_dir / "candidate_runtime.json").exists()
    assert summary["runtime_config_path"] == str(runtime_dir / "candidate_runtime.json")


def test_prepare_candidate_runtime_returns_summary_fields(tmp_path) -> None:
    """Return the expected runtime preparation summary fields."""
    runtime_dir = tmp_path / "runtime"
    summary = prepare_candidate_runtime(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(runtime_dir),
    )

    assert summary["local_socks_host"] == "127.0.0.1"
    assert summary["local_socks_port"] == 1081
    assert summary["outbound_tag"] == "scholar-probe-out"


def test_prepare_candidate_runtime_creates_runtime_dir(tmp_path) -> None:
    """Create the runtime directory when it does not exist."""
    runtime_dir = tmp_path / "missing" / "runtime"
    prepare_candidate_runtime(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(runtime_dir),
    )

    assert runtime_dir.exists()


def test_prepare_candidate_runtime_summary_excludes_raw_uri(tmp_path) -> None:
    """Keep raw URI content out of the returned summary."""
    runtime_dir = tmp_path / "runtime"
    summary = prepare_candidate_runtime(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(runtime_dir),
    )

    assert "vless://" not in json.dumps(summary)


def test_prepare_candidate_runtime_written_config_excludes_raw_uri(tmp_path) -> None:
    """Keep raw URI content out of the written config."""
    runtime_dir = tmp_path / "runtime"
    summary = prepare_candidate_runtime(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(runtime_dir),
    )

    rendered = Path(summary["runtime_config_path"]).read_text(encoding="utf-8")
    assert "vless://" not in rendered


def test_prepare_candidate_runtime_supports_custom_outbound_tag(tmp_path) -> None:
    """Allow callers to override the outbound tag."""
    runtime_dir = tmp_path / "runtime"
    summary = prepare_candidate_runtime(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(runtime_dir),
        outbound_tag="custom-outbound",
    )

    rendered = Path(summary["runtime_config_path"]).read_text(encoding="utf-8")
    assert summary["outbound_tag"] == "custom-outbound"
    assert '"tag": "custom-outbound"' in rendered


def test_prepare_candidate_runtime_supports_custom_inbound_tag(tmp_path) -> None:
    """Allow callers to override the inbound tag."""
    runtime_dir = tmp_path / "runtime"
    summary = prepare_candidate_runtime(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(runtime_dir),
        inbound_tag="custom-inbound",
    )

    rendered = Path(summary["runtime_config_path"]).read_text(encoding="utf-8")
    assert summary["inbound_tag"] == "custom-inbound"
    assert '"tag": "custom-inbound"' in rendered


def test_prepare_candidate_runtime_summary_excludes_sensitive_fields(tmp_path) -> None:
    """Keep sensitive candidate material out of the runtime summary."""
    runtime_dir = tmp_path / "runtime"
    summary = prepare_candidate_runtime(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(runtime_dir),
    )

    rendered = json.dumps(summary)
    assert "vless://" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered


def _make_candidate() -> CandidateProxy:
    """Construct one baseline candidate for runtime preparation tests."""
    return CandidateProxy(
        source_name="fixture-source",
        raw_name="US Scholar IPv4",
        protocol="vless",
        address="example.invalid",
        port=443,
        user_id="00000000-0000-0000-0000-000000000000",
        encryption="none",
        flow="xtls-rprx-vision",
        network="tcp",
        security="reality",
        server_name="www.cloudflare.com",
        fingerprint="chrome",
        public_key="PUBLIC_KEY_PLACEHOLDER",
        short_id="SHORT_ID_PLACEHOLDER",
        raw_uri="vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
        supported=True,
    )


def _make_xray_config(runtime_dir) -> XrayConfig:
    """Construct one Xray config for runtime preparation tests."""
    return XrayConfig(
        binary_path="xray",
        runtime_dir=str(runtime_dir),
        local_socks_host="127.0.0.1",
        local_socks_port=1081,
    )
