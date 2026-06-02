"""Tests for Textual-safe TUI tab identifiers and presentation helpers."""

from __future__ import annotations

from scholar_outbound_manager.tui.control_plane import ArtifactState
from scholar_outbound_manager.tui.control_plane import CommandState
from scholar_outbound_manager.tui.control_plane import ConfigState
from scholar_outbound_manager.tui.control_plane import ControlPlaneState
from scholar_outbound_manager.tui.control_plane import OperationAvailability
from scholar_outbound_manager.tui.control_plane import PoolState
from scholar_outbound_manager.tui.control_plane import SelectionState
from scholar_outbound_manager.tui.control_plane import SidecarState
from scholar_outbound_manager.tui.control_plane import WorkflowModelState
from scholar_outbound_manager.tui.commands import OperationSpec
from scholar_outbound_manager.tui.config_form import ConfigFormState
from scholar_outbound_manager.tui import app as tui_app
from scholar_outbound_manager.tui.workflow import MAIN_TABS


def test_textual_safe_id_for_dashboard() -> None:
    """Keep simple names readable after sanitization."""
    assert tui_app._textual_safe_id("Dashboard") == "dashboard"


def test_textual_safe_id_for_fetch_probe() -> None:
    """Replace spaces and punctuation with hyphens."""
    assert tui_app._textual_safe_id("Fetch & Probe") == "fetch-probe"


def test_textual_safe_id_for_restart_validate() -> None:
    """Collapse invalid punctuation runs into one hyphen."""
    assert tui_app._textual_safe_id("Restart & Validate") == "restart-validate"


def test_textual_safe_id_for_leading_number() -> None:
    """Prefix ids that would otherwise begin with a digit."""
    assert tui_app._textual_safe_id("123 Test") == "tab-123-test"


def test_textual_safe_id_for_blank_value() -> None:
    """Fallback to one safe default id when the title is empty."""
    assert tui_app._textual_safe_id("   ") == "tab"


def test_build_tab_specs_make_duplicate_ids_unique() -> None:
    """Disambiguate repeated or slug-colliding tab titles by occurrence."""
    specs, initial_id = tui_app._build_tab_specs(["Fetch & Probe", "Fetch-Probe", "Fetch & Probe"])

    assert initial_id == "fetch-probe"
    assert [spec["id"] for spec in specs] == ["fetch-probe", "fetch-probe-2", "fetch-probe-3"]


def test_workflow_tabs_all_produce_textual_safe_ids() -> None:
    """Ensure current workflow tabs never emit raw invalid ids."""
    specs, initial_id = tui_app._build_tab_specs(list(MAIN_TABS))

    assert initial_id == "dashboard"
    assert all(spec["id"] for spec in specs)
    assert all(spec["id"].replace("-", "").replace("_", "").isalnum() for spec in specs)
    assert specs[2]["title"] == "Fetch & Probe"
    assert specs[2]["id"] == "fetch-probe"


def test_build_tab_specs_do_not_use_raw_tab_label_as_id() -> None:
    """Keep human-readable titles while separating internal ids."""
    specs, _ = tui_app._build_tab_specs(["Dashboard", "Fetch & Probe"])

    assert specs[0] == {"title": "Dashboard", "id": "dashboard"}
    assert specs[1] == {"title": "Fetch & Probe", "id": "fetch-probe"}


def test_workflow_tabs_include_config_tab() -> None:
    """Expose the plan-aligned config tab in the primary workflow."""
    assert MAIN_TABS[1] == "Config"


