"""Tests for the single-Xray sidecar pool helpers."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.sidecar_pool import build_multi_port_sidecar_runtime_config
from scholar_outbound_manager.sidecar_pool import build_pool_socks_outbound_snippets
from scholar_outbound_manager.sidecar_pool import build_sidecar_pool_plan
from scholar_outbound_manager.sidecar_pool import check_pool_ports_available
from scholar_outbound_manager.sidecar_pool import check_tcp_port_available
from scholar_outbound_manager.sidecar_pool import load_pool_plan
from scholar_outbound_manager.sidecar_pool import validate_pool_sidecar
from scholar_outbound_manager.sidecar_pool import write_pool_plan


def test_build_sidecar_pool_plan_from_passed_candidates() -> None:
    """Plan one multi-port pool from passed candidates."""
    plan = build_sidecar_pool_plan(_passed_candidates_payload(), base_port=19080)

    assert plan.count == 2
    assert plan.entries[0].listen_port == 19080
    assert plan.entries[1].listen_port == 19081
    assert plan.entries[0].candidate_id == "candidate-001"


def test_build_sidecar_pool_plan_applies_max_count() -> None:
    """Limit the pool entry count when requested."""
    plan = build_sidecar_pool_plan(_passed_candidates_payload(), max_count=1)

    assert plan.count == 1
    assert len(plan.entries) == 1


def test_build_sidecar_pool_plan_filters_by_candidate_id() -> None:
    """Select exact candidate IDs for the pool plan."""
    plan = build_sidecar_pool_plan(_passed_candidates_payload(), candidate_ids=["candidate-002"])

    assert plan.count == 1
    assert plan.entries[0].candidate_id == "candidate-002"


def test_build_sidecar_pool_plan_rejects_missing_candidate_id() -> None:
    """Reject unknown pool candidate IDs."""
    with pytest.raises(ValueError, match="was not found"):
        build_sidecar_pool_plan(_passed_candidates_payload(), candidate_ids=["missing"])


def test_build_sidecar_pool_plan_rejects_port_overflow() -> None:
    """Reject ports beyond the valid TCP range."""
    with pytest.raises(ValueError, match="1..65535"):
        build_sidecar_pool_plan(_passed_candidates_payload(), base_port=65535)


def test_check_tcp_port_available_returns_true_for_free_port() -> None:
    """Report availability for a free local port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert check_tcp_port_available("127.0.0.1", int(port)) is True


