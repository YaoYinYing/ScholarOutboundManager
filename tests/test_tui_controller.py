"""Tests for the pure-Python TUI workbench controller."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scholar_outbound_manager.tui.action_runner import ActionResult
from scholar_outbound_manager.tui.controller import WorkbenchController


def test_controller_reloads_state(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(config_path.read_text(encoding="utf-8").replace("concurrency: 1", "concurrency: 3"), encoding="utf-8")

    state = controller.reload()

    assert state.config_state.valid is True
    assert controller.state.config_state.valid is True


def test_candidate_selection_moves_within_bounds(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)

    controller.move_candidate(1)
    assert controller.selection.selected_candidate_index == 1

    controller.move_candidate(10)
    assert controller.selection.selected_candidate_index == 1

    controller.move_candidate(-10)
    assert controller.selection.selected_candidate_index == 0


def test_choose_selected_candidate_writes_selected_artifact(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)

    result = controller.choose_selected_candidate()

    payload = json.loads((tmp_path / "state_data" / "selected_candidate.json").read_text(encoding="utf-8"))
    assert result.candidate_id == "candidate-001"
    assert payload["selected_candidate_id"] == "candidate-001"


def test_choose_selected_candidate_snapshots_previous_selected_artifact(tmp_path: Path) -> None:
    selected_candidate_path = tmp_path / "state_data" / "selected_candidate.json"
    selected_candidate_path.parent.mkdir(parents=True, exist_ok=True)
    selected_candidate_path.write_text('{"selected_candidate_id":"previous"}', encoding="utf-8")
    controller = _build_controller(tmp_path)

    result = controller.choose_selected_candidate()
    snapshots = controller.list_snapshots()

    assert result.snapshot_id is not None
    assert snapshots
    assert snapshots[0].files["selected_candidate"].exists is True


def test_workflow_controller_create_snapshot_returns_snapshot_object(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)

    snapshot = controller.create_snapshot("manual_test")

    assert snapshot.snapshot_id.startswith("snap-")
    assert snapshot.reason == "manual_test"


def test_choose_selected_candidate_no_longer_depends_on_string_snapshot_message(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)

    result = controller.choose_selected_candidate()

    assert result.snapshot_id is not None
    assert "selected_candidate.json" in result.output_path


def test_choose_selected_candidate_uses_row_source_index_not_visible_position(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    controller.state.selection_state.rows = [
        {
            **controller.state.selection_state.rows[0],
            "index": 1,
            "candidate_id": "candidate-002",
        },
        {
            **controller.state.selection_state.rows[1],
            "index": 0,
            "candidate_id": "candidate-001",
        },
    ]
    controller.selection.selected_candidate_index = 1

    result = controller.choose_selected_candidate()

    payload = json.loads((tmp_path / "state_data" / "selected_candidate.json").read_text(encoding="utf-8"))
    assert result.candidate_id == "candidate-001"
    assert payload["selected_candidate_id"] == "candidate-001"


def test_config_field_selection_moves_within_bounds(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    keys = [field.key for field in controller.state.config_form_state.fields]

    controller.move_config_field(1)
    assert controller.selection.selected_config_field_key == keys[1]

    controller.move_config_field(99)
    assert controller.selection.selected_config_field_key == keys[-1]

    controller.move_config_field(-99)
    assert controller.selection.selected_config_field_key == keys[0]


def test_invalid_config_field_update_is_rejected(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)

    with pytest.raises(ValueError):
        controller.update_config_field("probe.concurrency", "bad")


def test_safe_config_field_update_uses_transaction(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)

    result = controller.update_config_field("probe.concurrency", 4)

    assert result.saved is True
    assert "concurrency: 4" in (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert (tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl").exists()


def test_fetch_action_is_routine_and_does_not_require_confirmation(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path, runner=_CountingRunner())

    pending = controller.prepare_action("fetch")

    assert pending.requires_confirmation is False
    assert controller.action_state.pending_confirmation is None


def test_routine_action_runs_through_fake_runner_immediately(tmp_path: Path) -> None:
    runner = _CountingRunner()
    controller = _build_controller(tmp_path, runner=runner)

    result = controller.handle_operation("fetch")

    assert "completed successfully" in result
    assert runner.calls == ["fetch"]


def test_probe_action_runs_through_fake_runner_immediately(tmp_path: Path) -> None:
    runner = _CountingRunner()
    controller = _build_controller(tmp_path, runner=runner)

    result = controller.handle_operation("probe")

    assert "completed successfully" in result
    assert runner.calls == ["probe"]


def test_destructive_action_requires_prepare_and_confirm(tmp_path: Path) -> None:
    runner = _CountingRunner()
    controller = _build_controller(tmp_path, runner=runner)

    pending = controller.prepare_action("service_restart")
    result = controller.confirm_action("service_restart")

    assert pending.requires_confirmation is True
    assert result.succeeded is True
    assert runner.calls == ["service_restart"]


def test_clear_pending_action_prevents_execution(tmp_path: Path) -> None:
    runner = _CountingRunner()
    controller = _build_controller(tmp_path, runner=runner)

    controller.prepare_action("service_restart")
    controller.clear_pending_action()

    with pytest.raises(ValueError):
        controller.confirm_action("service_restart")
    assert runner.calls == []


def _build_controller(tmp_path: Path, runner=None) -> WorkbenchController:
    config_path = _write_config(tmp_path)
    passed_candidates_path = _write_passed_candidates(tmp_path)
    return WorkbenchController(
        loader_kwargs={
            "config_path": str(config_path),
            "candidates_path": str(tmp_path / "candidates.json"),
            "probe_summary_path": str(tmp_path / "state_data" / "probe_summary.json"),
            "passed_candidates_path": str(passed_candidates_path),
            "selected_candidate_path": str(tmp_path / "state_data" / "selected_candidate.json"),
            "pool_plan_path": str(tmp_path / "state_data" / "sidecar_pool_plan.json"),
            "action_journal_path": str(tmp_path / "state_data" / "tui" / "action_journal.jsonl"),
            "snapshot_root": str(tmp_path / "state_data" / "tui" / "artifact_snapshots"),
        },
        runner=runner,
        action_journal_path=str(tmp_path / "state_data" / "tui" / "action_journal.jsonl"),
        snapshot_root=str(tmp_path / "state_data" / "tui" / "artifact_snapshots"),
    )


class _CountingRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, spec, options) -> ActionResult:
        del options
        self.calls.append(spec.key)
        return ActionResult(
            key=spec.key,
            title=spec.title,
            command=spec.command,
            started_at="2026-06-02T00:00:00Z",
            finished_at="2026-06-02T00:00:01Z",
            exit_code=0,
            succeeded=True,
            stdout="",
            stderr="",
            redacted_stdout="",
            redacted_stderr="",
            summary=f"{spec.title} completed successfully.",
            expected_artifacts=[],
            warnings=[],
        )


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "subscriptions:",
                "  - name: fixture-source",
                "    url: https://example.invalid/subscription",
                "    format: auto",
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
                "  binary_path: /usr/local/bin/xray",
                "  runtime_dir: .runtime",
                "  local_socks_host: 127.0.0.1",
                "  local_socks_port: 1081",
                "output:",
                "  outbounds_path: generated/outbounds.json",
                "  routes_path: generated/routes.json",
                "  manifest_path: generated/manifest.json",
                "  history_dir: state_data/history",
                "generation:",
                "  tag_prefix: google-scholar-node-",
                "  max_passed_nodes: 2",
                "  fallback_blackhole_tag: blocked-scholar",
                "  previous_output_max_age_hours: 24",
                "routing:",
                "  mode: dedicated_inbound",
                "  inbound_tags:",
                "    - scholar-in",
                "  fail_closed: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _write_passed_candidates(tmp_path: Path) -> Path:
    path = tmp_path / "state_data" / "passed_candidates.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sensitive": True,
                "candidates": [
                    {
                        "candidate_id": "candidate-001",
                        "candidate": {
                            "source_name": "fixture",
                            "raw_name": "United States candidate one",
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
                    },
                    {
                        "candidate_id": "candidate-002",
                        "candidate": {
                            "source_name": "fixture",
                            "raw_name": "Japan candidate two",
                            "protocol": "trojan",
                            "address": "example.invalid",
                            "port": 443,
                            "password": "PASSWORD_PLACEHOLDER",
                            "supported": True,
                            "raw_uri": "trojan://PASSWORD_PLACEHOLDER@example.invalid:443",
                        },
                        "probe": {
                            "candidate_id": "candidate-002",
                            "home_status": 403,
                            "query_status": 403,
                            "blocked": True,
                            "timeout": False,
                            "error": "google_sorry",
                            "failure_markers": ["query-blocked"],
                            "latency_ms": 50,
                            "checked_at": "2026-05-27T00:00:00Z",
                            "passed": False,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path
