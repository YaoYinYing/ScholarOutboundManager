"""Tests for Xray outbound fragment generation."""

from __future__ import annotations

import json

import pytest

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.xray.outbound_builder import build_trojan_outbound
from scholar_outbound_manager.xray.outbound_builder import build_vless_outbound
from scholar_outbound_manager.xray.outbound_builder import build_vmess_outbound
from scholar_outbound_manager.xray.outbound_builder import build_xray_outbound
from scholar_outbound_manager.xray.outbound_builder import build_hysteria2_outbound
from scholar_outbound_manager.xray.outbound_builder import build_shadowsocks_outbound


def test_build_xray_outbound_dispatches_vless() -> None:
    """Dispatch supported VLESS candidates through the unified builder."""
    outbound = build_xray_outbound(_make_candidate(), "google-scholar-node-001")

    assert outbound["protocol"] == "vless"


def test_build_xray_outbound_dispatches_hysteria2() -> None:
    """Dispatch supported Hysteria2 candidates through the unified builder."""
    outbound = build_xray_outbound(_make_hysteria2_candidate(), "google-scholar-node-001")

    assert outbound["protocol"] == "hysteria"


def test_build_hysteria2_outbound() -> None:
    """Build a conservative Xray Hysteria outbound for Hysteria2."""
    outbound = build_hysteria2_outbound(_make_hysteria2_candidate(), "google-scholar-node-001")

    assert outbound["protocol"] == "hysteria"
    assert outbound["settings"] == {
        "version": 2,
        "address": "hy2.example.invalid",
        "port": 443,
    }
    assert outbound["streamSettings"]["network"] == "hysteria"
    assert outbound["streamSettings"]["security"] == "tls"
    assert outbound["streamSettings"]["tlsSettings"] == {
        "serverName": "hy2.example.invalid",
        "allowInsecure": True,
    }
    assert outbound["streamSettings"]["hysteriaSettings"] == {
        "version": 2,
        "auth": "HY2_PASSWORD_PLACEHOLDER",
    }


def test_build_hysteria2_outbound_keeps_experimental_candidate_path_available() -> None:
    """Keep the Xray builder available for explicitly enabled experimental candidates."""
    outbound = build_hysteria2_outbound(
        _make_hysteria2_candidate(extra={"experimental": True, "runtime_supported_by": ["xray-experimental"]}),
        "google-scholar-node-001",
    )

    assert outbound["protocol"] == "hysteria"


def test_build_hysteria2_outbound_rejects_missing_password() -> None:
    """Reject Hysteria2 candidates without auth material."""
    with pytest.raises(ValueError, match="authentication secret"):
        build_hysteria2_outbound(
            _make_hysteria2_candidate(password=None),
            "google-scholar-node-001",
        )


def test_build_hysteria2_outbound_rejects_obfs() -> None:
    """Fail closed when unmapped obfs fields are present."""
    with pytest.raises(ValueError, match="obfs is not mapped to Xray yet"):
        build_hysteria2_outbound(
            _make_hysteria2_candidate(extra={"obfs": "salamander", "obfs-password": "OBFS_PASSWORD_PLACEHOLDER"}),
            "google-scholar-node-001",
        )


def test_build_hysteria2_outbound_preserves_skip_cert_verify_false() -> None:
    """Default TLS verification should stay enabled when false is configured."""
    outbound = build_hysteria2_outbound(
        _make_hysteria2_candidate(extra={"skip_cert_verify": False}),
        "google-scholar-node-001",
    )

    assert outbound["streamSettings"]["tlsSettings"]["allowInsecure"] is False


def test_build_hysteria2_outbound_falls_back_to_address_for_server_name() -> None:
    """Fallback to address when the Clash node omits an explicit SNI value."""
    outbound = build_hysteria2_outbound(
        _make_hysteria2_candidate(server_name=None),
        "google-scholar-node-001",
    )

    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "hy2.example.invalid"


def test_build_hysteria2_outbound_rejects_alpn() -> None:
    """Fail closed when ALPN is still unmapped for Hysteria2."""
    with pytest.raises(ValueError, match="alpn is not mapped to Xray yet"):
        build_hysteria2_outbound(
            _make_hysteria2_candidate(alpn="h3,h2"),
            "google-scholar-node-001",
        )


def test_build_vless_reality_vision_outbound() -> None:
    """Build a VLESS Reality Vision outbound successfully."""
    outbound = build_vless_outbound(_make_candidate(), "google-scholar-node-001")

    assert outbound["streamSettings"]["security"] == "reality"
    assert outbound["streamSettings"]["realitySettings"]["serverName"] == "www.cloudflare.com"


def test_build_vless_tcp_tls_outbound() -> None:
    """Build a TCP+TLS VLESS outbound."""
    outbound = build_vless_outbound(
        _make_candidate(security="tls", public_key=None, short_id=None, flow=None),
        "google-scholar-node-001",
    )

    assert outbound["streamSettings"]["network"] == "tcp"
    assert outbound["streamSettings"]["security"] == "tls"
    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "www.cloudflare.com"


def test_build_vless_ws_tls_outbound() -> None:
    """Build a WS+TLS VLESS outbound."""
    outbound = build_vless_outbound(
        _make_candidate(
            network="ws",
            security="tls",
            public_key=None,
            short_id=None,
            flow=None,
            path="/ws",
            host="cdn.example.invalid",
        ),
        "google-scholar-node-001",
    )

    assert outbound["streamSettings"]["network"] == "ws"
    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "www.cloudflare.com"
    assert outbound["streamSettings"]["wsSettings"] == {
        "path": "/ws",
        "headers": {"Host": "cdn.example.invalid"},
    }