def test_tui_key_bindings_cover_expected_controls() -> None:
    """Keep the minimal workflow key bindings available."""
    bindings = {key: action for key, action, _description in tui_app.TUI_KEY_BINDINGS}

    assert bindings["q"] == "quit"
    assert bindings["r"] == "reload_state"
    assert bindings["j"] == "cursor_down"
    assert bindings["k"] == "cursor_up"
    assert bindings["enter"] == "confirm_selected"
    assert bindings["escape"] == "cancel_pending"
    assert bindings["e"] == "edit_config_field"
    assert bindings["d"] == "show_config_diff"
    assert bindings["s"] == "save_draft"
    assert bindings["u"] == "undo_save"
    assert bindings["f"] == "run_fetch"
    assert bindings["p"] == "run_probe"
    assert bindings["a"] == "run_artifact_check"
    assert bindings["c"] == "run_select"
    assert bindings["g"] == "run_stage_sidecar"
    assert bindings["v"] == "run_validate_sidecar"
    assert bindings["x"] == "create_snapshot"
    assert bindings["z"] == "rollback_latest_snapshot"
    assert bindings["?"] == "show_help"


def test_workflow_controller_requires_second_confirmation_before_network_action(tmp_path, monkeypatch) -> None:
    """Network actions should not run on the first key press."""
    call_count = {"runs": 0}

    def fake_load_control_plane_state(**kwargs):
        del kwargs
        state = _fake_control_plane_state()
        state.command_state.operations = [
            OperationSpec(
                "fetch",
                "Fetch Candidates",
                ["fetch"],
                True,
                True,
                False,
                True,
                ["candidates.json"],
            )
        ]
        return state

    class DummyRunner:
        def run(self, spec, options):
            call_count["runs"] += 1
            return tui_app.ActionResult(
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
                summary="ok",
                expected_artifacts=[],
                warnings=[],
            )

    monkeypatch.setattr("scholar_outbound_manager.tui.controller.load_control_plane_state", fake_load_control_plane_state)
    controller = tui_app.WorkflowController(
        loader_kwargs={},
        runner=DummyRunner(),
        action_journal_path=str(tmp_path / "state_data" / "tui" / "action_journal.jsonl"),
    )

    first = controller.handle_operation("fetch")

    assert "pending confirmation" in first.lower()
    assert call_count["runs"] == 0


def test_workflow_controller_confirms_fake_action_and_reloads_state(tmp_path, monkeypatch) -> None:
    """Confirmed actions should execute, journal, and reload workflow state."""
    load_calls: list[int] = []

    def fake_load_control_plane_state(**kwargs):
        del kwargs
        load_calls.append(1)
        return _fake_control_plane_state()

    monkeypatch.setattr("scholar_outbound_manager.tui.controller.load_control_plane_state", fake_load_control_plane_state)
    result = tui_app.ActionResult(
        key="artifact_check",
        title="Check Artifact Lineage",
        command=["artifact-check"],
        started_at="2026-06-02T00:00:00Z",
        finished_at="2026-06-02T00:00:01Z",
        exit_code=0,
        succeeded=True,
        stdout="",
        stderr="",
        redacted_stdout="ok",
        redacted_stderr="",
        summary="artifact check ok",
        expected_artifacts=[],
        warnings=[],
    )
    controller = tui_app.WorkflowController(
        loader_kwargs={},
        runner=tui_app.FakeActionRunner({"artifact_check": result}),
        action_journal_path=str(tmp_path / "state_data" / "tui" / "action_journal.jsonl"),
    )

    message = controller.handle_operation("artifact_check")

    assert "artifact check ok" in message
    assert controller.action_state.last_result is not None
    assert controller.action_state.last_result.key == "artifact_check"
    assert len(load_calls) >= 2


def test_workflow_controller_requires_confirmation_before_rollback(tmp_path, monkeypatch) -> None:
    """Artifact rollback should require a second confirmation press."""
    root = tmp_path / "state_data" / "tui" / "artifact_snapshots"
    snapshot_dir = root / "snap-20260602-000000-deadbe"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "snapshot.json").write_text(
        '{"schema_version":1,"snapshot_id":"snap-20260602-000000-deadbe","created_at":"2026-06-02T00:00:00Z","reason":"test","files":{}}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scholar_outbound_manager.tui.controller.load_control_plane_state",
        lambda **kwargs: _fake_control_plane_state(config_path=str(tmp_path / "config.yaml")),
    )
    controller = tui_app.WorkflowController(loader_kwargs={}, snapshot_root=str(root))

    first = controller.rollback_latest_snapshot()

    assert "pending confirmation" in first.lower()


