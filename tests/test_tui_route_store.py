from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.route_model import save_route_draft_state
from scholar_outbound_manager.tui.route_store import build_route_store_state
from scholar_outbound_manager.tui.route_store import choose_route_candidate


def test_choose_route_candidate_updates_store_and_clears_missing_candidate_error(tmp_path: Path) -> None:
    config_path = _write_route_config(tmp_path, candidate_id=None)
    paths = resolve_user_data_paths(config_path)
    _write_route_artifacts(paths)
    state = build_route_store_state(config_path=str(config_path), user_data_paths=paths)

    updated = choose_route_candidate(state, route_id="route-1", candidate_id="candidate-001")

    assert updated.entries[0].candidate_id == "candidate-001"
    assert updated.apply_available is True
    assert not any("missing a passed candidate" in error for error in updated.validation_errors)


def test_refresh_after_saved_route_choice_preserves_candidate(tmp_path: Path) -> None:
    config_path = _write_route_config(tmp_path, candidate_id=None)
    paths = resolve_user_data_paths(config_path)
    _write_route_artifacts(paths)
    state = build_route_store_state(config_path=str(config_path), user_data_paths=paths)
    updated = choose_route_candidate(state, route_id="route-1", candidate_id="candidate-001")
    save_route_draft_state(user_data_paths=paths, entries=list(updated.entries))

    refreshed = build_route_store_state(config_path=str(config_path), user_data_paths=paths)

    assert refreshed.entries[0].candidate_id == "candidate-001"
    assert refreshed.apply_available is True


def test_stale_artifacts_preserve_route_candidate_but_disable_apply(tmp_path: Path) -> None:
    config_path = _write_route_config(tmp_path, candidate_id="candidate-001")
    paths = resolve_user_data_paths(config_path)
    _write_route_artifacts(paths, stale=True)

    state = build_route_store_state(config_path=str(config_path), user_data_paths=paths)

    assert state.entries[0].candidate_id == "candidate-001"
    assert state.stale_warning is not None
    assert state.apply_available is False


def _write_route_config(tmp_path: Path, *, candidate_id: str | None) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "subscriptions:",
                "  - name: fixture",
                "    url: https://example.invalid/subscription",
                "    format: auto",
                "    enabled: true",
                "    headers: {}",
                "user_data_dir: state_data",
                "probe: {timeout_seconds: 5, concurrency: 1, cache_ttl_hours: 24, failure_backoff_hours: 24, allow_network_probe: false}",
                "xray: {binary_path: /usr/local/bin/xray, runtime_dir: .runtime, local_socks_host: 127.0.0.1, local_socks_port: 19080}",
                "sidecar: {service_name: scholar-outbound-sidecar.service}",
                f"route: {{mode: single, entries: [{{route_id: route-1, name: Scholar, candidate_id: {candidate_id if candidate_id else 'null'}, listen_host: 127.0.0.1, listen_port: 19080, enabled: true}}]}}",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _write_route_artifacts(paths, *, stale: bool = False) -> None:
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
    probe_hash = "deadbeefdeadbeef" if stale else source_hash
    atomic_write_json(
        paths.probe_summary,
        {
            "schema_version": 1,
            "source_candidates_hash": probe_hash,
            "records": [],
        },
    )
    atomic_write_json(
        paths.passed_candidates,
        {
            "schema_version": 1,
            "source_candidates_hash": probe_hash,
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
                    "probe": {
                        "candidate_id": "candidate-001",
                        "home_status": 200,
                        "query_status": 200,
                        "failure_markers": [],
                    },
                }
            ],
        },
    )
