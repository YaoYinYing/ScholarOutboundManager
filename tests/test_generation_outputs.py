"""Tests for Phase 13B generation outputs."""

from __future__ import annotations

import json

import pytest

from scholar_outbound_manager.generation import build_generated_nodes
from scholar_outbound_manager.generation import write_generation_outputs
from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import GenerationConfig
from scholar_outbound_manager.models import OutputConfig
from scholar_outbound_manager.models import ProbeResult
from scholar_outbound_manager.models import RoutingConfig


def test_build_generated_nodes_can_select_multiple_xray_protocols() -> None:
    """Generate nodes for all Xray-compatible protocols in this phase."""
    nodes = build_generated_nodes(
        candidates=[
            _make_vless_candidate(raw_name="node-vless"),
            _make_trojan_candidate(raw_name="node-trojan"),
            _make_shadowsocks_candidate(raw_name="node-ss"),
            _make_vmess_candidate(raw_name="node-vmess"),
        ],
        tag_prefix="google-scholar-node-",
        max_nodes=4,
    )

    assert [node.outbound["protocol"] for node in nodes] == [
        "vless",
        "trojan",
        "shadowsocks",
        "vmess",
    ]


def test_build_generated_nodes_uses_stable_tag_numbers() -> None:
    """Assign stable sequential tags across mixed supported protocols."""
    nodes = build_generated_nodes(
        candidates=[
            _make_vless_candidate(raw_name="node-1"),
            _make_trojan_candidate(raw_name="node-2"),
            _make_shadowsocks_candidate(raw_name="node-3"),
        ],
        tag_prefix="google-scholar-node-",
        max_nodes=3,
    )

    assert [node.tag for node in nodes] == [
        "google-scholar-node-001",
        "google-scholar-node-002",
        "google-scholar-node-003",
    ]


def test_write_generation_outputs_rejects_unsupported_protocol_without_crashing(tmp_path) -> None:
    """Reject unsupported protocols while still writing artifacts."""
    summary = write_generation_outputs(
        candidates=[
            _make_vless_candidate(raw_name="selected-node"),
            _make_candidate(protocol="hysteria2", raw_name="unsupported-node", public_key=None, short_id=None),
        ],
        output_config=_make_output_config(tmp_path),
        generation_config=_make_generation_config(),
        routing_config=_make_routing_config(fail_closed=True),
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert summary["selected_count"] == 1
    assert summary["rejected_count"] == 1
    assert manifest["rejected"][0]["reason"].startswith("Xray outbound is not supported:")


def test_write_generation_outputs_fail_closed_without_nodes(tmp_path) -> None:
    """Generate blackhole artifacts when no node is selected."""
    summary = write_generation_outputs(
        candidates=[_make_candidate(protocol="vmess", supported=False, unsupported_reason="Unsupported transport.")],
        output_config=_make_output_config(tmp_path),
        generation_config=_make_generation_config(),
        routing_config=_make_routing_config(fail_closed=True),
    )

    outbounds = json.loads((tmp_path / "outbounds.json").read_text(encoding="utf-8"))
    routes = json.loads((tmp_path / "routes.json").read_text(encoding="utf-8"))
    assert summary["selected_count"] == 0
    assert outbounds["outbounds"] == [{"tag": "blocked-scholar", "protocol": "blackhole"}]
    assert routes["routing"]["rules"][0]["outboundTag"] == "blocked-scholar"


def test_manifest_redaction_hides_uuid_password_public_key_and_raw_uri(tmp_path) -> None:
    """Keep sensitive fields out of review-safe manifest output."""
    write_generation_outputs(
        candidates=[
            _make_vless_candidate(raw_name="node-vless"),
            _make_trojan_candidate(raw_name="node-trojan"),
        ],
        output_config=_make_output_config(tmp_path),
        generation_config=_make_generation_config(),
        routing_config=_make_routing_config(fail_closed=True),
    )

    rendered = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert "00000000-0000-0000-0000-000000000000" not in rendered
    assert "PASSWORD_PLACEHOLDER" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "vless://" not in rendered


def test_build_generated_nodes_preserves_probe_evidence_when_provided() -> None:
    """Attach probe evidence to generated nodes when present."""
    probe_results = [
        ProbeResult(
            candidate_id="candidate-001",
            home_status=200,
            query_status=200,
            blocked=False,
            timeout=False,
            error=None,
            failure_markers=[],
            latency_ms=15,
            checked_at="2026-05-25T00:00:00Z",
        )
    ]

    nodes = build_generated_nodes(
        candidates=[_make_vless_candidate(raw_name="node-1")],
        tag_prefix="google-scholar-node-",
        max_nodes=1,
        probe_results=probe_results,
    )

    assert nodes[0].probe is not None
    assert nodes[0].probe.candidate_id == "candidate-001"


def test_write_generation_outputs_keeps_probe_evidence_in_manifest(tmp_path) -> None:
    """Write selected-node probe evidence into the generated manifest."""
    probe_results = [
        ProbeResult(
            candidate_id="candidate-001",
            home_status=200,
            query_status=200,
            blocked=False,
            timeout=False,
            error=None,
            failure_markers=[],
            latency_ms=15,
            checked_at="2026-05-25T00:00:00Z",
        )
    ]

    write_generation_outputs(
        candidates=[_make_vless_candidate(raw_name="node-1")],
        output_config=_make_output_config(tmp_path),
        generation_config=_make_generation_config(),
        routing_config=_make_routing_config(fail_closed=True),
        probe_results=probe_results,
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["selected"][0]["probe"]["candidate_id"] == "candidate-001"


def test_write_generation_outputs_rejects_unsupported_routing_mode(tmp_path) -> None:
    """Reject routing modes outside the current boundary."""
    with pytest.raises(ValueError, match="Only dedicated_inbound routing mode is supported in Phase 3b"):
        write_generation_outputs(
            candidates=[_make_vless_candidate(raw_name="node-1")],
            output_config=_make_output_config(tmp_path),
            generation_config=_make_generation_config(),
            routing_config=RoutingConfig(
                mode="domain_match",
                inbound_tags=["scholar-in"],
                fail_closed=True,
            ),
        )


def _make_candidate(**overrides: object) -> CandidateProxy:
    """Construct one baseline candidate for generation tests."""
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
        "path": "/ws",
        "host": "cdn.example.invalid",
        "extra": {},
        "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
        "supported": True,
        "unsupported_reason": None,
    }
    candidate_data.update(overrides)
    return CandidateProxy(**candidate_data)


def _make_vless_candidate(**overrides: object) -> CandidateProxy:
    candidate = _make_candidate(**overrides)
    return candidate


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


def _make_output_config(tmp_path) -> OutputConfig:
    """Construct output paths rooted in the pytest temporary directory."""
    return OutputConfig(
        outbounds_path=str(tmp_path / "outbounds.json"),
        routes_path=str(tmp_path / "routes.json"),
        manifest_path=str(tmp_path / "manifest.json"),
        history_dir=str(tmp_path / "history"),
    )


def _make_generation_config() -> GenerationConfig:
    """Construct one generation configuration for tests."""
    return GenerationConfig(
        tag_prefix="google-scholar-node-",
        max_passed_nodes=4,
        fallback_blackhole_tag="blocked-scholar",
        previous_output_max_age_hours=24,
    )


def _make_routing_config(fail_closed: bool) -> RoutingConfig:
    """Construct one routing configuration for tests."""
    return RoutingConfig(
        mode="dedicated_inbound",
        inbound_tags=["scholar-in"],
        fail_closed=fail_closed,
    )
