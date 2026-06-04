"""Tests for the Route workbench model."""

from __future__ import annotations

import json
from pathlib import Path

from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.route_model import add_route_entry
from scholar_outbound_manager.tui.route_model import build_passed_candidate_options
from scholar_outbound_manager.tui.route_model import build_route_workbench_state
from scholar_outbound_manager.tui.route_model import delete_route_entry
from scholar_outbound_manager.tui.route_model import save_route_draft_state
from scholar_outbound_manager.tui.route_model import save_route_entries_to_config_or_selected_routes
from scholar_outbound_manager.tui.route_model import update_route_entry_candidate


def test_build_passed_candidate_options_reads_redacted_labels_only(tmp_path: Path) -> None:
    paths = _write_config_and_artifacts(tmp_path)

    options = build_passed_candidate_options(paths.passed_candidates)

    assert options
    rendered = str(options[0])
    assert options[0].candidate_id == "candidate-001"
    assert "address" not in rendered
    assert "raw_uri" not in rendered
    assert "server_name" not in rendered
    assert len(options) == 1


def test_build_route_workbench_state_creates_default_route_when_missing(tmp_path: Path) -> None:
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
                "filters: {include_keywords: [], exclude_keywords: [], deprioritize_keywords: []}",
                "probe: {timeout_seconds: 5, concurrency: 1, cache_ttl_hours: 24, failure_backoff_hours: 24, allow_network_probe: false}",
                "xray: {binary_path: /usr/local/bin/xray, runtime_dir: .runtime, local_socks_host: 127.0.0.1, local_socks_port: 19080}",
                "output: {outbounds_path: generated/outbounds.json, routes_path: generated/routes.json, manifest_path: generated/manifest.json, history_dir: state_data/history}",
                "generation: {tag_prefix: scholar-, max_passed_nodes: 2, fallback_blackhole_tag: blocked, previous_output_max_age_hours: 24}",
                "routing: {mode: dedicated_inbound, inbound_tags: [scholar-in], fail_closed: true}",
            ]
        ),
        encoding="utf-8",
    )
    paths = resolve_user_data_paths(config_path)

    state = build_route_workbench_state(config_path=str(config_path), user_data_paths=paths)

    assert len(state.entries) == 1
    assert state.entries[0].name == "Scholar"
    assert state.entries[0].listen_port == 19080


def test_existing_route_entries_are_loaded_and_stale_candidates_are_marked(tmp_path: Path) -> None:
    paths = _write_config_and_artifacts(tmp_path, candidate_id="candidate-stale")

    state = build_route_workbench_state(config_path=str(paths.config_path), user_data_paths=paths)

    assert state.entries[0].candidate_id == "candidate-stale"
    assert state.entries[0].error == "stale candidate"
    assert state.can_apply is False
    assert state.candidate_selector_enabled is True


def test_delete_last_route_is_refused(tmp_path: Path) -> None:
    paths = _write_config_and_artifacts(tmp_path)
    state = build_route_workbench_state(config_path=str(paths.config_path), user_data_paths=paths)

    same_state, warning = delete_route_entry(state)

    assert same_state.entries == state.entries
    assert warning == "At least one route must remain configured."


def test_artifact_lineage_mismatch_disables_apply(tmp_path: Path) -> None:
    paths = _write_config_and_artifacts(tmp_path)
    probe_payload = json.loads(paths.probe_summary.read_text(encoding="utf-8"))
    probe_payload["source_candidates_hash"] = "deadbeefdeadbeef"
    atomic_write_json(paths.probe_summary, probe_payload)

    state = build_route_workbench_state(config_path=str(paths.config_path), user_data_paths=paths)

    assert state.can_apply is False
    assert state.stale_warning is not None
    assert state.candidate_selector_enabled is False
    assert state.candidate_selector_message == "Testing artifacts are stale. Run Test Nodes before changing routes."


def test_missing_passed_candidates_disables_selector(tmp_path: Path) -> None:
    paths = _write_config_and_artifacts(tmp_path)
    paths.passed_candidates.unlink()

    state = build_route_workbench_state(config_path=str(paths.config_path), user_data_paths=paths)

    assert state.candidate_selector_enabled is False
    assert state.candidate_selector_message == "No passed candidates available. Run Test Nodes first."
    assert state.can_apply is False


def test_choosing_passed_candidate_updates_route_draft(tmp_path: Path) -> None:
    paths = _write_config_and_artifacts(tmp_path, candidate_id=None)
    state = build_route_workbench_state(config_path=str(paths.config_path), user_data_paths=paths)

    updated = update_route_entry_candidate(state, entry_index=0, candidate_id="candidate-001")

    assert updated.entries[0].candidate_id == "candidate-001"
    assert updated.entries[0].candidate_label is not None
    assert updated.entries[0].protocol == "vless"


def test_route_refresh_preserves_selected_candidate_from_draft_store(tmp_path: Path) -> None:
    paths = _write_config_and_artifacts(tmp_path, candidate_id=None)
    state = build_route_workbench_state(config_path=str(paths.config_path), user_data_paths=paths)
    updated = update_route_entry_candidate(state, entry_index=0, candidate_id="candidate-001")
    save_route_draft_state(user_data_paths=paths, entries=updated.entries)

    refreshed = build_route_workbench_state(config_path=str(paths.config_path), user_data_paths=paths)

    assert refreshed.entries[0].candidate_id == "candidate-001"
    assert refreshed.entries[0].candidate_label is not None
    assert "missing a passed candidate" not in refreshed.validation_errors
    assert refreshed.can_apply is True


