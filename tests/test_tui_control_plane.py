"""Tests for TUI control-plane state loading."""

from __future__ import annotations

import builtins
import json
from pathlib import Path
from unittest.mock import patch

from scholar_outbound_manager.selection import build_selected_candidate_artifact
from scholar_outbound_manager.selection import load_candidate_payload
from scholar_outbound_manager.selection import select_candidate_by_index
from scholar_outbound_manager.tui.control_plane import control_plane_state_to_dict
from scholar_outbound_manager.tui.control_plane import load_control_plane_state


def test_load_control_plane_state_does_not_import_textual(tmp_path: Path, monkeypatch) -> None:
    """Control-plane state should stay pure Python and not depend on Textual."""
    candidates_path = _write_passed_candidates(tmp_path)
    config_path = _write_config(tmp_path)
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("textual"):
            raise AssertionError("load_control_plane_state should not import Textual")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    state = load_control_plane_state(
        config_path=str(config_path),
        candidates_path=str(candidates_path),
        passed_candidates_path=str(candidates_path),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(tmp_path / "selected_candidate.json"),
        session_path=str(tmp_path / "tui_session.json"),
    )

    assert state.config_state.valid is True


def test_control_plane_state_contains_expected_sections_and_command_previews(tmp_path: Path) -> None:
    """Load the required review-safe control-plane sections."""
    candidates_path = _write_passed_candidates(tmp_path)
    config_path = _write_config(tmp_path)

    state = load_control_plane_state(
        config_path=str(config_path),
        candidates_path=str(candidates_path),
        passed_candidates_path=str(candidates_path),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(tmp_path / "selected_candidate.json"),
        session_path=str(tmp_path / "tui_session.json"),
    )

    assert state.config_state.exists is True
    assert state.config_form_state.fields
    assert state.artifact_state.candidates_exists is True
    assert state.command_state.fetch_command_preview.startswith("scholar-outbound-manager fetch")
    assert state.command_state.select_command_preview.startswith("scholar-outbound-manager select choose")
    assert state.workflow_state.next_recommended_action
    assert "Why:" in state.workflow_state.next_recommended_action
    assert state.operation_availability.fetch_available is True
    assert state.operation_availability.config_save_available is True


def test_control_plane_state_does_not_leak_secret_values(tmp_path: Path) -> None:
    """No review-safe control-plane field should expose raw secrets."""
    candidates_path = _write_passed_candidates(tmp_path)
    config_path = _write_config(tmp_path, subscription_url="https://example.invalid/subscription-token")

    state = load_control_plane_state(
        config_path=str(config_path),
        candidates_path=str(candidates_path),
        passed_candidates_path=str(candidates_path),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(tmp_path / "selected_candidate.json"),
        session_path=str(tmp_path / "tui_session.json"),
    )

    rendered = json.dumps(control_plane_state_to_dict(state), ensure_ascii=False, sort_keys=True)
    assert "https://example.invalid/subscription-token" not in rendered
    assert "vless://" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "PASSWORD_PLACEHOLDER" not in rendered


