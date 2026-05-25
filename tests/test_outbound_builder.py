"""Tests for VLESS outbound fragment generation."""

from __future__ import annotations

import pytest

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.xray.outbound_builder import build_vless_outbound


def test_build_vless_reality_vision_outbound() -> None:
    """Build a VLESS Reality Vision outbound successfully."""
    candidate = _make_candidate()

    outbound = build_vless_outbound(candidate, "google-scholar-node-001")

    assert outbound["tag"] == "google-scholar-node-001"
    assert outbound["protocol"] == "vless"
    assert outbound["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"
    assert outbound["streamSettings"]["security"] == "reality"
    assert outbound["streamSettings"]["realitySettings"]["serverName"] == "www.cloudflare.com"


def test_outbound_does_not_include_raw_uri() -> None:
    """Exclude raw URI source material from generated outbounds."""
    candidate = _make_candidate()

    outbound = build_vless_outbound(candidate, "google-scholar-node-001")

    assert "raw_uri" not in repr(outbound)


def test_build_vless_outbound_omits_flow_when_missing() -> None:
    """Omit the flow field when the candidate does not define it."""
    candidate = _make_candidate(flow=None)

    outbound = build_vless_outbound(candidate, "google-scholar-node-001")

    users = outbound["settings"]["vnext"][0]["users"]
    assert "flow" not in users[0]


def test_build_vless_outbound_requires_reality_public_key() -> None:
    """Reject Reality candidates without a public key."""
    candidate = _make_candidate(public_key=None)

    with pytest.raises(ValueError, match="public_key"):
        build_vless_outbound(candidate, "google-scholar-node-001")


def test_build_vless_outbound_rejects_unsupported_candidate() -> None:
    """Reject candidates marked unsupported."""
    candidate = _make_candidate(supported=False, unsupported_reason="Unsupported transport.")

    with pytest.raises(ValueError, match="Unsupported transport."):
        build_vless_outbound(candidate, "google-scholar-node-001")


def test_build_vless_outbound_rejects_grpc() -> None:
    """Reject gRPC until the Phase 3 scope expands."""
    candidate = _make_candidate(network="grpc")

    with pytest.raises(ValueError, match="Phase 3 does not support grpc yet"):
        build_vless_outbound(candidate, "google-scholar-node-001")


def test_build_vless_outbound_splits_comma_delimited_alpn() -> None:
    """Split comma-delimited ALPN values into a list."""
    candidate = _make_candidate(alpn="h2,http/1.1")

    outbound = build_vless_outbound(candidate, "google-scholar-node-001")

    assert outbound["streamSettings"]["realitySettings"]["alpn"] == ["h2", "http/1.1"]


def _make_candidate(**overrides: object) -> CandidateProxy:
    """Construct one baseline VLESS Reality candidate for tests."""
    candidate_data: dict[str, object] = {
        "source_name": "unit-test",
        "raw_name": "reality-node",
        "protocol": "vless",
        "address": "example.invalid",
        "port": 443,
        "user_id": "00000000-0000-0000-0000-000000000000",
        "encryption": "none",
        "flow": "xtls-rprx-vision",
        "network": "tcp",
        "security": "reality",
        "server_name": "www.cloudflare.com",
        "fingerprint": "chrome",
        "public_key": "PUBLIC_KEY_PLACEHOLDER",
        "short_id": "abcd1234",
        "alpn": "h2",
        "path": "/ws",
        "host": "cdn.example.invalid",
        "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443?security=reality",
        "supported": True,
        "unsupported_reason": None,
    }
    candidate_data.update(overrides)
    return CandidateProxy(**candidate_data)
