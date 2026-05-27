"""Tests for artifact lineage and consistency helpers."""

from __future__ import annotations

import json
from pathlib import Path

from scholar_outbound_manager.state.artifact_lineage import build_probe_explanation
from scholar_outbound_manager.state.artifact_lineage import check_artifact_consistency
from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.state.artifact_lineage import generate_run_id


def test_compute_artifact_hash_is_stable_for_same_payload() -> None:
    payload = {"b": 2, "a": 1}
    assert compute_artifact_hash(payload) == compute_artifact_hash({"a": 1, "b": 2})


def test_generate_run_id_has_prefix() -> None:
    run_id = generate_run_id("probe")
    assert run_id.startswith("probe-")


def test_consistency_check_passes_for_matching_artifacts(tmp_path: Path) -> None:
    candidates_path, probe_path, passed_path = _write_matching_artifacts(tmp_path)

    report = check_artifact_consistency(
        candidates_path=candidates_path,
        probe_summary_path=probe_path,
        passed_candidates_path=passed_path,
    )

    assert report["probe_summary_source_candidates_match"] is True
    assert report["passed_candidates_source_candidates_match"] is True
    assert report["passed_candidates_source_probe_summary_match"] is True
    assert report["overall_consistent"] is True


def test_consistency_check_detects_mismatch(tmp_path: Path) -> None:
    candidates_path, probe_path, passed_path = _write_matching_artifacts(tmp_path)
    passed_payload = json.loads(passed_path.read_text(encoding="utf-8"))
    passed_payload["source_probe_summary_hash"] = "deadbeefdeadbeef"
    passed_path.write_text(json.dumps(passed_payload), encoding="utf-8")

    report = check_artifact_consistency(
        candidates_path=candidates_path,
        probe_summary_path=probe_path,
        passed_candidates_path=passed_path,
    )

    assert report["passed_candidates_source_probe_summary_match"] is False
    assert report["overall_consistent"] is False


def test_consistency_check_reports_legacy_unknown(tmp_path: Path) -> None:
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(json.dumps({"schema_version": 1, "candidates": []}), encoding="utf-8")

    report = check_artifact_consistency(candidates_path=candidates_path)

    assert report["overall_consistent"] is None
    assert report["warnings"]


def test_probe_explanation_filters_redacted_labels() -> None:
    payload = {
        "schema_version": 1,
        "artifact_type": "probe_summary",
        "run_id": "probe-1",
        "created_at": "2026-05-27T00:00:00Z",
        "records": [
            {
                "index": 0,
                "candidate_id": "candidate-001",
                "candidate_name": "US-LA-01",
                "attempted": True,
                "passed": False,
                "skipped": False,
                "skip_reason": None,
                "summary": {"result": {"home_status": 403, "query_status": 403, "failure_markers": ["stage_home_blocked"]}},
            }
        ],
    }

    explanation = build_probe_explanation(payload, label_regex="US-LA")

    rendered = json.dumps(explanation, ensure_ascii=False)
    assert explanation["record_count"] == 1
    assert "US-LA-01" in rendered
    assert "raw_uri" not in rendered


def _write_matching_artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    candidates_payload = {
        "schema_version": 1,
        "artifact_type": "candidates",
        "run_id": "fetch-1",
        "created_at": "2026-05-27T00:00:00Z",
        "candidates": [{"raw_name": "US-LA-01"}],
    }
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(json.dumps(candidates_payload), encoding="utf-8")
    candidates_hash = compute_artifact_hash(candidates_payload)

    probe_payload = {
        "schema_version": 1,
        "artifact_type": "probe_summary",
        "run_id": "probe-1",
        "created_at": "2026-05-27T00:01:00Z",
        "source_candidates_hash": candidates_hash,
        "source_candidates_run_id": "fetch-1",
        "records": [],
    }
    probe_path = tmp_path / "probe_summary.json"
    probe_path.write_text(json.dumps(probe_payload), encoding="utf-8")
    probe_hash = compute_artifact_hash(probe_payload)

    passed_payload = {
        "schema_version": 1,
        "artifact_type": "passed_candidates",
        "run_id": "probe-1",
        "created_at": "2026-05-27T00:01:00Z",
        "source_candidates_hash": candidates_hash,
        "source_candidates_run_id": "fetch-1",
        "source_probe_summary_hash": probe_hash,
        "source_probe_summary_run_id": "probe-1",
        "candidates": [],
    }
    passed_path = tmp_path / "passed_candidates.json"
    passed_path.write_text(json.dumps(passed_payload), encoding="utf-8")
    return candidates_path, probe_path, passed_path