def test_control_plane_loads_last_action_from_review_safe_journal(tmp_path: Path) -> None:
    """Expose the last review-safe action from the TUI action journal."""
    candidates_path = _write_passed_candidates(tmp_path)
    config_path = _write_config(tmp_path)
    action_journal_path = tmp_path / "state_data" / "tui" / "action_journal.jsonl"
    action_journal_path.parent.mkdir(parents=True, exist_ok=True)
    action_journal_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-06-02T00:00:00Z",
                "operation_key": "probe",
                "title": "Probe Candidates",
                "command_preview": "scholar-outbound-manager probe --allow-network-probe",
                "exit_code": 1,
                "succeeded": False,
                "redacted_stdout": "<REDACTED_URL>",
                "redacted_stderr": "password=<REDACTED>",
                "expected_artifacts": ["state_data/probe_summary.json"],
                "warnings": ["warn"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    state = load_control_plane_state(
        config_path=str(config_path),
        candidates_path=str(candidates_path),
        passed_candidates_path=str(candidates_path),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(tmp_path / "selected_candidate.json"),
        session_path=str(tmp_path / "tui_session.json"),
        action_journal_path=str(action_journal_path),
    )

    assert state.last_action is not None
    assert state.last_action.key == "probe"
    assert state.last_action.summary == "Probe Candidates failed with exit code 1."
    assert "password=<REDACTED>" in state.last_action.redacted_stderr_tail


def test_control_plane_prefers_selected_candidate_artifact_when_present(tmp_path: Path) -> None:
    candidates_path = _write_passed_candidates(tmp_path)
    config_path = _write_config(tmp_path)
    selected_candidate_path = tmp_path / "selected_candidate.json"
    payload = load_candidate_payload(candidates_path)
    record = select_candidate_by_index(payload, 0)
    selected_candidate_path.write_text(
        json.dumps(build_selected_candidate_artifact(record, selection_method="index")),
        encoding="utf-8",
    )

    state = load_control_plane_state(
        config_path=str(config_path),
        candidates_path=str(candidates_path),
        passed_candidates_path=str(candidates_path),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(selected_candidate_path),
        session_path=str(tmp_path / "tui_session.json"),
    )

    assert state.selection_state.selected_candidate_id == record.candidate_id
    assert state.selection_state.selection_method == "manual:selected_candidate"


def test_control_plane_ignores_invalid_selected_candidate_artifact_for_row_loading(tmp_path: Path) -> None:
    candidates_path = _write_passed_candidates(tmp_path)
    config_path = _write_config(tmp_path)
    selected_candidate_path = tmp_path / "selected_candidate.json"
    selected_candidate_path.write_text('{"selected_candidate_id":"previous"}', encoding="utf-8")

    state = load_control_plane_state(
        config_path=str(config_path),
        candidates_path=str(candidates_path),
        passed_candidates_path=str(candidates_path),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(selected_candidate_path),
        session_path=str(tmp_path / "tui_session.json"),
    )

    assert state.selection_state.rows
    assert state.selection_state.selected_candidate_id is not None


def test_control_plane_normalizes_legacy_last_action_without_summary(tmp_path: Path) -> None:
    """Older journal rows should still produce one typed last-action state."""
    candidates_path = _write_passed_candidates(tmp_path)
    config_path = _write_config(tmp_path)
    action_journal_path = tmp_path / "state_data" / "tui" / "action_journal.jsonl"
    action_journal_path.parent.mkdir(parents=True, exist_ok=True)
    action_journal_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-06-02T00:00:00Z",
                "operation_key": "artifact_check",
                "title": "Check Artifact Lineage",
                "exit_code": 0,
                "succeeded": True,
                "redacted_stdout": "",
                "redacted_stderr": "",
                "warnings": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    state = load_control_plane_state(
        config_path=str(config_path),
        candidates_path=str(candidates_path),
        passed_candidates_path=str(candidates_path),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(tmp_path / "selected_candidate.json"),
        session_path=str(tmp_path / "tui_session.json"),
        action_journal_path=str(action_journal_path),
    )

    assert state.last_action is not None
    assert state.last_action.title == "Check Artifact Lineage"
    assert state.last_action.summary == "Check Artifact Lineage completed successfully."
    assert state.last_action.redacted_stdout_tail == ""
    assert state.last_action.redacted_stderr_tail == ""


def test_control_plane_smoke_example_can_access_last_action_summary(tmp_path: Path) -> None:
    """The documented smoke access pattern should work without raw dict access."""
    candidates_path = _write_passed_candidates(tmp_path)
    config_path = _write_config(tmp_path)
    action_journal_path = tmp_path / "state_data" / "tui" / "action_journal.jsonl"
    action_journal_path.parent.mkdir(parents=True, exist_ok=True)
    action_journal_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-06-02T00:00:00Z",
                "operation_key": "select",
                "title": "Select Candidate",
                "exit_code": 0,
                "succeeded": True,
                "redacted_stdout": "",
                "redacted_stderr": "",
                "warnings": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    state = load_control_plane_state(
        config_path=str(config_path),
        candidates_path=str(candidates_path),
        passed_candidates_path=str(candidates_path),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(tmp_path / "selected_candidate.json"),
        session_path=str(tmp_path / "tui_session.json"),
        action_journal_path=str(action_journal_path),
    )

    assert (state.last_action.summary if state.last_action else None) == "Select Candidate completed successfully."


def test_control_plane_exposes_snapshot_metadata_and_rollback_availability(tmp_path: Path) -> None:
    """Latest snapshot metadata should appear in passive control-plane state."""
    candidates_path = _write_passed_candidates(tmp_path)
    config_path = _write_config(tmp_path)
    snapshot_root = tmp_path / "state_data" / "tui" / "artifact_snapshots"
    snapshot_dir = snapshot_root / "snap-20260602-000000-abcd12"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "snapshot.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_id": "snap-20260602-000000-abcd12",
                "created_at": "2026-06-02T00:00:00Z",
                "reason": "pre_probe",
                "files": {},
            }
        ),
        encoding="utf-8",
    )

    state = load_control_plane_state(
        config_path=str(config_path),
        candidates_path=str(candidates_path),
        passed_candidates_path=str(candidates_path),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(tmp_path / "selected_candidate.json"),
        session_path=str(tmp_path / "tui_session.json"),
        snapshot_root=str(snapshot_root),
    )

    assert state.artifact_state.snapshot_count == 1
    assert state.artifact_state.latest_snapshot_id == "snap-20260602-000000-abcd12"
    assert state.operation_availability.artifact_rollback_available is True


