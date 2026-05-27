"""Tests for Xray runtime configuration builders."""

from __future__ import annotations

import json

import pytest

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import XrayConfig
from scholar_outbound_manager.xray.runtime_config import build_local_socks_inbound
from scholar_outbound_manager.xray.runtime_config import build_runtime_config_for_candidate
from scholar_outbound_manager.xray.runtime_config import build_runtime_config_from_outbound
from scholar_outbound_manager.xray.runtime_config import write_runtime_config


def test_build_local_socks_inbound_uses_noauth() -> None:
    """Build a no-auth SOCKS inbound."""
    inbound = build_local_socks_inbound("127.0.0.1", 1080)

    assert inbound["protocol"] == "socks"
    assert inbound["settings"] == {"auth": "noauth", "udp": False}


def test_build_local_socks_inbound_requires_host() -> None:
    """Reject empty listen hosts."""
    with pytest.raises(ValueError, match="listen_host"):
        build_local_socks_inbound("", 1080)


def test_build_local_socks_inbound_requires_positive_port() -> None:
    """Reject non-positive listen ports."""
    with pytest.raises(ValueError, match="listen_port"):
        build_local_socks_inbound("127.0.0.1", 0)


def test_build_runtime_config_from_outbound_builds_sections() -> None:
    """Build a complete runtime config from one outbound."""
    config = build_runtime_config_from_outbound(
        outbound={"tag": "scholar-probe-out", "protocol": "vless"},
        listen_host="127.0.0.1",
        listen_port=1080,
    )

    assert config["inbounds"][0]["tag"] == "scholar-probe-socks-in"
    assert config["outbounds"][0]["tag"] == "scholar-probe-out"


def test_build_runtime_config_from_outbound_requires_tag() -> None:
    """Reject outbounds without a tag."""
    with pytest.raises(ValueError, match="tag"):
        build_runtime_config_from_outbound(
            outbound={"protocol": "vless"},
            listen_host="127.0.0.1",
            listen_port=1080,
        )


def test_build_runtime_config_for_candidate_uses_fixed_port() -> None:
    """Reuse the configured SOCKS port when it is positive."""
    config, port = build_runtime_config_for_candidate(
        candidate=_make_vless_candidate(),
        xray_config=_make_xray_config(local_socks_port=1081),
    )

    assert port == 1081
    assert config["inbounds"][0]["port"] == 1081


def test_build_runtime_config_for_candidate_allocates_free_port() -> None:
    """Allocate a positive local port when configured with zero."""
    from scholar_outbound_manager.xray import runtime_config as runtime_config_module

    original_find_free_tcp_port = runtime_config_module._find_free_tcp_port
    runtime_config_module._find_free_tcp_port = lambda host: 18080
    try:
        config, port = build_runtime_config_for_candidate(
            candidate=_make_vless_candidate(),
            xray_config=_make_xray_config(local_socks_port=0),
        )
    finally:
        runtime_config_module._find_free_tcp_port = original_find_free_tcp_port

    assert port == 18080
    assert config["inbounds"][0]["port"] == port


def test_build_runtime_config_for_candidate_rejects_negative_port() -> None:
    """Reject negative configured SOCKS ports."""
    with pytest.raises(ValueError, match="negative"):
        build_runtime_config_for_candidate(
            candidate=_make_vless_candidate(),
            xray_config=_make_xray_config(local_socks_port=-1),
        )


def test_build_runtime_config_for_trojan_candidate() -> None:
    """Build a runtime config for Trojan candidates."""
    config, _ = build_runtime_config_for_candidate(
        candidate=_make_trojan_candidate(),
        xray_config=_make_xray_config(local_socks_port=1081),
    )

    assert config["outbounds"][0]["protocol"] == "trojan"


def test_build_runtime_config_for_shadowsocks_candidate() -> None:
    """Build a runtime config for Shadowsocks candidates."""
    config, _ = build_runtime_config_for_candidate(
        candidate=_make_shadowsocks_candidate(),
        xray_config=_make_xray_config(local_socks_port=1081),
    )

    assert config["outbounds"][0]["protocol"] == "shadowsocks"


def test_build_runtime_config_for_vmess_candidate() -> None:
    """Build a runtime config for VMess candidates."""
    config, _ = build_runtime_config_for_candidate(
        candidate=_make_vmess_candidate(),
        xray_config=_make_xray_config(local_socks_port=1081),
    )

    assert config["outbounds"][0]["protocol"] == "vmess"


