"""Tests for structured Xray outbound specifications."""

from __future__ import annotations

import pytest

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.xray.spec import HysteriaProtocolSpec
from scholar_outbound_manager.xray.spec import ShadowsocksProtocolSpec
from scholar_outbound_manager.xray.spec import TrojanProtocolSpec
from scholar_outbound_manager.xray.spec import VlessProtocolSpec
from scholar_outbound_manager.xray.spec import VmessProtocolSpec
from scholar_outbound_manager.xray.spec_builder import build_hysteria2_spec
from scholar_outbound_manager.xray.spec_builder import build_shadowsocks_spec
from scholar_outbound_manager.xray.spec_builder import build_trojan_spec
from scholar_outbound_manager.xray.spec_builder import build_vless_spec
from scholar_outbound_manager.xray.spec_builder import build_vmess_spec
from scholar_outbound_manager.xray.spec_builder import build_xray_outbound_spec


def test_build_hysteria2_spec() -> None:
    """Build a Hysteria2 candidate into a normalized Xray spec."""
    spec = build_hysteria2_spec(_make_hysteria2_candidate(), "google-scholar-node-001")

    assert spec.protocol == "hysteria"
    assert isinstance(spec.protocol_spec, HysteriaProtocolSpec)
    assert spec.protocol_spec.endpoint.address == "hy2.example.invalid"
    assert spec.protocol_spec.endpoint.port == 443
    assert spec.protocol_spec.version == 2
    assert spec.transport.network == "hysteria"
    assert spec.transport.hysteria is not None
    assert spec.transport.hysteria.version == 2
    assert spec.transport.hysteria.auth == "HY2_PASSWORD_PLACEHOLDER"
    assert spec.tls is not None
    assert spec.tls.enabled is True
    assert spec.tls.server_name == "hy2.example.invalid"
    assert spec.tls.allow_insecure is True


def test_build_hysteria2_spec_falls_back_to_address_for_server_name() -> None:
    """Fallback to endpoint address when Hysteria2 omits SNI."""
    spec = build_hysteria2_spec(_make_hysteria2_candidate(server_name=None), "google-scholar-node-001")

    assert spec.tls is not None
    assert spec.tls.server_name == "hy2.example.invalid"
    assert spec.warnings


def test_build_hysteria2_spec_rejects_obfs() -> None:
    """Fail closed on unsupported Hysteria2 obfs fields."""
    with pytest.raises(ValueError, match="obfs is not mapped to Xray yet"):
        build_hysteria2_spec(
            _make_hysteria2_candidate(extra={"obfs": "salamander", "obfs-password": "OBFS_PASSWORD_PLACEHOLDER"}),
            "google-scholar-node-001",
        )


def test_build_hysteria2_spec_rejects_alpn() -> None:
    """Fail closed on unsupported Hysteria2 ALPN fields."""
    with pytest.raises(ValueError, match="alpn is not mapped to Xray yet"):
        build_hysteria2_spec(_make_hysteria2_candidate(alpn="h3,h2"), "google-scholar-node-001")


def test_build_vless_spec_keeps_reality_shape() -> None:
    """Keep Reality data in the normalized spec."""
    spec = build_vless_spec(_make_candidate(), "google-scholar-node-001")

    assert spec.protocol == "vless"
    assert isinstance(spec.protocol_spec, VlessProtocolSpec)
    assert spec.transport.network == "tcp"
    assert spec.reality is not None
    assert spec.reality.server_name == "www.cloudflare.com"
    assert spec.reality.public_key == "PUBLIC_KEY_PLACEHOLDER"
    assert spec.tls is None


def test_build_vmess_spec_keeps_transport_and_alter_id() -> None:
    """Keep VMess transport and user settings in the spec."""
    spec = build_vmess_spec(
        _make_candidate(
            protocol="vmess",
            encryption="auto",
            flow=None,
            network="ws",
            security="tls",
            public_key=None,
            short_id=None,
            path="/vmess",
            host="edge.example.invalid",
            raw_uri=None,
            extra={"alterId": 4},
        ),
        "google-scholar-node-001",
    )

    assert isinstance(spec.protocol_spec, VmessProtocolSpec)
    assert spec.protocol_spec.alter_id == 4
    assert spec.transport.network == "ws"
    assert spec.transport.ws_path == "/vmess"
    assert spec.transport.ws_host == "edge.example.invalid"
    assert spec.tls is not None
    assert spec.tls.server_name == "www.cloudflare.com"


def test_build_trojan_spec_keeps_tls_boundary() -> None:
    """Keep Trojan TLS data in the normalized spec."""
    spec = build_trojan_spec(
        _make_candidate(
            protocol="trojan",
            user_id=None,
            password="PASSWORD_PLACEHOLDER",
            encryption=None,
            flow=None,
            security="tls",
            public_key=None,
            short_id=None,
            raw_uri=None,
        ),
        "google-scholar-node-001",
    )

    assert isinstance(spec.protocol_spec, TrojanProtocolSpec)
    assert spec.tls is not None
    assert spec.tls.enabled is True
    assert spec.tls.server_name == "www.cloudflare.com"


def test_build_shadowsocks_spec_keeps_no_stream_layer_requirements() -> None:
    """Keep Shadowsocks in the protocol layer only."""
    spec = build_shadowsocks_spec(
        _make_candidate(
            protocol="shadowsocks",
            user_id=None,
            password="PASSWORD_PLACEHOLDER",
            encryption="aes-256-gcm",
            flow=None,
            security=None,
            public_key=None,
            short_id=None,
            raw_uri=None,
        ),
        "google-scholar-node-001",
    )

    assert isinstance(spec.protocol_spec, ShadowsocksProtocolSpec)
    assert spec.protocol == "shadowsocks"
    assert spec.transport.network == "tcp"
    assert spec.tls is None


def test_build_xray_outbound_spec_dispatches_supported_protocols() -> None:
    """Dispatch through the spec builder entrypoint."""
    assert build_xray_outbound_spec(_make_candidate(), "tag").protocol == "vless"
    assert build_xray_outbound_spec(_make_hysteria2_candidate(), "tag").protocol == "hysteria"


def _make_candidate(**overrides: object) -> CandidateProxy:
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


def _make_hysteria2_candidate(**overrides: object) -> CandidateProxy:
    candidate_data: dict[str, object] = {
        "protocol": "hysteria2",
        "user_id": None,
        "password": "HY2_PASSWORD_PLACEHOLDER",
        "encryption": None,
        "flow": None,
        "network": None,
        "security": "hysteria",
        "server_name": "hy2.example.invalid",
        "fingerprint": None,
        "public_key": None,
        "short_id": None,
        "alpn": None,
        "raw_uri": None,
        "address": "hy2.example.invalid",
        "extra": {"skip_cert_verify": True},
    }
    candidate_data.update(overrides)
    return _make_candidate(**candidate_data)