def test_workflow_controller_create_snapshot_returns_artifact_snapshot(tmp_path, monkeypatch) -> None:
    root = tmp_path / "state_data" / "tui" / "artifact_snapshots"

    def fake_load_control_plane_state(**kwargs):
        del kwargs
        return _fake_control_plane_state(config_path=str(tmp_path / "config.yaml"))

    monkeypatch.setattr("scholar_outbound_manager.tui.controller.load_control_plane_state", fake_load_control_plane_state)
    controller = tui_app.WorkflowController(loader_kwargs={}, snapshot_root=str(root))

    snapshot = controller.create_snapshot("manual_test")

    assert snapshot.snapshot_id.startswith("snap-")
    assert snapshot.reason == "manual_test"


def test_workflow_controller_create_snapshot_message_returns_user_string(tmp_path, monkeypatch) -> None:
    def fake_load_control_plane_state(**kwargs):
        del kwargs
        return _fake_control_plane_state(config_path=str(tmp_path / "config.yaml"))

    monkeypatch.setattr("scholar_outbound_manager.tui.controller.load_control_plane_state", fake_load_control_plane_state)
    controller = tui_app.WorkflowController(
        loader_kwargs={},
        snapshot_root=str(tmp_path / "state_data" / "tui" / "artifact_snapshots"),
    )

    message = controller.create_snapshot_message("manual_test")

    assert message.startswith("Created artifact snapshot snap-")


def test_workflow_controller_can_update_state_via_config_field_patch(tmp_path, monkeypatch) -> None:
    """Controller field updates should route through the structured config form path and refresh state."""
    load_calls: list[int] = []

    def fake_load_control_plane_state(**kwargs):
        del kwargs
        load_calls.append(1)
        return _fake_control_plane_state(config_path=str(tmp_path / "config.yaml"))

    monkeypatch.setattr("scholar_outbound_manager.tui.controller.load_control_plane_state", fake_load_control_plane_state)
    monkeypatch.setattr(
        "scholar_outbound_manager.tui.controller.apply_config_form_patch",
        lambda *args, **kwargs: type("FakeSaveResult", (), {"message": "updated probe.concurrency", "saved": True})(),
    )
    controller = tui_app.WorkflowController(loader_kwargs={})

    message = controller.update_config_field("probe.concurrency", 4)

    assert "probe.concurrency" in message
    assert len(load_calls) >= 2


def test_refresh_tab_bodies_updates_selection_view_after_cursor_move() -> None:
    updates: dict[str, str] = {}
    workflow_state = {
        "tabs": ["Selection"],
        "selection": {
            "sensitive_notice": "notice",
            "selected_candidate_id": "candidate-002",
            "selected_candidate_label": "label-2",
            "selected_region_hint": "US",
            "preferred_region_hint": None,
            "selection_method": "manual",
            "selection_reason": "operator",
        },
        "commands": {"select": "select ..."},
        "operation_availability": {"select_available": True},
        "workbench": {
            "selection_rows": [
                {
                    "index": 0,
                    "label": "label-1",
                    "region": "JP",
                    "protocol": "vless",
                    "passed": True,
                    "stage": "full_access",
                    "home_status": 200,
                    "query_status": 200,
                    "failure_marker_count": 0,
                    "candidate_id": "candidate-001",
                    "selected": False,
                },
                {
                    "index": 1,
                    "label": "label-2",
                    "region": "US",
                    "protocol": "vless",
                    "passed": True,
                    "stage": "full_access",
                    "home_status": 200,
                    "query_status": 200,
                    "failure_marker_count": 0,
                    "candidate_id": "candidate-002",
                    "selected": True,
                },
            ],
            "selected_candidate_detail": {"candidate_id": "candidate-002", "label": "label-2"},
        },
    }

    tui_app._refresh_tab_bodies(
        ["Selection"],
        workflow_state,
        lambda body_id, text: updates.__setitem__(body_id, text),
    )

    rendered = updates["selection-body"]
    assert "> #1 label-2" in rendered
    assert "selected_candidate_detail: {'candidate_id': 'candidate-002'" in rendered