def test_build_runtime_config_for_hysteria2_candidate() -> None:
    """Build a runtime config for supported Hysteria2 candidates."""
    config, _ = build_runtime_config_for_candidate(
        candidate=_make_hysteria2_candidate(),
        xray_config=_make_xray_config(local_socks_port=1081),
    )

    assert config["outbounds"][0]["protocol"] == "hysteria"
    assert config["outbounds"][0]["settings"]["version"] == 2
    assert config["outbounds"][0]["streamSettings"]["network"] == "hysteria"


def test_runtime_config_does_not_expose_raw_uri() -> None:
    """Keep raw URI source material out of runtime configs."""
    config, _ = build_runtime_config_for_candidate(
        candidate=_make_vmess_candidate(),
        xray_config=_make_xray_config(local_socks_port=1081),
    )

    assert "vless://" not in json.dumps(config)


def test_write_runtime_config_persists_json(tmp_path) -> None:
    """Write a runtime config to disk as JSON."""
    path = tmp_path / "runtime.json"
    config, _ = build_runtime_config_for_candidate(
        candidate=_make_vless_candidate(),
        xray_config=_make_xray_config(local_socks_port=1081),
    )

    write_runtime_config(path, config)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["inbounds"][0]["port"] == 1081


def _make_candidate(**overrides: object) -> CandidateProxy:
    """Construct one baseline candidate for runtime config tests."""
    candidate_data: dict[str, object] = {
        "source_name": "fixture-source",
        "raw_name": "node",
        "protocol": "vless",
        "address": "example.invalid",
        "port": 443,
        "user_id": "00000000-0000-0000-0000-000000000000",
        "password": None,
        "encryption": "none",
        "flow": "xtls-rprx-vision",
        "network": "tcp",
        "security": "reality",
        "server_name": "www.cloudflare.com",
        "fingerprint": "chrome",
        "public_key": "PUBLIC_KEY_PLACEHOLDER",
        "short_id": "SHORT_ID_PLACEHOLDER",
        "path": "/ws",
        "host": "cdn.example.invalid",
        "extra": {},
        "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
        "supported": True,
    }
    candidate_data.update(overrides)
    return CandidateProxy(**candidate_data)


def _make_vless_candidate(**overrides: object) -> CandidateProxy:
    return _make_candidate(**overrides)


def _make_trojan_candidate(**overrides: object) -> CandidateProxy:
    return _make_candidate(
        protocol="trojan",
        user_id=None,
        password="PASSWORD_PLACEHOLDER",
        encryption=None,
        flow=None,
        security="tls",
        public_key=None,
        short_id=None,
        raw_uri=None,
        **overrides,
    )


def _make_shadowsocks_candidate(**overrides: object) -> CandidateProxy:
    return _make_candidate(
        protocol="shadowsocks",
        user_id=None,
        password="PASSWORD_PLACEHOLDER",
        encryption="aes-256-gcm",
        flow=None,
        security=None,
        public_key=None,
        short_id=None,
        raw_uri=None,
        **overrides,
    )


def _make_vmess_candidate(**overrides: object) -> CandidateProxy:
    return _make_candidate(
        protocol="vmess",
        encryption="auto",
        flow=None,
        security="tls",
        public_key=None,
        short_id=None,
        raw_uri=None,
        extra={"alter_id": 8},
        **overrides,
    )


def _make_hysteria2_candidate(**overrides: object) -> CandidateProxy:
    return _make_candidate(
        protocol="hysteria2",
        user_id=None,
        password="HY2_PASSWORD_PLACEHOLDER",
        encryption=None,
        flow=None,
        network=None,
        security="hysteria",
        server_name="hy2.example.invalid",
        fingerprint=None,
        public_key=None,
        short_id=None,
        alpn="h3,h2",
        raw_uri=None,
        address="hy2.example.invalid",
        extra={},
        **overrides,
    )


def _make_xray_config(local_socks_port: int) -> XrayConfig:
    """Construct one Xray config for runtime config tests."""
    return XrayConfig(
        binary_path="xray",
        runtime_dir="runtime",
        local_socks_host="127.0.0.1",
        local_socks_port=local_socks_port,
    )
