from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.testing_events import TestingEvent
from scholar_outbound_manager.tui.testing_store import apply_testing_event
from scholar_outbound_manager.tui.testing_store import build_testing_store_state


def test_fake_probe_event_moves_row_to_run_without_toast_side_effects(tmp_path: Path) -> None:
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
            event_type="candidate_started",
            candidate_id="candidate-001",
            index=0,
            label="US Relay",
            region_hint="US",
            protocol="vless",
            status="RUN",
            home_status=None,
            query_status=None,
            stage="probing",
            markers=(),
            latency_ms=None,
            current=0,
            total=1,
            message="US Relay started",
        ),
    )

    assert updated.rows[0].status_icon == "RUN"
    assert updated.recent_events[-1] == "US Relay started"
    assert updated.job.message == "US Relay started"


def test_fake_probe_completion_updates_counts(tmp_path: Path) -> None:
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
            status="FAIL",
            home_status=403,
            query_status=403,
            stage="blocked",
            markers=("query_blocked",),
            latency_ms=500,
            current=1,
            total=1,
            message="US Relay -> FAIL",
        ),
    )

    assert updated.rows[0].status_icon == "FAIL"
    assert updated.summary.failed_count == 1
    assert updated.job.failed == 1


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("user_data_dir: state_data\nexperimental_hysteria2: false\n", encoding="utf-8")
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
        "records": [],
    }


def _passed_candidates_payload(source_hash: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_candidates_hash": source_hash,
        "candidates": [],
    }