def test_run_safe_tui_action_redacts_exception_details(tmp_path, monkeypatch) -> None:
    def fake_load_control_plane_state(**kwargs):
        del kwargs
        return _fake_control_plane_state(config_path=str(tmp_path / "config.yaml"))

    monkeypatch.setattr("scholar_outbound_manager.tui.controller.load_control_plane_state", fake_load_control_plane_state)
    controller = tui_app.WorkflowController(loader_kwargs={})

    message, succeeded = tui_app._run_safe_tui_action(
        controller,
        "Choose selected candidate",
        lambda: (_ for _ in ()).throw(
            ValueError(
                "raw_uri=vless://00000000-0000-0000-0000-000000000000@example.internal:443 "
                "server_name=secret.example.internal user_id=00000000-0000-0000-0000-000000000000 "
                "address=secret.example.internal path=/credential-bearing"
            )
        ),
    )

    assert succeeded is False
    assert message is not None
    assert "00000000-0000-0000-0000-000000000000" not in message
    assert "secret.example.internal" not in message
    assert "vless://" not in message
    assert "/credential-bearing" not in message
    assert controller.message is not None
    assert controller.message.level == "error"


def test_render_dashboard_and_config_tabs_show_reason_and_field_safety() -> None:
    """Rendered tabs should show blocking reason, structured field hints, and exclusion notice."""
    workflow_state = {
        "tab_strip": "tabs",
        "dashboard": {
            "repo_status": "clean",
            "current_git_commit": "abc1234",
            "config_dirty": False,
            "config_valid": True,
            "undo_available": False,
            "candidate_count": 1,
            "passed_count": 1,
            "selected_candidate_label": "United States relay",
            "next_recommended_action": "Review probe preview. Why: candidates are missing.",
            "last_action": {
                "title": "Probe Candidates",
                "succeeded": False,
                "exit_code": 1,
                "summary": "Probe Candidates failed with exit code 1.",
                "redacted_stderr_tail": "timeout",
            },
            "snapshot_count": 1,
            "latest_snapshot_id": "snap-1",
        },
        "preflight": {
            "config_exists": True,
            "config_valid": True,
            "config_validation_errors": [],
        },
        "config_editor": {
            "undo_available": False,
            "redacted_diff": "",
            "redacted_preview": "preview",
        },
        "config_form": {
            "fields": [
                {
                    "key": "probe.concurrency",
                    "value_type": "int",
                    "editable": True,
                    "requires_restart": False,
                },
                {
                    "key": "xray.local_socks_port",
                    "value_type": "int",
                    "editable": True,
                    "requires_restart": True,
                },
            ],
            "redacted_diff": "",
        },
        "operation_availability": {
            "config_save_available": True,
            "config_undo_available": False,
            "fetch_available": True,
            "probe_available": False,
            "artifact_check_available": True,
            "artifact_snapshot_available": True,
            "artifact_rollback_available": False,
            "select_available": False,
            "sidecar_stage_available": False,
            "service_validate_available": False,
            "snippet_available": True,
        },
        "warnings": ["network warning"],
        "commands": {
            "fetch": "fetch ...",
            "probe": "probe ...",
            "artifact_check": "artifact ...",
            "select": "select ...",
            "sidecar_stage": "stage ...",
            "service_restart": "restart ...",
            "service_validate": "validate ...",
            "pool_stage": "pool ...",
            "service_snippet": "snippet ...",
        },
        "artifacts": {
            "artifact_check": {"overall_consistent": False},
            "snapshot_count": 1,
            "latest_snapshot_id": "snap-1",
            "latest_snapshot_reason": "pre_probe",
            "candidates_hash": "a",
            "probe_summary_hash": "b",
            "passed_candidates_hash": "c",
            "warnings": ["mismatch"],
        },
        "selection": {
            "sensitive_notice": "selected_candidate.json is sensitive",
            "selected_candidate_id": "candidate-1",
            "selected_candidate_label": "United States relay",
            "selected_region_hint": "US",
            "preferred_region_hint": None,
            "selection_method": "auto",
            "selection_reason": "closest",
        },
        "snippets": {"warning": "warning"},
        "tabs": ["Dashboard", "Config"],
        "control_plane": {
            "workflow_state": {"blocking_reason": "Artifact mismatch detected."},
            "command_state": {
                "operations": [
                    {
                        "key": "fetch",
                        "requires_confirmation": True,
                        "network_access": True,
                        "systemd_access": False,
                        "risk_note": "Live network operation.",
                    }
                ]
            },
            "sidecar_state": {
                "service_active": "unknown",
                "service_enabled": "unknown",
                "socks_tcp_connect": "unknown",
                "last_validation": "unknown",
                "warning": "warn",
            },
            "pool_state": {"plan_exists": False, "port_warning": "warn", "rows": []},
        },
    }

    dashboard_rendered = tui_app.render_tab_text("Dashboard", workflow_state)
    config_rendered = tui_app.render_tab_text("Config", workflow_state)

    assert "blocking_reason: Artifact mismatch detected." in dashboard_rendered
    assert "last_action: title=Probe Candidates" in dashboard_rendered
    assert "sensitive fields excluded:" in config_rendered
    assert "probe.concurrency | type=int | editable=True | restart_required=False" in config_rendered
    assert "xray.local_socks_port | type=int | editable=True | restart_required=True" in config_rendered