def test_check_tcp_port_available_returns_false_for_occupied_port() -> None:
    """Report unavailable when another listener already owns the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert check_tcp_port_available("127.0.0.1", int(port)) is False


def test_check_pool_ports_available_reports_each_port() -> None:
    """Report availability by pool index."""
    plan = build_sidecar_pool_plan(_passed_candidates_payload(), base_port=19180)

    availability = check_pool_ports_available(plan)

    assert availability == {0: True, 1: True}


def test_build_multi_port_sidecar_runtime_config_creates_matching_sections() -> None:
    """Build one runtime config with matched inbounds, outbounds, and routes."""
    plan = build_sidecar_pool_plan(_passed_candidates_payload(), base_port=19080)
    candidates_by_id = {
        "candidate-001": _make_candidate(),
        "candidate-002": _make_candidate(
            protocol="trojan",
            user_id=None,
            password="PASSWORD_PLACEHOLDER",
            security="tls",
            public_key=None,
            short_id=None,
        ),
    }

    runtime_config = build_multi_port_sidecar_runtime_config(
        entries=plan.entries,
        candidates_by_id=candidates_by_id,
    )

    assert len(runtime_config["inbounds"]) == 2
    assert len(runtime_config["outbounds"]) == 2
    assert runtime_config["routing"]["rules"][0]["outboundTag"] == "scholar-sidecar-out-0"
    assert "raw_uri" not in json.dumps(runtime_config)


def test_build_multi_port_sidecar_runtime_config_supports_hysteria2_and_vless() -> None:
    """Allow Hysteria2 and VLESS candidates to coexist in one pool config."""
    plan = build_sidecar_pool_plan(_passed_candidates_payload_hysteria2(), base_port=19080)
    candidates_by_id = {
        "candidate-001": _make_candidate(),
        "candidate-002": _make_candidate(
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
        ),
    }

    runtime_config = build_multi_port_sidecar_runtime_config(
        entries=plan.entries,
        candidates_by_id=candidates_by_id,
    )

    assert [outbound["protocol"] for outbound in runtime_config["outbounds"]] == ["vless", "hysteria"]


def test_write_and_load_pool_plan_round_trip(tmp_path: Path) -> None:
    """Persist and reload a redacted pool plan artifact."""
    plan = build_sidecar_pool_plan(_passed_candidates_payload(), base_port=19080)
    output_path = tmp_path / "sidecar_pool_plan.json"

    write_pool_plan(output_path, plan)
    loaded = load_pool_plan(output_path)

    assert loaded.count == 2
    assert loaded.entries[1].listen_port == 19081


def test_build_pool_socks_outbound_snippets_returns_downstream_snippets() -> None:
    """Render downstream SOCKS snippets for every pool entry."""
    plan = build_sidecar_pool_plan(_passed_candidates_payload(), base_port=19080)

    snippets = build_pool_socks_outbound_snippets(plan)

    assert snippets[0]["protocol"] == "socks"
    assert snippets[1]["settings"]["servers"][0]["port"] == 19081


def test_validate_pool_sidecar_uses_monkeypatched_probe(monkeypatch) -> None:
    """Validate the pool without real network access."""
    plan = build_sidecar_pool_plan(_passed_candidates_payload(), base_port=19080)

    monkeypatch.setattr("scholar_outbound_manager.sidecar_pool._check_tcp_connect", lambda host, port, timeout_seconds: True)

    def fake_probe(target, socks, timeout):
        del socks, timeout
        status = 200
        return type(
            "Response",
            (),
            {
                "url": target.url,
                "status_code": status,
                "reason": "OK",
                "headers": {},
                "body_prefix": "",
                "elapsed_ms": 10,
                "timed_out": False,
                "error": None,
            },
        )()

    monkeypatch.setattr("scholar_outbound_manager.sidecar_pool.probe_http_via_socks", fake_probe)

    results = validate_pool_sidecar(plan)

    assert results[0]["passed"] is True
    assert results[1]["scholar_stage"] == "full_access"


def _passed_candidates_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "sensitive": True,
        "candidates": [
            {
                "candidate": _make_candidate().to_dict(),
                "probe": {
                    "candidate_id": "candidate-001",
                    "home_status": 200,
                    "query_status": 200,
                    "blocked": False,
                    "timeout": False,
                    "error": None,
                    "failure_markers": [],
                    "latency_ms": 10,
                    "checked_at": "2026-05-27T00:00:00Z",
                    "passed": True,
                },
            },
            {
                "candidate": _make_candidate(protocol="trojan", user_id=None, password="PASSWORD_PLACEHOLDER").to_dict(),
                "probe": {
                    "candidate_id": "candidate-002",
                    "home_status": 200,
                    "query_status": 200,
                    "blocked": False,
                    "timeout": False,
                    "error": None,
                    "failure_markers": [],
                    "latency_ms": 12,
                    "checked_at": "2026-05-27T00:00:00Z",
                    "passed": True,
                },
            },
        ],
    }


def _passed_candidates_payload_hysteria2() -> dict[str, object]:
    return {
        "schema_version": 1,
        "sensitive": True,
        "candidates": [
            {
                "candidate": _make_candidate().to_dict(),
                "probe": {
                    "candidate_id": "candidate-001",
                    "home_status": 200,
                    "query_status": 200,
                    "blocked": False,
                    "timeout": False,
                    "error": None,
                    "failure_markers": [],
                    "latency_ms": 10,
                    "checked_at": "2026-05-27T00:00:00Z",
                    "passed": True,
                },
            },
            {
                "candidate": _make_candidate(
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
                ).to_dict(),
                "probe": {
                    "candidate_id": "candidate-002",
                    "home_status": 200,
                    "query_status": 200,
                    "blocked": False,
                    "timeout": False,
                    "error": None,
                    "failure_markers": [],
                    "latency_ms": 12,
                    "checked_at": "2026-05-27T00:00:00Z",
                    "passed": True,
                },
            },
        ],
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
