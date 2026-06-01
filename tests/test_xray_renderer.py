"""Tests for rendering structured Xray outbound specs."""

from __future__ import annotations

import json

import pytest

from scholar_outbound_manager.xray.renderer import render_stream_settings
from scholar_outbound_manager.xray.renderer import render_xray_outbound
from scholar_outbound_manager.xray.spec import HysteriaProtocolSpec
from scholar_outbound_manager.xray.spec import ShadowsocksProtocolSpec
from scholar_outbound_manager.xray.spec import XrayOutboundSpec
from scholar_outbound_manager.xray.spec import XrayServerEndpoint
from scholar_outbound_manager.xray.spec import XrayTlsSpec
from scholar_outbound_manager.xray.spec import XrayTransportSpec
from scholar_outbound_manager.xray.spec_builder import build_hysteria2_spec
from scholar_outbound_manager.xray.spec_builder import build_vless_spec
from scholar_outbound_manager.models import CandidateProxy


def test_render_hysteria2_outbound_exact_shape() -> None:
    """Render a Hysteria2 spec to the expected Xray JSON shape."""
    outbound = render_xray_outbound(build_hysteria2_spec(_make_hysteria2_candidate(), "google-scholar-node-001"))

    assert outbound == {
        "tag": "google-scholar-node-001",
        "protocol": "hysteria",
        "settings": {
            "version": 2,
            "address": "hy2.example.invalid",
            "port": 443,
        },
        "streamSettings": {
            "network": "hysteria",
            "security": "tls",
            "tlsSettings": {
                "serverName": "hy2.example.invalid",
                "allowInsecure": True,
            },
            "hysteriaSettings": {
                "version": 2,
                "auth": "HY2_PASSWORD_PLACEHOLDER",
            },
        },
    }


def test_renderer_does_not_include_raw_uri() -> None:
    """Keep raw URI source material out of rendered JSON."""
    rendered = json.dumps(render_xray_outbound(build_vless_spec(_make_candidate(), "google-scholar-node-001")))

    assert "vless://" not in rendered


def test_renderer_rejects_missing_hysteria_auth() -> None:
    """Do not render hysteria transport without auth."""
    spec = XrayOutboundSpec(
        tag="tag",
        protocol="hysteria",
        protocol_spec=HysteriaProtocolSpec(endpoint=XrayServerEndpoint(address="hy2.example.invalid", port=443)),
        transport=XrayTransportSpec(network="hysteria"),
        tls=XrayTlsSpec(enabled=True, server_name="hy2.example.invalid"),
    )

    with pytest.raises(ValueError, match="requires auth"):
        render_stream_settings(spec)


def test_renderer_omits_tls_settings_when_disabled() -> None:
    """Do not emit TLS settings for protocols without TLS."""
    spec = XrayOutboundSpec(
        tag="tag",
        protocol="shadowsocks",
        protocol_spec=ShadowsocksProtocolSpec(
            endpoint=XrayServerEndpoint(address="ss.example.invalid", port=443),
            method="aes-256-gcm",
            password="PASSWORD_PLACEHOLDER",
        ),
    )

    rendered = render_xray_outbound(spec)
    assert "streamSettings" not in rendered


def test_renderer_keeps_vless_ws_reality_behavior() -> None:
    """Keep existing Reality and WebSocket rendering semantics."""
    outbound = render_xray_outbound(
        build_vless_spec(
            _make_candidate(
                network="ws",
                alpn="h2,http/1.1",
                path="/ws",
                host="cdn.example.invalid",
            ),
            "google-scholar-node-001",
        )
    )

    assert outbound["streamSettings"]["security"] == "reality"
    assert outbound["streamSettings"]["realitySettings"]["serverName"] == "www.cloudflare.com"
    assert outbound["streamSettings"]["realitySettings"]["alpn"] == ["h2", "http/1.1"]
    assert outbound["streamSettings"]["wsSettings"] == {
        "path": "/ws",
        "headers": {"Host": "cdn.example.invalid"},
    }


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
        alpn=None,
        raw_uri=None,
        address="hy2.example.invalid",
        extra={"skip_cert_verify": True},
        **overrides,
    )