def _fake_control_plane_state(*, config_path: str = "config.yaml") -> ControlPlaneState:
    return ControlPlaneState(
        workspace="/tmp/workspace",
        tabs=["Dashboard", "Config", "Selection"],
        config_state=ConfigState(True, True, False, False, "preview", "", [], 1, False, "dedicated_inbound", True),
        config_form_state=ConfigFormState(
            fields=[],
            dirty=False,
            valid=True,
            validation_errors=[],
            redacted_diff="",
        ),
        artifact_state=ArtifactState(True, False, False, False, None, None, [], None, None, None, 0, None, None),
        selection_state=SelectionState([], None, None, None, None, None, None),
        workflow_state=WorkflowModelState([], None, "next action"),
        command_state=CommandState(
            "fetch",
            "probe",
            "artifact",
            "select",
            "stage",
            "restart",
            "validate",
            "snippet",
            "pool",
            [
                OperationSpec(
                    "artifact_check",
                    "Check Artifact Lineage",
                    ["artifact-check"],
                    False,
                    False,
                    False,
                    False,
                    [],
                )
            ],
        ),
        operation_availability=OperationAvailability(True, False, False, False, False, False, False, True, False, False, True, False),
        sidecar_state=SidecarState("unknown", "unknown", "unknown", "unknown", "warn", True, "/usr/local/bin/xray"),
        pool_state=PoolState(False, [], "warn"),
        warnings=["live warning"],
        last_action=None,
        session={
            "schema_version": 1,
            "updated_at": "2026-06-02T00:00:00Z",
            "workspace": "/tmp/workspace",
            "last_step": None,
            "paths": {"config": config_path},
            "last_results": {},
        },
        snippets={"warning": "snippet warning", "rendered": "[]"},
        repo_status="clean",
        current_git_commit="abc1234",
        venv_detected=True,
        current_sidecar_port=19080,
    )
