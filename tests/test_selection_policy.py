"""Tests for geo-aware selection policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scholar_outbound_manager.selection_policy import explain_selection_policy
from scholar_outbound_manager.selection_policy import SelectionPolicyOptions
from scholar_outbound_manager.selection_policy import select_candidate_with_policy


def test_manual_candidate_id_wins_over_geo(tmp_path: Path) -> None:
    """Honor an explicit candidate ID before geo ranking."""
    payload = _payload()
    _write_geo_files(tmp_path)

    candidate, probe, decision = select_candidate_with_policy(
        payload,
        SelectionPolicyOptions(
            preferred_candidate_id="candidate-002",
            strategy="auto",
            geo_cache_path=str(tmp_path / "candidate_geo_cache.json"),
            host_geo_path=str(tmp_path / "host_geo.json"),
        ),
    )

    assert candidate.protocol == "trojan"
    assert probe is not None
    assert decision.method == "manual:candidate_id"


def test_manual_index_wins_over_geo(tmp_path: Path) -> None:
    """Honor an explicit candidate index before geo ranking."""
    payload = _payload()
    _write_geo_files(tmp_path)

    candidate, _, decision = select_candidate_with_policy(
        payload,
        SelectionPolicyOptions(
            preferred_candidate_index=1,
            strategy="auto",
            geo_cache_path=str(tmp_path / "candidate_geo_cache.json"),
            host_geo_path=str(tmp_path / "host_geo.json"),
        ),
    )

    assert candidate.protocol == "trojan"
    assert decision.selected_index == 1


def test_selected_candidate_path_wins_if_provided(tmp_path: Path) -> None:
    """Use the selected-candidate artifact before any other strategy."""
    selected_path = tmp_path / "selected_candidate.json"
    selected_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sensitive": True,
                "selected_at": "2026-05-27T00:00:00Z",
                "selection_method": "candidate_id",
                "selected_candidate_id": "candidate-002",
                "selected_index": 1,
                "candidate": _payload()["candidates"][1]["candidate"],
                "probe": _payload()["candidates"][1]["probe"],
            }
        ),
        encoding="utf-8",
    )

    candidate, _, decision = select_candidate_with_policy(
        _payload(),
        SelectionPolicyOptions(
            selected_candidate_path=str(selected_path),
            strategy="auto",
        ),
    )

    assert candidate.protocol == "trojan"
    assert decision.method == "manual:selected_candidate"


def test_geo_nearest_works_with_cache(tmp_path: Path) -> None:
    """Pick the nearest cached geo candidate when available."""
    payload = _payload()
    _write_geo_files(tmp_path)

    candidate, _, decision = select_candidate_with_policy(
        payload,
        SelectionPolicyOptions(
            strategy="geo_nearest",
            geo_cache_path=str(tmp_path / "candidate_geo_cache.json"),
            host_geo_path=str(tmp_path / "host_geo.json"),
        ),
    )

    assert candidate.protocol == "vless"
    assert decision.method == "geo_nearest"
    assert decision.geo_distance_km is not None


def test_geo_nearest_falls_back_to_first_when_cache_missing(tmp_path: Path) -> None:
    """Fall back to the first passed candidate when geo cache is unavailable."""
    candidate, _, decision = select_candidate_with_policy(
        _payload(),
        SelectionPolicyOptions(
            strategy="geo_nearest",
            geo_cache_path=str(tmp_path / "missing_cache.json"),
            host_geo_path=str(tmp_path / "missing_host.json"),
            fallback_to_first=True,
        ),
    )

    assert candidate.protocol == "vless"
    assert decision.method == "fallback:first"


def test_no_fallback_raises_clear_error(tmp_path: Path) -> None:
    """Raise when no selection path is available and fallback is disabled."""
    with pytest.raises(ValueError, match="requires host_geo and candidate_geo cache"):
        select_candidate_with_policy(
            _payload(),
            SelectionPolicyOptions(
                strategy="geo_nearest",
                geo_cache_path=str(tmp_path / "missing_cache.json"),
                host_geo_path=str(tmp_path / "missing_host.json"),
                fallback_to_first=False,
            ),
        )


def test_decision_output_hides_secrets(tmp_path: Path) -> None:
    """Keep the decision model redacted."""
    payload = _payload()
    _write_geo_files(tmp_path)

    _, _, decision = select_candidate_with_policy(
        payload,
        SelectionPolicyOptions(
            strategy="geo_nearest",
            geo_cache_path=str(tmp_path / "candidate_geo_cache.json"),
            host_geo_path=str(tmp_path / "host_geo.json"),
        ),
    )

    rendered = str(decision)
    assert "example.invalid" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "PASSWORD_PLACEHOLDER" not in rendered


def test_select_explain_hides_secrets(tmp_path: Path) -> None:
    """Explain selection ordering without exposing sensitive fields."""
    payload = _payload()
    _write_geo_files(tmp_path)

    explanation = explain_selection_policy(
        payload,
        SelectionPolicyOptions(
            strategy="auto",
            geo_cache_path=str(tmp_path / "candidate_geo_cache.json"),
            host_geo_path=str(tmp_path / "host_geo.json"),
        ),
    )

    rendered = json.dumps(explanation, ensure_ascii=False, sort_keys=True)
    assert "candidate-001" in rendered
    assert "example.invalid" not in rendered
    assert "raw_uri" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered


def _write_geo_files(tmp_path: Path) -> None:
    (tmp_path / "host_geo.json").write_text(
        json.dumps(
            {
                "country": "TW",
                "region": "Taipei",
                "city": "Taipei",
                "latitude": 25.033,
                "longitude": 121.565,
                "accuracy_radius_km": 50,
                "source": "manual",
                "updated_at": "2026-05-27T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "candidate_geo_cache.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "candidate_id": "candidate-001",
                        "protocol": "vless",
                        "geo": {
                            "country": "TW",
                            "city": "Taipei",
                            "latitude": 25.0375,
                            "longitude": 121.5637,
                            "accuracy_radius_km": 20,
                            "source": "manual",
                            "updated_at": "2026-05-27T00:00:00Z",
                        },
                        "confidence": "city",
                        "note": "cached",
                    },
                    {
                        "candidate_id": "candidate-002",
                        "protocol": "trojan",
                        "geo": {
                            "country": "JP",
                            "city": "Tokyo",
                            "latitude": 35.6762,
                            "longitude": 139.6503,
                            "accuracy_radius_km": 100,
                            "source": "manual",
                            "updated_at": "2026-05-27T00:00:00Z",
                        },
                        "confidence": "city",
                        "note": "cached",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "sensitive": True,
        "candidates": [
            {
                "candidate": {
                    "source_name": "fixture",
                    "raw_name": "node-a",
                    "protocol": "vless",
                    "address": "example.invalid",
                    "port": 443,
                    "user_id": "00000000-0000-0000-0000-000000000000",
                    "security": "reality",
                    "server_name": "www.cloudflare.com",
                    "public_key": "PUBLIC_KEY_PLACEHOLDER",
                    "supported": True,
                    "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
                },
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
                "candidate": {
                    "source_name": "fixture",
                    "raw_name": "node-b",
                    "protocol": "trojan",
                    "address": "example-b.invalid",
                    "port": 443,
                    "password": "PASSWORD_PLACEHOLDER",
                    "security": "tls",
                    "server_name": "www.cloudflare.com",
                    "supported": True,
                },
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
