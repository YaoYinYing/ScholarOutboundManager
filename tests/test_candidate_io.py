"""Tests for offline candidate JSON loading and dumping."""

from __future__ import annotations

import json

import pytest

from scholar_outbound_manager.io import dump_candidates
from scholar_outbound_manager.io import load_candidate_bundle
from scholar_outbound_manager.io import load_candidates


def test_load_candidates_from_top_level_list(tmp_path) -> None:
    """Load candidates from a top-level JSON list."""
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(json.dumps([_candidate_mapping()]), encoding="utf-8")

    candidates = load_candidates(candidate_path)

    assert len(candidates) == 1
    assert candidates[0].raw_name == "US Scholar IPv4"


def test_load_candidates_from_candidates_key(tmp_path) -> None:
    """Load candidates from an object with a candidates list."""
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(json.dumps({"candidates": [_candidate_mapping()]}), encoding="utf-8")

    candidates = load_candidates(candidate_path)

    assert len(candidates) == 1
    assert candidates[0].protocol == "vless"


def test_load_candidates_rejects_invalid_json(tmp_path) -> None:
    """Raise a value error when JSON parsing fails."""
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(ValueError, match=str(candidate_path)):
        load_candidates(candidate_path)


def test_load_candidates_rejects_invalid_top_level_shape(tmp_path) -> None:
    """Reject unsupported top-level JSON structures."""
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(json.dumps({"items": [_candidate_mapping()]}), encoding="utf-8")

    with pytest.raises(ValueError, match="must be a list or an object with a 'candidates' list"):
        load_candidates(candidate_path)


def test_load_candidates_reports_missing_required_field_with_index(tmp_path) -> None:
    """Include the candidate index when a required field is missing."""
    candidate_path = tmp_path / "candidates.json"
    candidate_data = _candidate_mapping()
    candidate_data.pop("address")
    candidate_path.write_text(json.dumps([candidate_data]), encoding="utf-8")

    with pytest.raises(ValueError, match=r"index 0"):
        load_candidates(candidate_path)


def test_load_candidates_reports_unknown_field_with_index(tmp_path) -> None:
    """Include the candidate index when an unknown field is present."""
    candidate_path = tmp_path / "candidates.json"
    candidate_data = _candidate_mapping()
    candidate_data["unexpected"] = "value"
    candidate_path.write_text(json.dumps([candidate_data]), encoding="utf-8")

    with pytest.raises(ValueError, match=r"index 0"):
        load_candidates(candidate_path)


def test_dump_candidates_round_trips_through_loader(tmp_path) -> None:
    """Write candidates to disk and load them back."""
    output_path = tmp_path / "candidates.json"
    original_candidates = load_candidates(_write_source_candidates(tmp_path))

    dump_candidates(output_path, original_candidates)
    loaded_candidates = load_candidates(output_path)

    assert [candidate.to_dict() for candidate in loaded_candidates] == [
        candidate.to_dict() for candidate in original_candidates
    ]


def test_load_candidate_bundle_reads_probe_evidence_from_sensitive_artifact(tmp_path) -> None:
    """Load candidates together with optional probe results from passed-candidate artifacts."""
    candidate_path = tmp_path / "passed_candidates.json"
    candidate_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sensitive": True,
                "passed_candidate_ids": ["candidate-001"],
                "candidates": [
                    {
                        "candidate": _candidate_mapping(),
                        "probe": {
                            "candidate_id": "candidate-001",
                            "home_status": 200,
                            "query_status": 200,
                            "blocked": False,
                            "timeout": False,
                            "error": None,
                            "failure_markers": [],
                            "latency_ms": 10,
                            "checked_at": "2026-05-25T00:00:00Z",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    bundle = load_candidate_bundle(candidate_path)

    assert len(bundle.candidates) == 1
    assert bundle.probe_results[0] is not None
    assert bundle.probe_results[0].candidate_id == "candidate-001"


def _write_source_candidates(tmp_path):
    """Write one source candidate file for round-trip tests."""
    source_path = tmp_path / "source_candidates.json"
    source_path.write_text(json.dumps([_candidate_mapping()]), encoding="utf-8")
    return source_path


def _candidate_mapping() -> dict[str, object]:
    """Build one placeholder candidate mapping."""
    return {
        "source_name": "fixture-source",
        "raw_name": "US Scholar IPv4",
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
        "short_id": "SHORT_ID_PLACEHOLDER",
        "supported": True,
    }
