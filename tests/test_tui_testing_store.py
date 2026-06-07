from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.testing_events import TestingEvent
from scholar_outbound_manager.tui.testing_store import apply_testing_event
from scholar_outbound_manager.tui.testing_store import build_testing_store_state


def test_build_testing_store_state_marks_stale_rows_for_lineage_mismatch(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    candidates = _candidates_payload()
    atomic_write_json(paths.candidates, candidates)
    atomic_write_json(paths.probe_summary, _probe_payload("deadbeefdeadbeef"))
    atomic_write_json(paths.passed_candidates, _passed_candidates_payload("deadbeefdeadbeef"))

    state = build_testing_store_state(config_path=str(config_path), user_data_paths=paths)

    assert state.artifacts.lineage_consistent is False
    assert state.stale_warning is not None
    assert state.rows[0].status_icon == "STALE"


def test_apply_testing_event_updates_rows_and_redacts_recent_events(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    candidates = _candidates_payload()
    atomic_write_json(paths.candidates, candidates)
    source_hash = compute_artifact_hash(candidates)
    atomic_write_json(paths.probe_summary, _probe_payload(source_hash))
    atomic_write_json(paths.passed_candidates, _passed_candidates_payload(source_hash))
    state = build_testing_store_state(config_path=str(config_path), user_data_paths=paths)

    updated = apply_testing_event(
        state,
        TestingEvent(
            event_type="candidate_result",
            candidate_id="candidate-001",
            index=0,
            label="US Relay",
            region_hint="US",
            protocol="vless",
            status="PASS",
            home_status=200,
            query_status=200,
            stage="full_access",
            markers=(),
            latency_ms=321,
            current=1,
            total=1,
            message="vless://uuid@example.invalid:443 path=/secret token=secret",
        ),
    )

    assert updated.rows[0].status_icon == "PASS"
    assert updated.summary.passed_count == 1
    assert "vless://" not in updated.recent_events[-1]
    assert "token=secret" not in updated.recent_events[-1]


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