def test_control_plane_next_recommended_action_tracks_artifact_progression(tmp_path: Path) -> None:
    """Recommend fetch, probe, or select according to current artifact presence."""
    config_path = _write_config(tmp_path)

    fetch_state = load_control_plane_state(
        config_path=str(config_path),
        candidates_path=str(tmp_path / "candidates.json"),
        passed_candidates_path=str(tmp_path / "passed_candidates.json"),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(tmp_path / "selected_candidate.json"),
        session_path=str(tmp_path / "tui_session.json"),
    )
    assert "run fetch explicitly" in fetch_state.workflow_state.next_recommended_action.lower()
    assert "why:" in fetch_state.workflow_state.next_recommended_action.lower()

    candidates_path = _write_candidates_only(tmp_path)
    probe_state = load_control_plane_state(
        config_path=str(config_path),
        candidates_path=str(candidates_path),
        passed_candidates_path=str(tmp_path / "passed_candidates.json"),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(tmp_path / "selected_candidate.json"),
        session_path=str(tmp_path / "tui_session.json"),
    )
    assert "run probe explicitly" in probe_state.workflow_state.next_recommended_action.lower()
    assert "why:" in probe_state.workflow_state.next_recommended_action.lower()

    passed_candidates_path = _write_passed_candidates(tmp_path)
    select_state = load_control_plane_state(
        config_path=str(config_path),
        candidates_path=str(candidates_path),
        passed_candidates_path=str(passed_candidates_path),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(tmp_path / "selected_candidate.json"),
        session_path=str(tmp_path / "tui_session.json"),
    )
    assert "choose one passed candidate" in select_state.workflow_state.next_recommended_action.lower()
    assert "why:" in select_state.workflow_state.next_recommended_action.lower()
    assert select_state.operation_availability.select_available is True


