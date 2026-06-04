"""Tests for config-centered TUI presentation helpers."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.tui import app as tui_app
from scholar_outbound_manager.tui.commands import OperationSpec
from scholar_outbound_manager.tui.config_form import ConfigFormState
from scholar_outbound_manager.tui.control_plane import ArtifactState
from scholar_outbound_manager.tui.control_plane import CommandState
from scholar_outbound_manager.tui.control_plane import ConfigState
from scholar_outbound_manager.tui.control_plane import ControlPlaneState
from scholar_outbound_manager.tui.control_plane import OperationAvailability
from scholar_outbound_manager.tui.control_plane import PoolState
from scholar_outbound_manager.tui.control_plane import SelectionState
from scholar_outbound_manager.tui.control_plane import SidecarState
from scholar_outbound_manager.tui.control_plane import WorkflowModelState
from scholar_outbound_manager.tui.workflow import MAIN_TABS


def test_textual_safe_id_keeps_widget_ids_valid() -> None:
    assert tui_app._textual_safe_id("Fetch & Probe") == "fetch-probe"
    assert tui_app._textual_safe_id("123 Test") == "tab-123-test"
    assert tui_app._textual_safe_id("   ") == "tab"


def test_build_tab_specs_uses_home_as_initial_tab() -> None:
    specs, initial_id = tui_app._build_tab_specs(list(MAIN_TABS))

    assert MAIN_TABS == ("Home", "Settings", "Testing", "Route", "Logs")
    assert initial_id == "home"
    assert [spec["title"] for spec in specs] == list(MAIN_TABS)


def test_render_home_tab_shows_config_centered_summary() -> None:
    rendered = tui_app.render_tab_text(
        "Home",
        {
            "home": {
                "config_path": "/tmp/config.yaml",
                "user_data_dir": "/tmp/state_data",
                "subscription_configured": True,
                "last_fetch_status": "ready",
                "candidate_count": 12,
                "passed_count": 5,
                "tested_count": 9,
                "full_access_count": 5,
                "query_blocked_count": 3,
                "enabled_route_count": 1,
                "route_count": 1,
                "active_listen_ports": [19080],
                "selected_candidate_label": "US relay",
                "service_active": "unknown",
                "socks_status": "unknown",
                "last_validation": "needed",
                "next_recommended_action": "Validate sidecar service.",
            },
            "wizard": {
                "active": False,
            },
        },
    )

    assert "Scholar Outbound Manager" in rendered
    assert "Config: /tmp/config.yaml" in rendered
    assert "User data: /tmp/state_data" in rendered
    assert "Subscription" in rendered
    assert "Testing" in rendered
    assert "Route" in rendered
    assert "Sidecar" in rendered
    assert "Next: Validate sidecar service." in rendered


def test_render_settings_hides_subscription_url_and_shows_safe_fields() -> None:
    rendered = tui_app.render_tab_text(
        "Settings",
        {
            "settings": {
                "config_path": "/tmp/config.yaml",
                "user_data_dir": "/tmp/state_data",
                "subscription_url_masked": "******** configured",
                "subscription_user_agent": "Clash.Meta",
                "xray_binary_path": ".runtime/xray/xray",
                "fail_closed": True,
                "experimental_hysteria2": False,
                "service_name": "scholar-outbound-sidecar.service",
                "redacted_diff": "",
            }
        },
    )

    assert "Settings" in rendered
    assert "URL: ******** configured" in rendered
    assert "https://" not in rendered
    assert "User-Agent: Clash.Meta" in rendered
    assert "fail_closed: ON" in rendered
    assert "hysteria2 experimental: OFF" in rendered
    assert "[Save] [Undo] [Show Diff] [Test Fetch]" in rendered


def test_render_testing_shows_summary_inspector_and_recent_events() -> None:
    rendered = tui_app.render_tab_text(
        "Testing",
        {
            "testing": {
                "job_state": "idle",
                "progress_current": 2,
                "progress_total": 4,
                "summary": {
                    "subscription_configured": True,
                    "last_fetch_status": "ready",
                    "candidate_count": 4,
                    "supported_count": 3,
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
                },
                "log_lines": ["Probe Candidates completed successfully."],
            }
        },
    )

    assert "Summary" in rendered
    assert "Candidates: 4" in rendered
    assert "Selected candidate" in rendered
    assert "Recent events" in rendered
    assert "Probe Candidates completed successfully." in rendered


def test_render_logs_shows_local_only_rollback_warning() -> None:
    rendered = tui_app.render_tab_text(
        "Logs",
        {
            "logs_screen": {
                "rollback_warning": [
                    "Artifact rollback restores local artifacts only.",
                    "It does not undo network effects.",
                ],
                "last_action": {
                    "title": "Probe Candidates",
                    "summary": "Probe Candidates failed with exit code 1.",
                },
            }
        },
    )

    assert "Logs" in rendered
    assert "Artifact rollback restores local artifacts only." in rendered
    assert "It does not undo network effects." in rendered
    assert "Probe Candidates failed with exit code 1." in rendered


def test_shortcuts_are_contextual_by_page() -> None:
    assert tui_app._shortcuts_for_tab("Home", pending_confirmation=False) != tui_app._shortcuts_for_tab("Route", pending_confirmation=False)
    assert "1 Home" in tui_app._shortcuts_for_tab("Home", pending_confirmation=False)
    assert "Apply" in tui_app._shortcuts_for_tab("Route", pending_confirmation=False)


def test_testing_action_notice_mentions_network_write_boundary() -> None:
    message = tui_app._build_testing_confirmation_message(
        {
            "settings": {"user_data_dir": "state_data"},
            "control_plane": {
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
                }
            },
        },
        action_key="fetch",
        action_label="Fetch Subscription",
    )

    assert "use network" in message
    assert "write artifacts under state_data" in message
    assert "will not modify production Xray/XrayR/x-ui" in message
    assert "Pending confirmation" not in message


def test_confirmation_body_explains_destructive_boundary() -> None:
    pending = tui_app.PendingAction(
        key="service_restart",
        title="Restart Managed Sidecar Service",
        requires_confirmation=True,
        risk_note="Restart only the managed service.",
    )

    body = tui_app._build_confirmation_body(pending)

    assert "Touches systemd: yes" in body
    assert "Does not modify production Xray/XrayR/x-ui." in body
    assert "Press Enter to confirm or Esc to cancel." in body


def test_route_select_value_is_blank_for_missing_candidate_or_empty_options() -> None:
    assert tui_app._resolve_route_select_value({"candidate_id": None}, []) is None
    assert tui_app._resolve_route_select_value({"candidate_id": "candidate-001"}, []) is None
    assert tui_app._resolve_route_select_value({"candidate_id": "candidate-001"}, [("US relay", "candidate-001")]) == "candidate-001"


def test_route_select_options_do_not_use_blank_string_sentinel() -> None:
    source = (Path(tui_app.__file__)).read_text(encoding="utf-8")

    assert '"Select.BLANK"' not in source
    assert "str(Select.BLANK)" not in source


def test_safe_refresh_redacts_exception_details_without_reraising(tmp_path: Path) -> None:
    captured: list[tuple[str, str]] = []
    journal_path = tmp_path / "action_journal.jsonl"

    def refresh() -> None:
        raise RuntimeError(
            "bad vless://uuid-raw@example.invalid:443?path=/secret "
            "11111111-2222-3333-4444-555555555555 "
            "server_name=example.invalid host=example.invalid path=/secret"
        )

    succeeded, safe_message = tui_app._run_safe_refresh(
        reason="startup",
        refresh_func=refresh,
        render_error=lambda title, message: captured.append((title, message)),
        journal_path=journal_path,
    )

    assert succeeded is False
    assert safe_message is not None
    assert captured
    assert captured[0][0] == "TUI refresh failed"
    assert "Sensitive details were hidden." in captured[0][1]
    assert "vless://" not in captured[0][1]
    assert "11111111-2222-3333-4444-555555555555" not in captured[0][1]
    assert "example.invalid" not in captured[0][1]
    assert journal_path.exists()


def test_on_mount_uses_safe_refresh_wrapper() -> None:
    source = (Path(tui_app.__file__)).read_text(encoding="utf-8")

    assert 'self._safe_refresh_ui("startup")' in source


def test_probe_command_preview_uses_user_data_dir_paths(tmp_path: Path) -> None:
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
                "user_data_dir: custom_state",
                "filters: {include_keywords: [], exclude_keywords: [], deprioritize_keywords: []}",
                "probe: {timeout_seconds: 5, concurrency: 1, cache_ttl_hours: 24, failure_backoff_hours: 24, allow_network_probe: false}",
                "xray: {binary_path: /usr/local/bin/xray, runtime_dir: .runtime, local_socks_host: 127.0.0.1, local_socks_port: 19080}",
                "output: {outbounds_path: generated/outbounds.json, routes_path: generated/routes.json, manifest_path: generated/manifest.json, history_dir: custom_state/history}",
                "generation: {tag_prefix: scholar-, max_passed_nodes: 2, fallback_blackhole_tag: blocked, previous_output_max_age_hours: 24}",
                "routing: {mode: dedicated_inbound, inbound_tags: [scholar-in], fail_closed: true}",
            ]
        ),
        encoding="utf-8",
    )

    workflow = tui_app.load_workflow_state(config_path=str(config_path))
    operations = workflow["control_plane"]["command_state"]["operations"]
    probe_spec = next(operation for operation in operations if operation["key"] == "probe")
    probe_command = probe_spec["command"]

    assert str(tmp_path / "custom_state" / "candidates.json") in probe_command
    assert str(tmp_path / "custom_state" / "probe_summary.json") in probe_command
    assert str(tmp_path / "custom_state" / "passed_candidates.json") in probe_command


def test_safe_wrapper_redacts_exception_and_journals(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("scholar_outbound_manager.tui.controller.load_control_plane_state", lambda **kwargs: _fake_control_plane_state())
    controller = tui_app.WorkflowController(loader_kwargs={}, action_journal_path=str(tmp_path / "action_journal.jsonl"))

    message, succeeded = tui_app._run_safe_tui_action(
        controller,
        "Probe",
        lambda: (_ for _ in ()).throw(
            ValueError(
                "raw_uri=vless://00000000-0000-0000-0000-000000000000@example.invalid "
                "password=secret server_name=fake.example.com host=fake.example.com path=/secret"
            )
        ),
    )

    rendered = (tmp_path / "action_journal.jsonl").read_text(encoding="utf-8")
    assert succeeded is False
    assert message is not None
    assert "vless://" not in message
    assert "00000000-0000-0000-0000-000000000000" not in message
    assert "fake.example.com" not in message
    assert "/secret" not in message
    assert "vless://" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered
    assert "fake.example.com" not in rendered
    assert "/secret" not in rendered


def _fake_control_plane_state() -> ControlPlaneState:
    return ControlPlaneState(
        workspace="/tmp/workspace",
        tabs=["Home", "Settings", "Testing", "Route", "Logs"],
        config_state=ConfigState(True, True, False, False, "preview", "", [], 1, False, "dedicated_inbound", True),
        config_form_state=ConfigFormState(fields=[], dirty=False, valid=True, validation_errors=[], redacted_diff=""),
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
            [OperationSpec("artifact_check", "Check Artifact Lineage", ["artifact-check"], False, False, False, False, [])],
        ),
        operation_availability=OperationAvailability(True, False, False, False, False, False, False, True, False, False, True, False),
        sidecar_state=SidecarState("unknown", "unknown", "unknown", "unknown", "warn", True, "/usr/local/bin/xray"),
        pool_state=PoolState(False, [], "warn"),
        warnings=[],
        last_action=None,
        session={"schema_version": 1, "updated_at": "2026-06-04T00:00:00Z", "workspace": "/tmp/workspace", "last_step": None, "paths": {"config": "config.yaml"}, "last_results": {}},
        snippets={"warning": "snippet warning", "rendered": "[]"},
        repo_status="clean",
        current_git_commit="abc1234",
        venv_detected=True,
        current_sidecar_port=19080,
    )
