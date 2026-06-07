from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.tui.events import ProbeProcessCompleted
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.reducer import reduce_app_state
from scholar_outbound_manager.tui.state import AppState as _AppState
from scholar_outbound_manager.tui.state import KeyHint as _KeyHint
from scholar_outbound_manager.tui.state import NavState as _NavState
from scholar_outbound_manager.tui.state import RouteStoreState as _RouteStoreState
from scholar_outbound_manager.tui.state import StatusBarState as _StatusBarState
from scholar_outbound_manager.tui.state import TestingArtifactsState as _TestingArtifactsState
from scholar_outbound_manager.tui.testing_jobs import idle_testing_job_state
from scholar_outbound_manager.tui.testing_runtime import TestingSummary as _TestingSummary
from scholar_outbound_manager.tui.testing_runtime import idle_testing_runtime
from scholar_outbound_manager.tui.state import TestingStoreState as _TestingStoreState
from scholar_outbound_manager.tui.testing_store import build_testing_store_state


def test_probe_process_completed_sets_phase_finalizing_not_completed(tmp_path: Path) -> None:
    state = _state(tmp_path)

    new_state, effects = reduce_app_state(state, ProbeProcessCompleted(job_id="probe-1", exit_code=0))

    assert new_state.testing.runtime.phase == "finalizing"
    assert new_state.testing.runtime.process_completed is True
    assert new_state.testing.runtime.completion_message is None
    assert effects


def test_artifact_reconciliation_sets_completed_only_after_attempted_records(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    candidates = _supported_candidates_payload()
    atomic_write_json(paths.candidates, candidates)
    source_hash = compute_artifact_hash(candidates)
    atomic_write_json(
        paths.probe_summary,
        {
            "schema_version": 1,
            "source_candidates_hash": source_hash,
            "attempted_count": 1,
            "passed_count": 1,
            "failed_count": 0,
            "skipped_count": 0,
            "parallel_workers": 4,
            "records": [
                {
                    "candidate_id": "candidate-001",
                    "attempted": True,
                    "passed": True,
                    "summary": {"result": {"candidate_id": "candidate-001", "home_status": 200, "query_status": 200, "failure_markers": []}},
                }
            ],
        },
    )
    atomic_write_json(
        paths.passed_candidates,
        {
            "schema_version": 1,
            "source_candidates_hash": source_hash,
            "passed_candidate_ids": ["candidate-001"],
            "candidates": [],
        },
    )

    runtime = replace(idle_testing_runtime(), phase="finalizing", process_completed=True, process_exit_code=0)
    store = build_testing_store_state(config_path=str(config_path), user_data_paths=paths, previous_runtime=runtime)

    assert store.runtime.phase == "completed"
    assert store.runtime.completion_message == "Probe completed and artifacts reconciled."


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("user_data_dir: state_data\nprobe:\n  concurrency: 4\n", encoding="utf-8")
    return config_path


def _supported_candidates_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": "hash-ok",
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


def _state(tmp_path: Path) -> _AppState:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    return _AppState(
        nav=_NavState(active_page="testing"),
        settings={},
        testing=_TestingStoreState(
            artifacts=_TestingArtifactsState(True, False, False, True, (), {}),
            rows=(),
            selected_index=0,
            job=idle_testing_job_state(),
            runtime=idle_testing_runtime(),
            summary=_TestingSummary(True, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, "ready", "not_tested", 1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 1, 0, 0, "all_candidates"),
            stale_warning=None,
            recent_events=(),
        ),
        route=_RouteStoreState((), 0, (), (), False, None, {}),
        logs={},
        modal=None,
        status_bar=_StatusBarState(message=None, level=None, keys=(_KeyHint("q", "Quit"),)),
        user_data_paths=paths,
        config_path=config_path,
    )
