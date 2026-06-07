from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.testing_runtime import idle_testing_runtime
from scholar_outbound_manager.tui.testing_store import build_testing_store_state


def test_testing_summary_distinguishes_total_testable_experimental_and_visible(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    candidates = {
        "schema_version": 1,
        "candidates": [
            *[
                {
                    "candidate_id": f"vless-{index:03d}",
                    "candidate": {
                        "source_name": "fixture",
                        "raw_name": f"US Relay {index}",
                        "protocol": "vless",
                        "address": "example.invalid",
                        "port": 443,
                        "supported": True,
                    },
                }
                for index in range(30)
            ],
            *[
                {
                    "candidate_id": f"hy2-{index:03d}",
                    "candidate": {
                        "source_name": "fixture",
                        "raw_name": f"JP Relay {index}",
                        "protocol": "hysteria2",
                        "address": "example.invalid",
                        "port": 443,
                        "supported": False,
                    },
                }
                for index in range(17)
            ],
        ],
    }
    atomic_write_json(paths.candidates, candidates)

    store = build_testing_store_state(config_path=str(config_path), user_data_paths=paths)

    assert store.summary.total_candidates == 47
    assert store.summary.testable_candidates == 30
    assert store.summary.experimental_disabled == 17
    assert store.summary.visible_rows == 47


def test_zero_attempted_after_process_success_becomes_warning_not_completed(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    candidates = {
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
    atomic_write_json(paths.candidates, candidates)
    source_hash = compute_artifact_hash(candidates)
    atomic_write_json(paths.probe_summary, {"schema_version": 1, "source_candidates_hash": source_hash, "attempted_count": 0, "records": []})
    atomic_write_json(paths.passed_candidates, {"schema_version": 1, "source_candidates_hash": source_hash, "passed_candidate_ids": [], "candidates": []})

    runtime = replace(idle_testing_runtime(), phase="finalizing", process_completed=True, process_exit_code=0)
    store = build_testing_store_state(config_path=str(config_path), user_data_paths=paths, previous_runtime=runtime)

    assert store.runtime.phase == "warning"
    assert "no candidate results were loaded" in (store.runtime.warning_message or "").lower()


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("user_data_dir: state_data\nexperimental:\n  enable_hysteria2: false\n", encoding="utf-8")
    return config_path
