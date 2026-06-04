"""Tests for Testing screen rendering helpers."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.tui.app import render_tab_text
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.testing_model import build_testing_screen_state
from scholar_outbound_manager.tui.view_model import build_testing_table_model


def test_testing_table_model_has_candidate_columns() -> None:
    model = build_testing_table_model(
        {
            "testing": {
                "rows": [
                    {
                        "index": 1,
                        "region_hint": "US",
                        "label": "US relay",
                        "protocol": "vless",
                        "passed": True,
                        "status_icon": "PASS",
                        "latency_ms": 1200,
                        "home_status": 200,
                        "query_status": 200,
                        "stage": "full_access",
                        "markers": (),
                    }
                ]
            }
        }
    )

    assert model.columns == ["status", "#", "region", "label", "protocol", "latency", "home", "query", "stage", "markers"]
    assert model.rows[0][0] == "PASS"
    assert "scholar-outbound-manager probe" not in str(model.rows)


def test_render_testing_page_uses_workbench_language_not_command_dump() -> None:
    rendered = render_tab_text(
        "Testing",
        {
            "testing": {
                "job_state": "idle",
                "progress_current": 1,
                "progress_total": 3,
                "summary": {
                    "subscription_configured": True,
                    "last_fetch_status": "ready",
                    "candidate_count": 3,
                    "supported_count": 2,
                    "experimental_disabled_count": 1,
                    "attempted_count": 2,
                    "passed_count": 1,
                    "failed_count": 1,
                },
                "rows": [
                    {
                        "index": 18,
                        "region_hint": "US",
                        "label": "US relay",
                        "protocol": "vless",
                        "status_icon": "PASS",
                        "passed": True,
                        "latency_ms": 1225,
                        "home_status": 200,
                        "query_status": 200,
                        "stage": "full_access",
                        "markers": (),
                    }
                ],
                "inspector": {
                    "label": "US relay",
                    "region_hint": "US",
                    "protocol": "vless",
                    "candidate_id": "candidate-018",
                    "scholar_stage": "full_access",
                    "home_status": 200,
                    "query_status": 200,
                    "latency_ms": 1225,
                    "markers": (),
                    "selected_for_route": False,
                    "explanation": "Home and query both passed without failure markers.",
                    "artifact_warning": "Artifact lineage mismatch.\nThe current probe summary does not match the current candidates artifact.\nRun Test Nodes to rebuild probe_summary and passed_candidates.",
                },
                "log_lines": ["Probe Candidates completed successfully."],
            }
        },
    )

    assert "Fetch Subscription" in rendered
    assert "Test Nodes" in rendered
    assert "Retest Failed" in rendered
    assert "Selected candidate" in rendered
    assert "Recent events" in rendered
    assert "Artifact lineage mismatch." in rendered
    assert "scholar-outbound-manager probe" not in rendered


def test_testing_table_model_supports_run_status() -> None:
    model = build_testing_table_model(
        {
            "testing": {
                "rows": [
                    {
                        "index": 1,
                        "region_hint": "JP",
                        "label": "JP relay",
                        "protocol": "vless",
                        "passed": False,
                        "status_icon": "RUN",
                        "latency_ms": None,
                        "home_status": None,
                        "query_status": None,
                        "stage": "running",
                        "markers": (),
                    }
                ]
            }
        }
    )

    assert model.rows[0][0] == "RUN"


def test_testing_state_reports_timeout_diagnosis_and_stale_artifacts(tmp_path: Path) -> None:
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
    candidates_payload = {
        "schema_version": 1,
        "artifact_type": "candidates",
        "run_id": "run-candidates",
        "created_at": "2026-06-05T00:00:00Z",
        "candidates": [
            {
                "candidate_id": "candidate-001",
                "candidate": {
                    "source_name": "fixture",
                    "raw_name": "US Relay 01",
                    "protocol": "vless",
                    "address": "example.invalid",
                    "port": 443,
                    "supported": True,
                    "extra": {"display_name": "US Relay 01"},
                }
            }
        ],
    }
    from scholar_outbound_manager.state.atomic_write import atomic_write_json

    atomic_write_json(paths.candidates, candidates_payload)
    atomic_write_json(
        paths.probe_summary,
        {
            "schema_version": 1,
            "artifact_type": "probe_summary",
            "run_id": "run-probe",
            "created_at": "2026-06-05T00:00:00Z",
            "source_candidates_hash": "deadbeefdeadbeef",
            "records": [],
        },
    )
    paths.action_journal.parent.mkdir(parents=True, exist_ok=True)
    paths.action_journal.write_text(
        '{"operation_key":"probe","title":"Probe Candidates","exit_code":124,"succeeded":false,"summary":"Probe timed out or was interrupted. Artifacts may be stale. Run Test Nodes again or increase testing timeout."}\n',
        encoding="utf-8",
    )
    state = build_testing_screen_state(config_path=str(config_path), user_data_paths=paths)

    assert state.artifacts_stale is True
    assert state.last_exit_code == 124
    assert "timed out or was interrupted" in str(state.last_failure_reason)


def test_testing_state_clears_stale_warning_after_successful_probe(tmp_path: Path) -> None:
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
    from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
    from scholar_outbound_manager.state.atomic_write import atomic_write_json

    candidates_payload = {
        "schema_version": 1,
        "artifact_type": "candidates",
        "run_id": "run-candidates",
        "created_at": "2026-06-05T00:00:00Z",
        "candidates": [
            {
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
                    "latency_ms": 800,
                    "failure_markers": [],
                },
            }
        ],
    }
    candidates_hash = compute_artifact_hash(candidates_payload)
    atomic_write_json(paths.candidates, candidates_payload)
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
                    "summary": {"result": {"candidate_id": "candidate-001", "home_status": 200, "query_status": 200, "latency_ms": 800, "failure_markers": []}},
                }
            ],
        },
    )
    atomic_write_json(
        paths.passed_candidates,
        {
            "schema_version": 1,
            "artifact_type": "passed_candidates",
            "run_id": "run-passed",
            "created_at": "2026-06-05T00:00:00Z",
            "source_candidates_hash": candidates_hash,
            "source_probe_summary_hash": "feedfacefeedface",
            "passed_candidate_ids": ["candidate-001"],
            "candidates": candidates_payload["candidates"],
        },
    )
    paths.action_journal.parent.mkdir(parents=True, exist_ok=True)
    paths.action_journal.write_text(
        '{"operation_key":"probe","title":"Probe Candidates","exit_code":0,"succeeded":true,"summary":"Probe Candidates completed successfully."}\n',
        encoding="utf-8",
    )

    state = build_testing_screen_state(config_path=str(config_path), user_data_paths=paths)

    assert state.artifacts_stale is False
    assert state.last_failure_reason is None
