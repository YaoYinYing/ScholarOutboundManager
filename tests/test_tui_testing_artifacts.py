from __future__ import annotations

import json
from pathlib import Path

from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.testing_artifacts import load_testing_artifacts


def test_load_testing_artifacts_reads_full_passed_candidates_artifact(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    candidates = _candidates_payload()
    atomic_write_json(paths.candidates, candidates)
    source_hash = compute_artifact_hash(candidates)
    atomic_write_json(paths.probe_summary, _probe_payload(source_hash))
    atomic_write_json(paths.passed_candidates, _passed_candidates_payload(source_hash))

    artifacts = load_testing_artifacts(paths)

    assert artifacts.lineage_consistent is True
    assert "candidate-001" in artifacts.passed_ids
    assert artifacts.probe_results_by_candidate_id["candidate-001"]["attempted"] is True


def test_load_testing_artifacts_marks_lineage_mismatch(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    candidates = _candidates_payload()
    atomic_write_json(paths.candidates, candidates)
    atomic_write_json(paths.probe_summary, _probe_payload("deadbeefdeadbeef"))
    atomic_write_json(paths.passed_candidates, _passed_candidates_payload("deadbeefdeadbeef"))

    artifacts = load_testing_artifacts(paths)

    assert artifacts.lineage_consistent is False
    assert artifacts.warnings


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("user_data_dir: state_data\n", encoding="utf-8")
    return config_path


def _candidates_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "candidates": [
            {
                "candidate_id": "candidate-001",
                "candidate": {
                    "source_name": "fixture",
                    "raw_name": "US Relay",
                    "protocol": "vless",
                    "address": "example.invalid",
                    "port": 443,
                    "supported": True,
                },
            }
        ],
    }


def _probe_payload(source_hash: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_candidates_hash": source_hash,
        "records": [
            {
                "candidate_id": "candidate-001",
                "attempted": True,
                "passed": True,
                "summary": {"result": {"candidate_id": "candidate-001", "home_status": 200, "query_status": 200, "failure_markers": []}},
            }
        ],
    }


def _passed_candidates_payload(source_hash: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_candidates_hash": source_hash,
        "candidates": [
            {
                "candidate_id": "candidate-001",
                "candidate": {
                    "source_name": "fixture",
                    "raw_name": "US Relay",
                    "protocol": "vless",
                    "address": "example.invalid",
                    "port": 443,
                    "supported": True,
                },
                "probe": {"candidate_id": "candidate-001", "home_status": 200, "query_status": 200, "failure_markers": []},
            }
        ],
    }