def test_control_plane_next_recommended_action_prefers_fix_or_save_config(tmp_path: Path) -> None:
    """Config invalidity or dirty form state should outrank downstream workflow steps."""
    config_path = _write_config(tmp_path)

    invalid_state = load_control_plane_state(
        config_path=str(tmp_path / "missing-config.yaml"),
        candidates_path=str(tmp_path / "candidates.json"),
        passed_candidates_path=str(tmp_path / "passed_candidates.json"),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(tmp_path / "selected_candidate.json"),
        session_path=str(tmp_path / "tui_session.json"),
    )
    assert "create or point the tui" in invalid_state.workflow_state.next_recommended_action.lower()
    assert "config file is missing" in invalid_state.workflow_state.next_recommended_action.lower()

    config_path = _write_config(tmp_path)
    with patch(
        "scholar_outbound_manager.tui.control_plane.build_config_form_state",
        return_value=type("DummyForm", (), {"fields": [], "dirty": True, "valid": True, "validation_errors": [], "redacted_diff": "diff"})(),
    ):
        dirty_state = load_control_plane_state(
            config_path=str(config_path),
            candidates_path=str(tmp_path / "candidates.json"),
            passed_candidates_path=str(tmp_path / "passed_candidates.json"),
            probe_summary_path=str(tmp_path / "probe_summary.json"),
            selected_candidate_path=str(tmp_path / "selected_candidate.json"),
            session_path=str(tmp_path / "tui_session.json"),
        )
    assert "save config changes" in dirty_state.workflow_state.next_recommended_action.lower()
    assert "structured config changes are pending" in dirty_state.workflow_state.next_recommended_action.lower()


def _write_passed_candidates(tmp_path: Path) -> Path:
    path = tmp_path / "passed_candidates.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sensitive": True,
                "candidates": [
                    {
                        "candidate": {
                            "source_name": "fixture",
                            "raw_name": "US Scholar 01",
                            "protocol": "vless",
                            "address": "example.invalid",
                            "port": 443,
                            "user_id": "00000000-0000-0000-0000-000000000000",
                            "security": "reality",
                            "server_name": "www.cloudflare.com",
                            "public_key": "PUBLIC_KEY_PLACEHOLDER",
                            "supported": True,
                            "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
                        },
                        "probe": {
                            "candidate_id": "candidate-001",
                            "home_status": 200,
                            "query_status": 200,
                            "blocked": False,
                            "timeout": False,
                            "error": None,
                            "failure_markers": [],
                            "latency_ms": 10,
                            "checked_at": "2026-05-27T00:00:00Z",
                            "passed": True,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_candidates_only(tmp_path: Path) -> Path:
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "candidates": [
                    {
                        "source_name": "fixture",
                        "raw_name": "US Scholar 01",
                        "protocol": "vless",
                        "address": "example.invalid",
                        "port": 443,
                        "user_id": "00000000-0000-0000-0000-000000000000",
                        "security": "reality",
                        "server_name": "www.cloudflare.com",
                        "public_key": "PUBLIC_KEY_PLACEHOLDER",
                        "supported": True,
                        "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_config(tmp_path: Path, *, subscription_url: str = "https://example.invalid/subscription") -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        "\n".join(
            [
                "subscriptions:",
                '  - name: "fixture-source"',
                f'    url: "{subscription_url}"',
                '    format: "auto"',
                "    enabled: true",
                "    headers: {}",
                "filters:",
                "  include_keywords: []",
                "  exclude_keywords: []",
                "  deprioritize_keywords: []",
                "probe:",
                "  timeout_seconds: 5",
                "  concurrency: 1",
                "  cache_ttl_hours: 24",
                "  failure_backoff_hours: 24",
                "  allow_network_probe: false",
                "xray:",
                '  binary_path: "/usr/local/bin/xray"',
                f'  runtime_dir: "{tmp_path / ".runtime"}"',
                '  local_socks_host: "127.0.0.1"',
                "  local_socks_port: 1081",
                "output:",
                '  outbounds_path: "generated/outbounds.json"',
                '  routes_path: "generated/routes.json"',
                '  manifest_path: "generated/manifest.json"',
                '  history_dir: "state_data/history"',
                "generation:",
                '  tag_prefix: "google-scholar-node-"',
                "  max_passed_nodes: 2",
                '  fallback_blackhole_tag: "blocked-scholar"',
                "  previous_output_max_age_hours: 24",
                "routing:",
                '  mode: "dedicated_inbound"',
                "  inbound_tags:",
                '    - "scholar-in"',
                "  fail_closed: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path