def test_save_route_entries_writes_config_and_local_route_artifacts(tmp_path: Path) -> None:
    paths = _write_config_and_artifacts(tmp_path, candidate_id=None)
    state = build_route_workbench_state(config_path=str(paths.config_path), user_data_paths=paths)
    updated = update_route_entry_candidate(state, entry_index=0, candidate_id="candidate-001")

    message = save_route_entries_to_config_or_selected_routes(
        str(paths.config_path),
        user_data_paths=paths,
        entries=updated.entries,
    )

    config_text = paths.config_path.read_text(encoding="utf-8")
    selected_routes = json.loads(paths.selected_routes.read_text(encoding="utf-8"))
    assert "candidate-001" in config_text
    assert selected_routes["routes"][0]["candidate_id"] == "candidate-001"
    assert "saved to config.yaml" in message


def test_add_route_suggests_next_port(tmp_path: Path) -> None:
    paths = _write_config_and_artifacts(tmp_path)
    state = build_route_workbench_state(config_path=str(paths.config_path), user_data_paths=paths)

    updated = add_route_entry(state)

    assert len(updated.entries) == 2
    assert updated.entries[-1].listen_port == 19081


def _write_config_and_artifacts(tmp_path: Path, *, candidate_id: str | None = "candidate-001"):
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
                "filters: {include_keywords: [], exclude_keywords: [], deprioritize_keywords: []}",
                "probe: {timeout_seconds: 5, concurrency: 1, cache_ttl_hours: 24, failure_backoff_hours: 24, allow_network_probe: false}",
                "xray: {binary_path: /usr/local/bin/xray, runtime_dir: .runtime, local_socks_host: 127.0.0.1, local_socks_port: 19080}",
                "sidecar: {service_name: scholar-outbound-sidecar.service}",
                f"route: {{mode: single, entries: [{{name: Scholar, candidate_id: {candidate_id if candidate_id else 'null'}, listen_host: 127.0.0.1, listen_port: 19080, enabled: true}}]}}",
                "output: {outbounds_path: generated/outbounds.json, routes_path: generated/routes.json, manifest_path: generated/manifest.json, history_dir: state_data/history}",
                "generation: {tag_prefix: scholar-, max_passed_nodes: 2, fallback_blackhole_tag: blocked, previous_output_max_age_hours: 24}",
                "routing: {mode: dedicated_inbound, inbound_tags: [scholar-in], fail_closed: true}",
            ]
        ),
        encoding="utf-8",
    )
    paths = resolve_user_data_paths(config_path)
    candidates_payload = _candidate_payload(
        run_id="run-candidates",
        artifact_type="candidates",
        probe=False,
    )
    atomic_write_json(paths.candidates, candidates_payload)
    candidates_hash = compute_artifact_hash(candidates_payload)
    atomic_write_json(
        paths.probe_summary,
        {
            "schema_version": 1,
            "artifact_type": "probe_summary",
            "run_id": "run-probe",
            "created_at": "2026-06-05T00:00:00Z",
            "source_candidates_hash": candidates_hash,
            "records": [
                {
                    "candidate_id": "candidate-001",
                    "attempted": True,
                    "passed": True,
                    "skipped": False,
                    "summary": {
                        "result": {
                            "candidate_id": "candidate-001",
                            "home_status": 200,
                            "query_status": 200,
                            "latency_ms": 1200,
                            "failure_markers": [],
                        }
                    },
                }
            ],
        },
    )
    atomic_write_json(
        paths.passed_candidates,
        _candidate_payload(
            run_id="run-passed",
            artifact_type="passed_candidates",
            probe=True,
            source_candidates_hash=candidates_hash,
        ),
    )
    return paths


def _candidate_payload(*, run_id: str, artifact_type: str, probe: bool, source_candidates_hash: str | None = None) -> dict[str, object]:
    candidate = {
        "candidate_id": "candidate-001",
        "candidate": {
            "source_name": "fixture",
            "raw_name": "US Relay 01",
            "protocol": "vless",
            "address": "example.invalid",
            "port": 443,
            "supported": True,
            "extra": {"display_name": "US Relay 01"},
        },
        "probe": {
            "candidate_id": "candidate-001",
            "home_status": 200,
            "query_status": 200,
            "latency_ms": 1200,
            "failure_markers": [],
        },
    }
    failed_candidate = {
        "candidate_id": "candidate-002",
        "candidate": {
            "source_name": "fixture",
            "raw_name": "Blocked Relay 02",
            "protocol": "vless",
            "address": "example.invalid",
            "port": 443,
            "supported": True,
            "extra": {"display_name": "Blocked Relay 02"},
        },
        "probe": {
            "candidate_id": "candidate-002",
            "home_status": 403,
            "query_status": 403,
            "latency_ms": 1500,
            "failure_markers": ["stage_query_blocked"],
        },
    }
    unsupported_candidate = {
        "candidate_id": "candidate-003",
        "candidate": {
            "source_name": "fixture",
            "raw_name": "Experimental Relay 03",
            "protocol": "hysteria2",
            "address": "example.invalid",
            "port": 443,
            "supported": False,
            "extra": {"display_name": "Experimental Relay 03"},
        },
        "probe": {
            "candidate_id": "candidate-003",
            "home_status": 200,
            "query_status": 200,
            "latency_ms": 900,
            "failure_markers": [],
        },
    }
    payload = {
        "schema_version": 1,
        "artifact_type": artifact_type,
        "run_id": run_id,
        "created_at": "2026-06-05T00:00:00Z",
        "candidates": [candidate, failed_candidate, unsupported_candidate],
    }
    if probe:
        payload["source_candidates_hash"] = source_candidates_hash
        payload["source_probe_summary_hash"] = "aabbccddeeff0011"
        payload["passed_candidate_ids"] = ["candidate-001"]
    return payload