def test_build_trojan_tcp_tls_outbound() -> None:
    """Build a TCP+TLS Trojan outbound."""
    outbound = build_trojan_outbound(
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

    assert outbound["protocol"] == "trojan"
    assert outbound["streamSettings"]["network"] == "tcp"
    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "www.cloudflare.com"


def test_build_trojan_ws_tls_outbound() -> None:
    """Build a WS+TLS Trojan outbound."""
    outbound = build_trojan_outbound(
        _make_candidate(
            protocol="trojan",
            user_id=None,
            password="PASSWORD_PLACEHOLDER",
            encryption=None,
            flow=None,
            network="ws",
            security="tls",
            path="/trojan",
            host="edge.example.invalid",
            public_key=None,
            short_id=None,
            raw_uri=None,
        ),
        "google-scholar-node-001",
    )

    assert outbound["streamSettings"]["wsSettings"]["path"] == "/trojan"
    assert outbound["streamSettings"]["wsSettings"]["headers"]["Host"] == "edge.example.invalid"


def test_build_shadowsocks_outbound() -> None:
    """Build a Shadowsocks outbound."""
    outbound = build_shadowsocks_outbound(
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

    assert outbound["protocol"] == "shadowsocks"
    assert outbound["settings"]["servers"][0]["method"] == "aes-256-gcm"
    assert "streamSettings" not in outbound


def test_build_vmess_tcp_outbound() -> None:
    """Build a TCP VMess outbound."""
    outbound = build_vmess_outbound(
        _make_candidate(
            protocol="vmess",
            encryption="auto",
            flow=None,
            security="none",
            public_key=None,
            short_id=None,
            raw_uri=None,
            extra={"alter_id": 8},
        ),
        "google-scholar-node-001",
    )

    assert outbound["protocol"] == "vmess"
    assert outbound["settings"]["vnext"][0]["users"][0]["alterId"] == 8
    assert outbound["streamSettings"]["security"] == "none"


def test_build_vmess_ws_tls_outbound() -> None:
    """Build a WS+TLS VMess outbound."""
    outbound = build_vmess_outbound(
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

    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "www.cloudflare.com"
    assert outbound["streamSettings"]["wsSettings"]["path"] == "/vmess"
    assert outbound["settings"]["vnext"][0]["users"][0]["alterId"] == 4


def test_build_xray_outbound_rejects_unsupported_protocol() -> None:
    """Reject protocols outside the supported Xray set."""
    candidate = _make_candidate(protocol="wireguard", public_key=None, short_id=None, raw_uri=None)

    with pytest.raises(ValueError, match="protocol 'wireguard'"):
        build_xray_outbound(candidate, "google-scholar-node-001")


def test_builders_reject_grpc() -> None:
    """Reject gRPC transports for this phase."""
    with pytest.raises(ValueError, match="Phase 13B does not support grpc yet"):
        build_vless_outbound(_make_candidate(network="grpc"), "google-scholar-node-001")
    with pytest.raises(ValueError, match="Phase 13B does not support grpc yet"):
        build_vmess_outbound(
            _make_candidate(
                protocol="vmess",
                network="grpc",
                encryption="auto",
                flow=None,
                security="none",
                public_key=None,
                short_id=None,
                raw_uri=None,
            ),
            "google-scholar-node-001",
        )


def test_outbounds_do_not_include_raw_uri() -> None:
    """Exclude raw URI source material from generated outbounds."""
    rendered = json.dumps(
        build_xray_outbound(
            _make_candidate(protocol="vmess", security="none", public_key=None, short_id=None, raw_uri=None),
            "google-scholar-node-001",
        )
    )

    assert "raw_uri" not in rendered
    assert "vless://" not in rendered


def test_builder_errors_do_not_include_secret_material() -> None:
    """Keep error messages free of credential values and raw source material."""
    candidate = _make_candidate(
        protocol="trojan",
        user_id=None,
        password="VERY_SECRET_PASSWORD",
        security="reality",
        public_key="PUBLIC_KEY_PLACEHOLDER",
        raw_uri="vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
    )

    with pytest.raises(ValueError) as excinfo:
        build_trojan_outbound(candidate, "google-scholar-node-001")

    message = str(excinfo.value)
    assert "VERY_SECRET_PASSWORD" not in message
    assert "00000000-0000-0000-0000-000000000000" not in message
    assert "PUBLIC_KEY_PLACEHOLDER" not in message
    assert "vless://" not in message


def _make_candidate(**overrides: object) -> CandidateProxy:
    """Construct one baseline candidate for outbound tests."""
    candidate_data: dict[str, object] = {
        "source_name": "unit-test",
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
        "short_id": "abcd1234",
        "alpn": "h2,http/1.1",
        "path": "/ws",
        "host": "cdn.example.invalid",
        "extra": {},
        "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
        "supported": True,
        "unsupported_reason": None,
    }
    candidate_data.update(overrides)
    return CandidateProxy(**candidate_data)


def _make_hysteria2_candidate(**overrides: object) -> CandidateProxy:
    """Construct one baseline Hysteria2 candidate for outbound tests."""
    candidate_data: dict[str, object] = {
        "source_name": "unit-test",
        "raw_name": "hy2-node",
        "protocol": "hysteria2",
        "address": "hy2.example.invalid",
        "port": 443,
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
        "path": None,
        "host": None,
        "extra": {"skip_cert_verify": True},
        "raw_uri": None,
        "supported": True,
        "unsupported_reason": None,
    }
    candidate_data.update(overrides)
    return CandidateProxy(**candidate_data)
