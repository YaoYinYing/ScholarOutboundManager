"""Optional workflow-oriented Textual TUI entry point and helpers."""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import asdict
from dataclasses import replace
from pathlib import Path

from scholar_outbound_manager.selection import build_selected_candidate_artifact
from scholar_outbound_manager.selection import load_candidate_payload
from scholar_outbound_manager.selection import select_candidate_by_index
from scholar_outbound_manager.selection import write_selected_candidate_artifact
from scholar_outbound_manager.tui.action_runner import ActionResult
from scholar_outbound_manager.tui.action_runner import load_last_action
from scholar_outbound_manager.tui.artifact_rollback import ArtifactSnapshot
from scholar_outbound_manager.tui.artifact_rollback import list_artifact_snapshots
from scholar_outbound_manager.tui.action_runner import FakeActionRunner
from scholar_outbound_manager.tui.action_runner import append_action_journal
from scholar_outbound_manager.tui.action_policy import get_action_policy
from scholar_outbound_manager.tui.backend import CallbackBackend
from scholar_outbound_manager.tui.config_centered import build_first_run_wizard_state
from scholar_outbound_manager.tui.config_centered import summarize_config_centered_state
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_SESSION_PATH
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ACTION_JOURNAL_PATH
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ARTIFACT_SNAPSHOT_ROOT
from scholar_outbound_manager.tui.control_plane import ControlPlaneState
from scholar_outbound_manager.tui.control_plane import control_plane_state_to_dict
from scholar_outbound_manager.tui.control_plane import load_control_plane_state
from scholar_outbound_manager.tui.controller import WorkbenchMessage
from scholar_outbound_manager.tui.controller import WorkbenchController as BaseWorkbenchController
from scholar_outbound_manager.tui.controller import PendingAction
from scholar_outbound_manager.tui.detail_model import build_route_detail_body
from scholar_outbound_manager.tui.detail_model import build_testing_detail_body
from scholar_outbound_manager.tui.effect_runner import EffectRunner
from scholar_outbound_manager.tui.effects import CreateSnapshot
from scholar_outbound_manager.tui.effects import Effect
from scholar_outbound_manager.tui.events import ActionCompleted
from scholar_outbound_manager.tui.events import ActionFailed
from scholar_outbound_manager.tui.events import AppStateReloaded
from scholar_outbound_manager.tui.events import ArtifactRefresh
from scholar_outbound_manager.tui.events import EffectFailed
from scholar_outbound_manager.tui.events import HelpRequested
from scholar_outbound_manager.tui.events import ModalCancel
from scholar_outbound_manager.tui.events import ModalConfirm
from scholar_outbound_manager.tui.events import Navigate
from scholar_outbound_manager.tui.events import ProbeProcessCompleted
from scholar_outbound_manager.tui.events import ProbeEventReceived
from scholar_outbound_manager.tui.events import ProbeFailed
from scholar_outbound_manager.tui.events import ProbeStarted
from scholar_outbound_manager.tui.events import RefreshRequested
from scholar_outbound_manager.tui.events import RouteCandidateChosen
from scholar_outbound_manager.tui.events import RouteInspectSelected
from scholar_outbound_manager.tui.events import PortCheckCompleted
from scholar_outbound_manager.tui.events import RouteSelectRow
from scholar_outbound_manager.tui.events import RouteTestPortRequested
from scholar_outbound_manager.tui.events import TestingFetchRequested
from scholar_outbound_manager.tui.events import TestingInspectSelected
from scholar_outbound_manager.tui.events import TestingMoveCursor
from scholar_outbound_manager.tui.events import TestingProbeRequested
from scholar_outbound_manager.tui.events import TestingStopRequested
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.reducer import reduce_app_state
from scholar_outbound_manager.tui.route_model import add_route_entry
from scholar_outbound_manager.tui.route_model import build_route_workbench_state
from scholar_outbound_manager.tui.route_model import check_selected_route_port
from scholar_outbound_manager.tui.route_model import delete_route_entry
from scholar_outbound_manager.tui.route_model import route_workbench_state_to_dict
from scholar_outbound_manager.tui.route_model import save_route_draft_state
from scholar_outbound_manager.tui.route_model import save_route_entries_to_config_or_selected_routes
from scholar_outbound_manager.tui.route_model import update_route_entry_candidate
from scholar_outbound_manager.tui.route_store import build_route_store_state
from scholar_outbound_manager.tui.screens import build_ascii_tab_strip
from scholar_outbound_manager.tui.state import AppState
from scholar_outbound_manager.tui.state import KeyHint
from scholar_outbound_manager.tui.state import NavState
from scholar_outbound_manager.tui.state import StatusBarState
from scholar_outbound_manager.tui.state import build_session_state
from scholar_outbound_manager.tui.state import write_session_state
from scholar_outbound_manager.tui.testing_model import build_testing_screen_state
from scholar_outbound_manager.tui.testing_model import testing_screen_state_to_dict
from scholar_outbound_manager.tui.testing_events import TestingEvent
from scholar_outbound_manager.tui.testing_events import render_testing_event_line
from scholar_outbound_manager.tui.testing_jobs import TestingJobState
from scholar_outbound_manager.tui.testing_store import build_testing_store_state
from scholar_outbound_manager.tui.view_model import ActivateStep
from scholar_outbound_manager.tui.view_model import build_home_cards
from scholar_outbound_manager.tui.view_model import build_logs_summary
from scholar_outbound_manager.tui.view_model import RouteSummary
from scholar_outbound_manager.tui.view_model import SettingsFieldView
from scholar_outbound_manager.tui.view_model import build_activate_steps
from scholar_outbound_manager.tui.view_model import build_route_candidate_display
from scholar_outbound_manager.tui.view_model import build_operation_impact
from scholar_outbound_manager.tui.view_model import build_route_detail
from scholar_outbound_manager.tui.view_model import build_route_table_model
from scholar_outbound_manager.tui.view_model import build_route_summaries
from scholar_outbound_manager.tui.view_model import build_settings_summary
from scholar_outbound_manager.tui.view_model import build_settings_groups
from scholar_outbound_manager.tui.view_model import build_testing_table_model
from scholar_outbound_manager.tui.view_model import build_workflow_summary
from scholar_outbound_manager.tui.view_model import redact_text
from scholar_outbound_manager.tui.view_model import resolve_next_action
from scholar_outbound_manager.tui.view_model import truncate_display_value
from scholar_outbound_manager.tui.workflow import MAIN_TABS


TUI_KEY_BINDINGS: tuple[tuple[str, str, str], ...] = (
    ("1", "open_home", "Home"),
    ("2", "open_settings", "Settings"),
    ("3", "open_testing", "Testing"),
    ("4", "open_route", "Route"),
    ("5", "open_logs", "Logs"),
    ("q", "quit", "Quit"),
    ("r", "reload_state", "Reload State"),
    ("j", "cursor_down", "Move Down"),
    ("k", "cursor_up", "Move Up"),
    ("enter", "confirm_selected", "Confirm"),
    ("i", "open_detail", "Detail"),
    ("escape", "cancel_pending", "Cancel Pending"),
    ("e", "edit_config_field", "Edit Config Field"),
    ("d", "show_config_diff", "Show Config Diff"),
    ("s", "save_draft", "Save Draft"),
    ("u", "undo_save", "Undo Save"),
    ("f", "run_fetch", "Run Fetch"),
    ("t", "run_probe", "Run Probe"),
    ("shift+f", "run_retest_failed", "Retest Failed"),
    ("c", "run_artifact_check", "Run Artifact Check"),
    ("a", "run_select", "Run Select"),
    ("shift+a", "run_stage_sidecar", "Run Stage Sidecar"),
    ("shift+r", "run_restart_sidecar", "Restart Sidecar"),
    ("shift+s", "route_start_placeholder", "Start Sidecar"),
    ("shift+x", "route_stop_placeholder", "Stop Sidecar"),
    ("v", "run_validate_sidecar", "Run Validate"),
    ("x", "contextual_x", "Contextual X"),
    ("z", "rollback_latest_snapshot", "Rollback Latest Snapshot"),
    ("?", "show_help", "Help"),
)

class WorkflowController(BaseWorkbenchController):
    """Compatibility wrapper that exposes workbench state for the TUI app/tests."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.workflow_state = _build_workflow_state(self)

    def reload(self) -> None:
        super().reload()
        self.workflow_state = _build_workflow_state(self)

    def handle_operation(self, action_key: str) -> str:
        message = super().handle_operation(action_key)
        self.workflow_state = _build_workflow_state(self)
        return message

    def update_config_field(self, field_key: str, value: object) -> str:
        result = super().update_config_field(field_key, value)
        self.workflow_state = _build_workflow_state(self)
        return result.message

    def undo_config_save(self) -> str:
        result = super().undo_config()
        self.workflow_state = _build_workflow_state(self)
        return result.message

    def create_snapshot(self, reason: str = "manual_tui_snapshot") -> ArtifactSnapshot:
        snapshot = super().create_snapshot(reason)
        self.workflow_state = _build_workflow_state(self)
        return snapshot

    def create_snapshot_message(self, reason: str = "manual_tui_snapshot") -> str:
        snapshot = self.create_snapshot(reason)
        return f"Created artifact snapshot {snapshot.snapshot_id}."

    def rollback_latest_snapshot(self) -> str:
        if self.pending_action is not None and self.pending_action.key == "rollback_snapshot":
            result = super().confirm_action("rollback_snapshot")
            self.workflow_state = _build_workflow_state(self)
            return result.summary
        pending = super().prepare_action("rollback_snapshot")
        self.workflow_state = _build_workflow_state(self)
        return f"Pending confirmation: press rollback again to run {pending.title}."


def _format_last_action(last_action: dict[str, object] | None) -> str:
    if not isinstance(last_action, dict) or not last_action:
        return "none"
    title = str(last_action.get("title") or last_action.get("key") or "unknown")
    exit_code = last_action.get("exit_code")
    succeeded = last_action.get("succeeded")
    summary = str(last_action.get("summary") or "")
    stderr_tail = str(last_action.get("redacted_stderr_tail") or "")
    parts = [f"title={title}", f"succeeded={succeeded}", f"exit_code={exit_code}"]
    if summary:
        parts.append(f"summary={summary}")
    if stderr_tail:
        parts.append(f"stderr_tail={stderr_tail}")
    rollback_hint = str(last_action.get("rollback_hint") or "")
    if rollback_hint:
        parts.append(f"rollback_hint={rollback_hint}")
    return "; ".join(parts)


def _tab_body_id(tab: str) -> str:
    """Return one stable Static body id for a workflow tab."""
    return f"{_textual_safe_id(tab)}-body"


def redact_exception_message(message: str) -> str:
    """Return one review-safe TUI error summary."""
    redacted = redact_text(message)
    redacted = re.sub(r"\b(AppState|CandidateTestRow|RouteStoreState|RouteCandidateOption)\([^)]*\)", "<redacted runtime state>", redacted)
    if len(redacted) <= 240:
        return redacted
    return redacted[:237] + "..."


def _build_refresh_error_body(safe_message: str) -> str:
    """Build one redacted refresh failure panel body."""
    return "\n".join(
        [
            "A UI refresh error occurred. Sensitive details were hidden.",
            "",
            f"Reason: {safe_message}",
            "",
            "Suggested recovery:",
            "- Press r to reload.",
            "- Check artifact consistency in Logs.",
            "- Run Test Nodes if testing artifacts are stale.",
            "- Quit and reopen if the error persists.",
        ]
    )


def _run_safe_refresh(
    *,
    reason: str,
    refresh_func: Callable[[], None],
    render_error: Callable[[str, str], None],
    journal_path: Path | None = None,
) -> tuple[bool, str | None]:
    """Run one refresh path without leaking raw traceback locals into the TUI."""
    try:
        refresh_func()
    except Exception as exc:
        safe_message = redact_exception_message(str(exc))
        if journal_path is not None:
            append_action_journal(
                ActionResult(
                    key="tui_refresh_error",
                    title=f"TUI refresh failed during {reason}",
                    command=["internal", "tui_refresh_error"],
                    started_at="",
                    finished_at="",
                    exit_code=126,
                    succeeded=False,
                    stdout="",
                    stderr=safe_message,
                    redacted_stdout="",
                    redacted_stderr=safe_message,
                    summary=safe_message,
                    expected_artifacts=[],
                    warnings=["UI refresh failed before backend execution completed."],
                ),
                journal_path=journal_path,
            )
        render_error("TUI refresh failed", _build_refresh_error_body(safe_message))
        return False, safe_message
    return True, None


def _build_route_select_options(route_state: dict[str, object]) -> list[tuple[str, str]]:
    """Build passed-candidate Select options for the Route editor."""
    options: list[tuple[str, str]] = []
    for option in route_state.get("passed_candidates", []) if isinstance(route_state.get("passed_candidates"), list) else []:
        if not isinstance(option, dict):
            continue
        options.append(
            (
                f"{option['label']} · {option['region_hint'] or '-'} · {option['protocol']} · {option['stage']}",
                str(option["candidate_id"]),
            )
        )
    return options


def _resolve_route_select_value(
    route_entry: dict[str, object],
    options: Sequence[tuple[str, str]],
) -> str | None:
    """Resolve the current Route selector value without stringifying blank sentinels."""
    candidate_id = route_entry.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        return None
    option_values = {value for _, value in options}
    if candidate_id not in option_values:
        return None
    return candidate_id


def _should_ignore_route_select_change(
    *,
    route_form_syncing: bool,
    event_value: object,
    current_candidate_id: str | None,
) -> bool:
    """Return whether a Route Select change should be ignored as non-user intent."""
    if route_form_syncing:
        return True
    if event_value is None:
        return True
    if not isinstance(event_value, str) or not event_value:
        return True
    if event_value == current_candidate_id:
        return True
    return False


def _refresh_tab_bodies(
    tabs: list[str],
    workflow_state: dict[str, object],
    update_body: Callable[[str, str], None],
) -> None:
    """Refresh all rendered tab bodies after one state mutation."""
    for tab in tabs:
        update_body(_tab_body_id(tab), render_tab_text(tab, workflow_state))


def _run_safe_tui_action(
    controller: WorkflowController,
    description: str,
    func: Callable[[], str | None],
) -> tuple[str | None, bool]:
    """Run one TUI action without letting raw exceptions escape into Textual tracebacks."""
    try:
        message = func()
    except Exception as exc:
        safe_message = redact_exception_message(str(exc))
        append_action_journal(
            ActionResult(
                key="tui_safe_error",
                title=description,
                command=["internal", "tui_safe_error"],
                started_at="",
                finished_at="",
                exit_code=126,
                succeeded=False,
                stdout="",
                stderr=safe_message,
                redacted_stdout="",
                redacted_stderr=safe_message,
                summary=safe_message,
                expected_artifacts=[],
                warnings=["UI action failed before backend execution."],
            ),
            journal_path=controller._action_journal_path,  # type: ignore[attr-defined]
        )
        controller.message = WorkbenchMessage("error", description, safe_message)
        controller.action_state.status_message = safe_message
        controller.workflow_state = _build_workflow_state(controller)
        return f"{description} failed: {safe_message}", False
    controller.workflow_state = _build_workflow_state(controller)
    return message, True


def _apply_testing_event_to_rows(rows: list[dict[str, object]], event: TestingEvent) -> list[dict[str, object]]:
    """Apply one Testing event to plain row dictionaries."""
    updated_rows = [dict(row) for row in rows]
    for row in updated_rows:
        if event.candidate_id and row.get("candidate_id") == event.candidate_id:
            if event.status is not None:
                row["status_icon"] = event.status
            if event.stage is not None:
                row["stage"] = event.stage
            if event.home_status is not None:
                row["home_status"] = event.home_status
            if event.query_status is not None:
                row["query_status"] = event.query_status
            if event.latency_ms is not None:
                row["latency_ms"] = event.latency_ms
            if event.markers:
                row["markers"] = event.markers
    return updated_rows


def _format_health(state: str) -> str:
    return {
        "ok": "OK",
        "warning": "Warning",
        "blocked": "Blocked",
        "unknown": "Unknown",
    }.get(state, state.title())


def _find_operation(workflow_state: dict[str, object], key: str) -> dict[str, object] | None:
    operations = workflow_state.get("control_plane", {}).get("command_state", {}).get("operations", [])
    for operation in operations:
        if isinstance(operation, dict) and operation.get("key") == key:
            return operation
    return None


def _render_testing_summary_lines(testing_state: dict[str, object]) -> list[str]:
    summary = testing_state.get("summary", {}) if isinstance(testing_state.get("summary"), dict) else {}
    return [
        f"Catalog: Total {summary.get('total_candidates') or 0} | Testable {summary.get('testable_candidates') or 0} | Visible {summary.get('visible_rows') or 0}",
        f"Probe: Tested {summary.get('attempted') or 0} / {summary.get('testable_candidates') or 0} | Passed {summary.get('passed') or 0} | Failed {summary.get('failed') or 0} | Skipped {summary.get('skipped') or 0}",
        f"Rows: Pending {summary.get('pending') or 0} | Running {summary.get('running') or 0} | Stale {summary.get('stale') or 0} | Experimental disabled {summary.get('experimental_disabled') or 0}",
        f"Table: {str(summary.get('table_scope') or 'all_candidates').replace('_', ' ')}",
    ]


def _render_testing_inspector_text(testing_state: dict[str, object]) -> str:
    inspector = testing_state.get("inspector", {}) if isinstance(testing_state.get("inspector"), dict) else {}
    markers = inspector.get("markers")
    marker_text = ", ".join(str(marker) for marker in markers) if isinstance(markers, (list, tuple)) and markers else "none"
    lines = [
        "Selected candidate",
        "",
        f"Label: {inspector.get('label') or 'none'}",
        f"Region: {inspector.get('region_hint') or '-'}",
        f"Protocol: {inspector.get('protocol') or '-'}",
        f"Candidate ID: {inspector.get('candidate_id') or '-'}",
        f"Scholar: {inspector.get('scholar_stage') or '-'}",
        f"Home: {inspector.get('home_status') or '-'}",
        f"Query: {inspector.get('query_status') or '-'}",
        f"Latency: {inspector.get('latency_ms') or '-'}",
        f"Markers: {marker_text}",
        f"Selected for route: {'yes' if inspector.get('selected_for_route') else 'no'}",
        "",
        f"Meaning: {inspector.get('explanation') or '-'}",
    ]
    warning = inspector.get("artifact_warning")
    if isinstance(warning, str) and warning:
        lines.extend(["", f"Artifact warning: {warning}"])
    return "\n".join(lines)


def _build_testing_confirmation_message(
    workflow_state: dict[str, object],
    *,
    action_key: str,
    action_label: str,
) -> str:
    operation = _find_operation(workflow_state, action_key)
    impact = build_operation_impact(operation, action_label=action_label)
    user_data_dir = str(workflow_state.get("settings", {}).get("user_data_dir") or "user_data_dir")
    lines = [
        f"{action_label} is a live Testing action.",
        f"This will {'use network' if impact.uses_network else 'stay local'}, write artifacts under {user_data_dir}, and will not modify production Xray/XrayR/x-ui.",
    ]
    if impact.touches_system:
        lines.append("This action can touch a managed system service.")
    return " ".join(lines)


def _testing_banner_text(artifact_warning: str | None) -> str:
    lines = [
        "Fetch/Test are live network operations.",
        "They write local artifacts under user_data_dir.",
        "They do not modify production Xray/XrayR/x-ui.",
        "Progress may be phase-level only when per-candidate streaming is unavailable.",
    ]
    if artifact_warning:
        lines.extend(["", artifact_warning])
    return "\n".join(lines)


def _pending_title_for_action(action_key: str) -> str:
    titles = {
        "sidecar_stage": "Apply Route",
        "service_start": "Start Managed Sidecar Service",
        "service_stop": "Stop Managed Sidecar Service",
        "service_restart": "Restart Managed Sidecar Service",
        "rollback_snapshot": "Rollback Artifact Snapshot",
    }
    return titles.get(action_key, action_key.replace("_", " ").title())


def _build_confirmation_body(pending: PendingAction) -> str:
    policy = get_action_policy(pending.key)
    lines = [
        pending.title,
        "",
        f"Risk: {policy.user_facing_risk}",
        f"Changes local artifacts: {'yes' if policy.writes_artifact else 'no'}",
        f"Touches managed service: {'yes' if policy.mutates_service else 'no'}",
        f"Touches systemd: {'yes' if policy.systemd_access else 'no'}",
        "Does not modify production Xray/XrayR/x-ui.",
        "",
        "Press Enter to confirm or Esc to cancel.",
    ]
    return "\n".join(lines)


def _selected_cursor_candidate_id(workbench: dict[str, object]) -> str | None:
    rows = workbench.get("selection_rows", [])
    selection = workbench.get("selection", {})
    if not isinstance(rows, list) or not isinstance(selection, dict):
        return None
    selected_index = selection.get("selected_candidate_index")
    if not isinstance(selected_index, int) or selected_index < 0 or selected_index >= len(rows):
        return None
    row = rows[selected_index]
    if not isinstance(row, dict):
        return None
    candidate_id = row.get("candidate_id")
    return str(candidate_id) if isinstance(candidate_id, str) else None


def _shortcuts_for_tab(tab: str, *, pending_confirmation: bool) -> str:
    if pending_confirmation:
        return "Keys: Enter confirm | Esc cancel | q quit"
    shortcuts = {
        "Home": "Keys: 1 Home | 2 Settings | 3 Testing | 4 Route | 5 Logs | r Refresh | q Quit",
        "Settings": "Keys: s Save | u Undo | d Diff | f Test Fetch | q Quit",
        "Testing": "Keys: f Fetch | t Test Nodes | F Retest Failed | x Stop | j/k Move | Enter Inspect | q Quit",
        "Route": "Keys: a Add Route | d Delete Route | c Choose | p Test Port | A Apply | S Start | X Stop | R Restart | v Validate | Enter Detail | q Quit",
        "Logs": "Keys: c Artifact Check | x Snapshot | z Rollback | q Quit",
    }
    return shortcuts.get(tab, "Keys: 1-5 pages | r refresh | q quit")


def _key_hints_for_page(page: str) -> list[KeyHint]:
    """Build contextual key hints for one active page."""
    mapping = {
        "home": [("1", "Home"), ("2", "Settings"), ("3", "Testing"), ("4", "Route"), ("5", "Logs"), ("r", "Refresh"), ("q", "Quit")],
        "settings": [("s", "Save"), ("u", "Undo"), ("d", "Diff"), ("f", "Test Fetch"), ("q", "Quit")],
        "testing": [("f", "Fetch"), ("t", "Test Nodes"), ("x", "Stop"), ("j/k", "Move"), ("Enter", "Detail"), ("q", "Quit")],
        "route": [("a", "Add"), ("d", "Delete"), ("c", "Choose"), ("p", "Test Port"), ("A", "Apply"), ("Enter", "Detail"), ("q", "Quit")],
        "logs": [("c", "Artifact Check"), ("x", "Snapshot"), ("z", "Rollback"), ("q", "Quit")],
    }
    return [KeyHint(key=key, label=label) for key, label in mapping.get(page, [("q", "Quit")])]


def _render_route_table(routes: list[RouteSummary]) -> list[str]:
    if not routes:
        return ["  No routes are available yet."]
    lines = [
        "  #   Region       Provider         Protocol   Latency   Result   Note",
    ]
    for route in routes[:8]:
        result = "Passed" if route.passed else "Review"
        prefix = ">" if route.is_cursor else " "
        lines.append(
            f"{prefix} {route.index:<2}  {route.region:<12} {route.provider:<16} {route.protocol:<9} "
            f"{route.latency_label:<8} {result:<8} {route.note}"
        )
    return lines


def _render_activate_steps(steps: list[ActivateStep]) -> list[str]:
    lines: list[str] = []
    for index, step in enumerate(steps, start=1):
        lines.append(f"  {index}. {step.title:<32} {step.status}")
        lines.append(f"     {step.note}")
    return lines


def _render_settings_groups(groups: dict[str, list[SettingsFieldView]]) -> list[str]:
    lines = [
        "Sensitive values are hidden: subscription URLs, proxy URLs, UUIDs, passwords, tokens, public keys, server names, and obfs passwords.",
    ]
    for title, fields in groups.items():
        lines.append("")
        lines.append(title)
        if not fields:
            lines.append("  No editable fields in this group.")
            continue
        for field in fields:
            suffix = "    restart required" if field.restart_required else ""
            lines.append(f"  {field.title}: {field.value}{suffix}")
    return lines


def _render_logs_history(workbench: dict[str, object]) -> list[str]:
    history = workbench.get("action_history", [])
    if not isinstance(history, list) or not history:
        return ["  No actions recorded in this session."]
    lines: list[str] = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        status = "OK" if entry.get("succeeded") else "Failed"
        lines.append(f"  {entry.get('created_at')}  {entry.get('title') or entry.get('key')}  {status}")
    return lines


def _render_logs_snapshots(workbench: dict[str, object]) -> list[str]:
    snapshots = workbench.get("snapshots", [])
    if not isinstance(snapshots, list) or not snapshots:
        return ["  No local file snapshots are recorded."]
    first = snapshots[0]
    if not isinstance(first, dict):
        return ["  No local file snapshots are recorded."]
    return [
        f"  Latest: {first.get('snapshot_id')}",
        f"  Reason: {first.get('reason')}",
    ]


def _enabled_label(value: str) -> str:
    normalized = str(value or "unknown")
    return {
        "true": "Enabled",
        "false": "Disabled",
        "unknown": "Unknown",
    }.get(normalized, normalized.title())


def _last_check_label(value: str) -> str:
    normalized = str(value or "unknown")
    return "Never" if normalized == "unknown" else normalized


def _textual_safe_id(value: str) -> str:
    """Return one Textual-compatible widget id."""
    lowered = value.strip().lower()
    safe = re.sub(r"[^a-z0-9_-]+", "-", lowered).strip("-")
    if not safe:
        safe = "tab"
    if safe[0].isdigit():
        safe = f"tab-{safe}"
    return safe


def _build_tab_specs(tabs: list[str]) -> tuple[list[dict[str, str]], str]:
    """Return workflow tab titles plus safe ids and one initial safe id."""
    if not tabs:
        return [], "tab"
    counts: dict[str, int] = {}
    specs: list[dict[str, str]] = []
    initial_id = "tab"
    for index, tab in enumerate(tabs):
        base = _textual_safe_id(tab)
        count = counts.get(base, 0) + 1
        counts[base] = count
        safe_id = base if count == 1 else f"{base}-{count}"
        specs.append({"title": tab, "id": safe_id})
        if (tab == "Home" and initial_id == "tab") or index == 0:
            initial_id = safe_id if tab == "Home" else initial_id
    if initial_id == "tab":
        initial_id = specs[0]["id"]
    return specs, initial_id


def build_parser() -> argparse.ArgumentParser:
    """Build the TUI-specific parser."""
    parser = argparse.ArgumentParser(prog="scholar-outbound-manager-tui")
    parser.add_argument("config", nargs="?", default="config.yaml")
    parser.add_argument("--candidates", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--probe-summary", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--passed-candidates", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--selected-candidate", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--pool-plan", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--session", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--output", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--strategy", default="auto", choices=("auto", "manual", "geo_nearest", "geo-nearest", "region_hint", "region-hint", "first"))
    parser.add_argument("--geo-cache", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--host-geo", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--preferred-region-hint")
    parser.add_argument("--prefer-geo", dest="prefer_geo", action="store_true", default=True)
    parser.add_argument("--no-prefer-geo", dest="prefer_geo", action="store_false")
    return parser


def load_dashboard_state(
    *,
    candidates_path: str | Path,
    output_path: str | Path,
    strategy: str = "auto",
    geo_cache_path: str = "state_data/geo/candidate_geo_cache.json",
    host_geo_path: str = "state_data/geo/host_geo.json",
    prefer_geo: bool = True,
    preferred_region_hint: str | None = None,
) -> dict[str, object]:
    """Load the redacted dashboard state without importing Textual."""
    control_plane = load_control_plane_state(
        candidates_path=str(candidates_path),
        passed_candidates_path=str(candidates_path),
        action_journal_path=DEFAULT_TUI_ACTION_JOURNAL_PATH,
        output_path=str(output_path),
        strategy=strategy,
        geo_cache_path=geo_cache_path,
        host_geo_path=host_geo_path,
        prefer_geo=prefer_geo,
        preferred_region_hint=preferred_region_hint,
    )
    return {
        "candidates_path": str(candidates_path),
        "output_path": str(output_path),
        "rows": list(control_plane.selection_state.rows),
        "selected_index": 0 if control_plane.selection_state.rows else None,
        "selected_candidate_id": control_plane.selection_state.selected_candidate_id,
        "selection_method": control_plane.selection_state.selection_method,
        "selection_reason": control_plane.selection_state.selection_reason,
    }


def load_workflow_state(
    *,
    config_path: str = "config.yaml",
    candidates_path: str | None = None,
    probe_summary_path: str | None = None,
    passed_candidates_path: str | None = None,
    selected_candidate_path: str | None = None,
    pool_plan_path: str | None = None,
    session_path: str | None = None,
    action_journal_path: str | None = None,
    snapshot_root: str | None = None,
    output_path: str | None = None,
    strategy: str = "auto",
    geo_cache_path: str | None = None,
    host_geo_path: str | None = None,
    prefer_geo: bool = True,
    preferred_region_hint: str | None = None,
) -> dict[str, object]:
    """Build a workflow-oriented, redacted TUI state model."""
    resolved_paths = resolve_user_data_paths(config_path)
    control_plane = load_control_plane_state(
        config_path=config_path,
        candidates_path=str(resolved_paths.candidates if candidates_path is None else candidates_path),
        probe_summary_path=str(resolved_paths.probe_summary if probe_summary_path is None else probe_summary_path),
        passed_candidates_path=str(resolved_paths.passed_candidates if passed_candidates_path is None else passed_candidates_path),
        selected_candidate_path=str(resolved_paths.selected_candidate if selected_candidate_path is None else selected_candidate_path),
        pool_plan_path=str(resolved_paths.pool_plan if pool_plan_path is None else pool_plan_path),
        session_path=str(resolved_paths.session if session_path is None else session_path),
        action_journal_path=str(resolved_paths.action_journal if action_journal_path is None else action_journal_path),
        snapshot_root=str(resolved_paths.snapshot_root if snapshot_root is None else snapshot_root),
        output_path=str(resolved_paths.selected_candidate if output_path is None else output_path),
        strategy=strategy,
        geo_cache_path=str(resolved_paths.geo_cache if geo_cache_path is None else geo_cache_path),
        host_geo_path=str(resolved_paths.host_geo if host_geo_path is None else host_geo_path),
        prefer_geo=prefer_geo,
        preferred_region_hint=preferred_region_hint,
    )
    return control_plane_state_to_workflow_dict(control_plane)


def build_app_state(
    *,
    controller: WorkflowController,
    config_path: str,
    active_page: str = "home",
    testing_selected_index: int | None = None,
    route_selected_index: int = 0,
    route_port_results: dict[str, object] | None = None,
) -> AppState:
    """Build one store-driven AppState from canonical artifacts and control-plane summaries."""
    control_plane = controller.state
    resolved_paths = resolve_user_data_paths(config_path)
    config_summary = summarize_config_centered_state(config_path)
    testing = build_testing_store_state(
        config_path=config_path,
        user_data_paths=resolved_paths,
        selected_index=testing_selected_index,
    )
    route = build_route_store_state(
        config_path=config_path,
        user_data_paths=resolved_paths,
        selected_index=route_selected_index,
        port_results=route_port_results if isinstance(route_port_results, dict) else None,
    )
    status = StatusBarState(
        message=None,
        level=None,
        keys=tuple(_key_hints_for_page(active_page)),
    )
    return AppState(
        nav=NavState(active_page=active_page),
        settings=_build_settings_state(config_summary, control_plane),
        testing=testing,
        route=route,
        logs=_build_logs_state(resolved_paths, control_plane),
        modal=None,
        status_bar=status,
        user_data_paths=resolved_paths,
        config_path=Path(config_path),
    )


def _build_settings_state(config_summary, control_plane: ControlPlaneState) -> dict[str, object]:
    return {
        "config_path": config_summary.config_path,
        "user_data_dir": config_summary.user_data_dir,
        "subscription_url_configured": config_summary.subscription_url_configured,
        "subscription_url_masked": config_summary.subscription_url_masked,
        "subscription_user_agent": config_summary.subscription_user_agent,
        "xray_binary_path": config_summary.xray_binary_path,
        "fail_closed": config_summary.fail_closed,
        "experimental_hysteria2": config_summary.experimental_hysteria2,
        "service_name": config_summary.service_name,
        "probe_concurrency": config_summary.probe_concurrency,
        "undo_available": control_plane.config_state.undo_available,
        "redacted_diff": control_plane.config_state.redacted_diff,
        "service_active": control_plane.sidecar_state.service_active,
        "service_enabled": control_plane.sidecar_state.service_enabled,
        "socks_status": control_plane.sidecar_state.socks_tcp_connect,
        "last_validation": control_plane.sidecar_state.last_validation,
        "next_recommended_action": control_plane.workflow_state.next_recommended_action,
    }


def _build_logs_state(user_data_paths, control_plane: ControlPlaneState) -> dict[str, object]:
    snapshots = list_artifact_snapshots(user_data_paths.snapshot_root)
    latest_action = None if control_plane.last_action is None else asdict(control_plane.last_action)
    return {
        "last_action": latest_action,
        "snapshot_rows": [
            [snapshot.snapshot_id, snapshot.reason]
            for snapshot in snapshots[:12]
        ],
        "action_rows": []
        if latest_action is None
        else [[
            str(latest_action.get("title") or latest_action.get("key") or "Action"),
            "ok" if latest_action.get("succeeded") else "review",
            truncate_display_value(str(latest_action.get("summary") or ""), limit=60),
        ]],
        "rollback_warning": [
            "Artifact rollback restores local artifacts only.",
            "It does not undo network effects.",
            "It does not restart sidecar.",
            "It does not modify production Xray/XrayR/x-ui.",
        ],
    }


def control_plane_state_to_workflow_dict(control_plane: ControlPlaneState) -> dict[str, object]:
    """Adapt the control-plane dataclass tree to the legacy workflow-state shape."""
    payload = control_plane_state_to_dict(control_plane)
    config_path = str(payload["session"]["paths"]["config"])
    resolved_paths = resolve_user_data_paths(config_path)
    config_summary = summarize_config_centered_state(config_path)
    testing_screen = build_testing_screen_state(config_path=config_path, user_data_paths=resolved_paths)
    route_workbench = build_route_workbench_state(config_path=config_path, user_data_paths=resolved_paths)
    testing_summary = testing_screen.summary
    wizard = build_first_run_wizard_state(config_path)
    route_count = len(config_summary.route_entries)
    enabled_route_count = sum(1 for row in config_summary.route_entries if row.get("enabled") is True)
    latest_action = payload["last_action"]
    return {
        "tabs": payload["tabs"],
        "tab_strip": build_ascii_tab_strip(),
        "wizard": {
            "active": wizard.active,
            "config_path": wizard.config_path,
            "user_data_dir": wizard.user_data_dir,
            "xray_binary_path": wizard.xray_binary_path,
            "subscription_url_configured": wizard.subscription_url_configured,
            "steps": list(wizard.step_titles),
            "redacted_preview": wizard.redacted_preview,
        },
        "home": {
            "config_path": config_summary.config_path,
            "user_data_dir": config_summary.user_data_dir,
            "subscription_configured": config_summary.subscription_url_configured,
            "last_fetch_status": testing_summary.last_fetch_status,
            "candidate_count": testing_summary.candidate_count,
            "supported_count": testing_summary.supported_count,
            "experimental_disabled_count": testing_summary.experimental_disabled_count,
            "tested_count": testing_summary.attempted_count,
            "passed_count": testing_summary.passed_count,
            "failed_count": testing_summary.failed_count,
            "last_probe_status": testing_summary.last_probe_status,
            "full_access_count": testing_summary.full_access_count,
            "query_blocked_count": testing_summary.query_blocked_count,
            "transport_failed_count": testing_summary.transport_failed_count,
            "route_count": route_count,
            "enabled_route_count": enabled_route_count,
            "selected_candidate_count": 1 if payload["selection_state"]["selected_candidate_id"] else 0,
            "selected_candidate_label": payload["selection_state"]["selected_candidate_label"],
            "active_listen_ports": config_summary.selected_ports,
            "service_active": payload["sidecar_state"]["service_active"],
            "service_enabled": payload["sidecar_state"]["service_enabled"],
            "socks_status": payload["sidecar_state"]["socks_tcp_connect"],
            "last_validation": payload["sidecar_state"]["last_validation"],
            "next_recommended_action": payload["workflow_state"]["next_recommended_action"],
            "latest_action_summary": None if latest_action is None else latest_action.get("summary"),
        },
        "settings": {
            "config_path": config_summary.config_path,
            "user_data_dir": config_summary.user_data_dir,
            "subscription_url_configured": config_summary.subscription_url_configured,
            "subscription_url_masked": config_summary.subscription_url_masked,
            "subscription_user_agent": config_summary.subscription_user_agent,
            "xray_binary_path": config_summary.xray_binary_path,
            "fail_closed": config_summary.fail_closed,
            "experimental_hysteria2": config_summary.experimental_hysteria2,
            "service_name": config_summary.service_name,
            "undo_available": payload["config_state"]["undo_available"],
            "redacted_diff": payload["config_state"]["redacted_diff"],
        },
        "testing": testing_screen_state_to_dict(testing_screen),
        "route": {
            **route_workbench_state_to_dict(route_workbench),
            "service_name": config_summary.service_name,
            "selected_candidate_label": payload["selection_state"]["selected_candidate_label"],
            "selected_candidate_id": payload["selection_state"]["selected_candidate_id"],
            "actions": ["Add Route", "Delete Route", "Choose Passed Node", "Test Port", "Apply", "Start", "Stop", "Restart", "Validate"],
        },
        "logs_screen": {
            "last_action": latest_action,
            "snapshot_count": payload["artifact_state"]["snapshot_count"],
            "latest_snapshot_id": payload["artifact_state"]["latest_snapshot_id"],
            "latest_snapshot_reason": payload["artifact_state"]["latest_snapshot_reason"],
            "rollback_warning": [
                "Artifact rollback restores local artifacts only.",
                "It does not undo network effects.",
                "It does not restart sidecar.",
                "It does not modify production Xray/XrayR/x-ui.",
            ],
        },
        "dashboard": {
            "repo_status": payload["repo_status"],
            "current_git_commit": payload["current_git_commit"],
            "venv_detected": payload["venv_detected"],
            "config_exists": payload["config_state"]["exists"],
            "config_dirty": payload["config_state"]["dirty"],
            "config_valid": payload["config_state"]["valid"],
            "undo_available": payload["config_state"]["undo_available"],
            "xray_binary_exists": payload["sidecar_state"]["xray_binary_exists"],
            "service_active": payload["sidecar_state"]["service_active"],
            "service_enabled": payload["sidecar_state"]["service_enabled"],
            "socks_tcp_connect": payload["sidecar_state"]["socks_tcp_connect"],
            "last_scholar_validation": payload["artifact_state"]["overall_consistent"],
            "candidate_count": len(payload["selection_state"]["rows"]),
            "passed_count": sum(1 for row in payload["selection_state"]["rows"] if row.get("passed") is True),
            "selected_candidate_label": payload["selection_state"]["selected_candidate_label"],
            "current_sidecar_port": payload["current_sidecar_port"],
            "next_recommended_action": payload["workflow_state"]["next_recommended_action"],
            "last_action": payload["last_action"],
            "snapshot_count": payload["artifact_state"]["snapshot_count"],
            "latest_snapshot_id": payload["artifact_state"]["latest_snapshot_id"],
        },
        "wizard_steps": payload["workflow_state"]["steps"],
        "paths": payload["session"]["paths"],
        "session": payload["session"],
        "artifacts": {
            "candidates_exists": payload["artifact_state"]["candidates_exists"],
            "probe_summary_exists": payload["artifact_state"]["probe_summary_exists"],
            "passed_candidates_exists": payload["artifact_state"]["passed_candidates_exists"],
            "selected_candidate_exists": payload["artifact_state"]["selected_candidate_exists"],
            "pool_plan_exists": payload["pool_state"]["plan_exists"],
            "candidates_hash": payload["artifact_state"]["candidates_hash"],
            "probe_summary_hash": payload["artifact_state"]["probe_summary_hash"],
            "passed_candidates_hash": payload["artifact_state"]["passed_candidates_hash"],
            "artifact_check": payload["artifact_state"]["artifact_check"],
            "warnings": payload["artifact_state"]["warnings"],
            "snapshot_count": payload["artifact_state"]["snapshot_count"],
            "latest_snapshot_id": payload["artifact_state"]["latest_snapshot_id"],
            "latest_snapshot_reason": payload["artifact_state"]["latest_snapshot_reason"],
        },
        "preflight": {
            "config_exists": payload["config_state"]["exists"],
            "config_valid": payload["config_state"]["valid"],
            "config_validation_errors": payload["config_state"]["validation_errors"],
            "enabled_subscription_count": payload["config_state"]["enabled_subscription_count"],
            "xray_binary_exists": payload["sidecar_state"]["xray_binary_exists"],
            "probe_allow_network_probe": payload["config_state"]["probe_allow_network_probe"],
            "xray_binary_path": payload["sidecar_state"]["xray_binary_path"],
            "routing_mode": payload["config_state"]["routing_mode"],
            "routing_fail_closed": payload["config_state"]["routing_fail_closed"],
        },
        "config_editor": {
            "config_path": payload["session"]["paths"]["config"],
            "dirty": payload["config_state"]["dirty"],
            "parsed_ok": payload["config_state"]["valid"],
            "validation_errors": payload["config_state"]["validation_errors"],
            "redacted_preview": payload["config_state"]["redacted_preview"],
            "redacted_diff": payload["config_state"]["redacted_diff"],
            "undo_available": payload["config_state"]["undo_available"],
            "last_saved_at": None,
        },
        "config_form": payload["config_form_state"],
        "selection": {
            "rows": payload["selection_state"]["rows"],
            "selected_candidate_id": payload["selection_state"]["selected_candidate_id"],
            "selected_candidate_label": payload["selection_state"]["selected_candidate_label"],
            "preferred_region_hint": payload["selection_state"]["preferred_region_hint"],
            "selection_method": payload["selection_state"]["selection_method"],
            "selection_reason": payload["selection_state"]["selection_reason"],
            "selected_region_hint": payload["selection_state"]["selected_region_hint"],
            "sensitive_notice": "selected_candidate.json is sensitive and will not be displayed.",
        },
        "commands": {
            "fetch": payload["command_state"]["fetch_command_preview"],
            "probe": payload["command_state"]["probe_command_preview"],
            "artifact_check": payload["command_state"]["artifact_check_command_preview"],
            "select": payload["command_state"]["select_command_preview"],
            "sidecar_stage": payload["command_state"]["sidecar_stage_command_preview"],
            "pool_stage": payload["command_state"]["pool_stage_command_preview"],
            "service_restart": payload["command_state"]["service_restart_command_preview"],
            "service_validate": payload["command_state"]["service_validate_command_preview"],
            "service_snippet": payload["command_state"]["snippet_command_preview"],
        },
        "warnings": payload["warnings"],
        "snippets": payload["snippets"],
        "last_action": payload["last_action"],
        "operation_availability": payload["operation_availability"],
        "control_plane": payload,
    }


def _build_workflow_state(controller: WorkflowController) -> dict[str, object]:
    payload = control_plane_state_to_workflow_dict(controller.state)
    workbench = controller.build_workbench_state()
    workbench["selection_rows"] = _build_selection_rows(payload["selection"]["rows"], workbench)
    payload["workbench"] = workbench
    return payload


def _build_selection_rows(rows: list[dict[str, object]], workbench: dict[str, object]) -> list[dict[str, object]]:
    selected_index = (
        workbench.get("selection", {}).get("selected_candidate_index")
        if isinstance(workbench.get("selection"), dict)
        else None
    )
    rendered: list[dict[str, object]] = []
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        rendered.append(
            {
                **row,
                "selected": position == selected_index,
            }
        )
    return rendered


def _render_candidate_rows(workbench: dict[str, object]) -> list[str]:
    rows = workbench.get("selection_rows", [])
    if not isinstance(rows, list) or not rows:
        return ["candidate_table: no candidates"]
    lines = ["candidate_table:"]
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        marker = ">" if row.get("selected") else " "
        lines.append(
            f"{marker} #{row.get('index')} {row.get('label')} | {row.get('region')} | {row.get('protocol')} | "
            f"passed={row.get('passed')} | stage={row.get('stage')} | home={row.get('home_status')} | query={row.get('query_status')} | "
            f"markers={row.get('failure_marker_count')} | id={row.get('candidate_id')}"
        )
    return lines


def _render_action_history(workbench: dict[str, object]) -> list[str]:
    history = workbench.get("action_history", [])
    if not isinstance(history, list) or not history:
        return ["action_history: none"]
    lines = ["action_history:"]
    for entry in history:
        if not isinstance(entry, dict):
            continue
        lines.append(
            f" - {entry.get('created_at')} | {entry.get('key')} | exit={entry.get('exit_code')} | ok={entry.get('succeeded')} | "
            f"snapshot={entry.get('snapshot_id')} | {entry.get('summary')}"
        )
    return lines


def _render_snapshot_rows(workbench: dict[str, object]) -> list[str]:
    rows = workbench.get("snapshots", [])
    if not isinstance(rows, list) or not rows:
        return ["snapshots: none"]
    lines = ["snapshots:"]
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append(
            f" - {row.get('snapshot_id')} | reason={row.get('reason')} | files={row.get('file_count')} | created_at={row.get('created_at')}"
        )
    return lines


def render_tab_text(tab: str, workflow_state: dict[str, object]) -> str:
    """Render one tab body from the redacted workflow state."""
    if tab == "Home":
        home = workflow_state.get("home", {})
        wizard = workflow_state.get("wizard", {})
        cards = build_home_cards(workflow_state)
        lines = [
            "Scholar Outbound Manager",
            "",
            f"Config: {home.get('config_path')}",
            f"User data: {home.get('user_data_dir')}",
        ]
        for card in cards:
            lines.append("")
            lines.append(card.title)
            for label, value in card.rows:
                lines.append(f"  {label}: {value}")
        lines.extend(["", f"Next: {home.get('next_recommended_action')}"])
        if wizard.get("active"):
            lines.extend(
                [
                    "",
                    "First-run wizard",
                    f"  Target config: {wizard.get('config_path')}",
                    f"  Steps: {', '.join(wizard.get('steps', []))}",
                ]
            )
        return "\n".join(lines)
    if tab == "Settings":
        settings = build_settings_summary(workflow_state)
        lines = [
            "Settings",
            "",
            f"Config path: {settings.config_path}",
            f"User data dir: {settings.user_data_dir}",
            "",
            "Subscription",
            f"  URL: {settings.subscription_url_masked}",
            f"  User-Agent: {settings.subscription_user_agent}",
            "",
            "Runtime",
            f"  Xray: {settings.xray_binary_path}",
            "",
            "Safety",
            f"  fail_closed: {'ON' if settings.fail_closed else 'OFF'}",
            f"  hysteria2 experimental: {'ON' if settings.experimental_hysteria2 else 'OFF'}",
            f"  service name: {settings.service_name}",
            "",
            "Actions",
            "  [Save] [Undo] [Show Diff] [Test Fetch]",
        ]
        diff = workflow_state.get("settings", {}).get("redacted_diff")
        if isinstance(diff, str) and diff:
            lines.extend(["", "Redacted diff", diff])
        return "\n".join(lines)
    if tab == "Testing":
        testing = workflow_state.get("testing", {})
        table = build_testing_table_model(workflow_state)
        summary = testing.get("summary", {}) if isinstance(testing.get("summary"), dict) else {}
        inspector = testing.get("inspector", {}) if isinstance(testing.get("inspector"), dict) else {}
        log_lines = testing.get("log_lines", []) if isinstance(testing.get("log_lines"), list) else []
        lines = [
            "Testing",
            "",
            "Fetch/Test are live network operations.",
            "They write local artifacts under user_data_dir.",
            "They do not modify production Xray/XrayR/x-ui.",
            "",
            "Toolbar: [Fetch Subscription] [Test Nodes] [Retest Failed] [Stop]",
            f"Progress: {testing.get('job_state') or 'idle'} {testing.get('progress_current') or 0}/{testing.get('progress_total') or max(int(summary.get('supported_count') or 0), 0)}",
            "",
            "Summary",
            f"  Subscription: {'configured' if summary.get('subscription_configured') else 'missing'}",
            f"  Fetched: {summary.get('last_fetch_status')}",
            f"  Candidates: {summary.get('candidate_count') or 0}",
            f"  Supported: {summary.get('supported_count') or 0}",
            f"  Experimental-disabled: {summary.get('experimental_disabled_count') or 0}",
            f"  Tested: {summary.get('attempted_count') or 0} / {summary.get('supported_count') or 0}",
            f"  Passed: {summary.get('passed_count') or 0}",
            f"  Failed: {summary.get('failed_count') or 0}",
            f"  Last exit code: {testing.get('last_exit_code') if testing.get('last_exit_code') is not None else '-'}",
            f"  Artifacts stale: {'yes' if testing.get('artifacts_stale') else 'no'}",
            "",
            "Candidate table",
            "  " + " | ".join(table.columns),
        ]
        for row in table.rows[:8]:
            lines.append("  " + " | ".join(row))
        if not table.rows:
            lines.append(f"  {table.empty_message}")
        lines.extend(
            [
                "",
                "Selected candidate",
                f"  Label: {inspector.get('label') or 'none'}",
                f"  Region: {inspector.get('region_hint') or '-'}",
                f"  Protocol: {inspector.get('protocol') or '-'}",
                f"  Candidate ID: {inspector.get('candidate_id') or '-'}",
                f"  Scholar: {inspector.get('scholar_stage') or '-'}",
                f"  Home: {inspector.get('home_status') or '-'}",
                f"  Query: {inspector.get('query_status') or '-'}",
                f"  Latency: {inspector.get('latency_ms') or '-'}",
                f"  Markers: {', '.join(inspector.get('markers') or []) or 'none'}",
                f"  Explanation: {inspector.get('explanation') or '-'}",
            ]
        )
        warning = inspector.get("artifact_warning")
        if isinstance(warning, str) and warning:
            lines.extend(["", warning])
        failure_reason = testing.get("last_failure_reason")
        if isinstance(failure_reason, str) and failure_reason:
            lines.extend(["", f"Last failure: {failure_reason}"])
        if log_lines:
            lines.extend(["", "Recent events"])
            for line in log_lines[:4]:
                lines.append(f"  {line}")
        return "\n".join(lines)
    if tab == "Route":
        route = workflow_state.get("route", {})
        table = build_route_table_model(workflow_state)
        entries = route.get("entries", [])
        selected_index = int(route.get("selected_index", 0) or 0)
        current_entry = entries[selected_index] if isinstance(entries, list) and entries and 0 <= selected_index < len(entries) else {}
        lines = [
            "Route",
            "",
            "Route table",
            "  " + " | ".join(table.columns),
        ]
        for row in table.rows[:8]:
            lines.append("  " + " | ".join(row))
        if not table.rows:
            lines.append(f"  {table.empty_message}")
        lines.extend(
            [
                "",
                "Editor",
                f"  Candidate: {build_route_candidate_display(current_entry if isinstance(current_entry, dict) else {}, limit=60)}",
                f"  Listen host: {current_entry.get('listen_host') if isinstance(current_entry, dict) else '127.0.0.1'}",
                f"  Listen port: {current_entry.get('listen_port') if isinstance(current_entry, dict) else '19080'}",
                f"  Enabled: {'yes' if (current_entry.get('enabled', True) if isinstance(current_entry, dict) else True) else 'no'}",
                f"  Managed service: {route.get('service_name')}",
                "  Actions: [Choose Passed Node] [Test Port] [Apply] [Start] [Stop] [Restart] [Validate]",
                f"  Candidate selector: {'enabled' if route.get('candidate_selector_enabled') else 'disabled'}",
                f"  Apply available: {'yes' if route.get('can_apply') else 'no'}",
                f"  Boundary: {route.get('production_boundary')}",
            ]
        )
        if route.get("candidate_selector_message"):
            lines.extend(["", f"  {route.get('candidate_selector_message')}"])
        if route.get("stale_warning"):
            lines.extend(["", f"  {route.get('stale_warning')}"])
        validation_errors = route.get("validation_errors")
        if isinstance(validation_errors, list) and validation_errors:
            lines.extend(["", "Validation errors"])
            for error in validation_errors:
                lines.append(f"  {error}")
        return "\n".join(lines)
    if tab == "Logs":
        logs = build_logs_summary(workflow_state)
        lines = [
            "Logs",
            "",
            "Action history",
        ]
        for row in logs.action_rows:
            lines.append("  " + " | ".join(row))
        if not logs.action_rows:
            lines.append("  No actions recorded in this session.")
        lines.extend(["", "Snapshots"])
        for row in logs.snapshot_rows:
            lines.append("  " + " | ".join(row))
        lines.extend(["", "Rollback boundary"])
        for warning in logs.rollback_warning:
            lines.append(f"  {warning}")
        last_action = workflow_state.get("logs_screen", {}).get("last_action")
        if isinstance(last_action, dict):
            lines.extend(
                [
                    "",
                    "Latest result",
                    f"  {last_action.get('title') or last_action.get('key')}: {last_action.get('summary')}",
                ]
            )
        return "\n".join(lines)

    workbench = workflow_state.get("workbench", {}) if isinstance(workflow_state.get("workbench"), dict) else {}
    pending_confirmation = bool(workbench.get("pending_action"))
    selected_candidate_id = workflow_state.get("selection", {}).get("selected_candidate_id")
    cursor_candidate_id = _selected_cursor_candidate_id(workbench)
    route_summaries = build_route_summaries(
        workbench.get("selection_rows", []),
        selected_candidate_id=selected_candidate_id,
        cursor_candidate_id=cursor_candidate_id,
    )
    if tab == "Overview":
        summary = build_workflow_summary(workflow_state)
        lines = [
            "Scholar Outbound",
            "",
            "Summary",
            f"  Config:          {_format_health(summary.config_state.value)}",
            f"  Routes:          {summary.route_count} found, {summary.passed_route_count} passed",
            f"  Selected route:  {summary.selected_route_label or 'None selected'}",
            f"  Local service:   {summary.service_state_label}",
            f"  Local SOCKS:     {summary.local_proxy_state_label}",
            "",
            "Next action",
            f"  {summary.next_action_label}",
            "",
            "Reason",
            f"  {summary.next_action_reason}",
            "",
            "Details",
            f"  Last action: {summary.last_action_label}",
            f"  Route state: {_format_health(summary.route_state.value)}",
        ]
        if pending_confirmation:
            lines.extend(["", "Pending confirmation", f"  {workbench.get('pending_action')}"])
        lines.extend(["", _shortcuts_for_tab(tab, pending_confirmation=pending_confirmation)])
        return "\n".join(lines)
    if tab == "Candidates":
        current_route = workflow_state["selection"]["selected_candidate_label"] or "None selected"
        cursor_route = next((route.display_label for route in route_summaries if route.is_cursor), "No cursor route")
        detail = build_route_detail(workbench.get("selected_candidate_detail"))
        lines = [
            "Routes",
            "",
            "Summary",
            f"  Current selected route: {current_route}",
            f"  Cursor route:           {cursor_route}",
            "",
            "Next action / Available actions",
            "  Choose the cursor route for local activation.",
            "",
            "Details",
            "Available routes",
            *_render_route_table(route_summaries),
        ]
        if detail is not None:
            lines.extend(
                [
                    "",
                    "Cursor details",
                    f"  Label:        {detail.display_label}",
                    f"  Region:       {detail.region}",
                    f"  Protocol:     {detail.protocol}",
                    f"  Result:       {'Passed' if detail.passed else 'Needs review'}",
                    f"  Stage:        {detail.stage_label}",
                    f"  Candidate ID: {detail.raw_id}",
                    f"  Home status:  {detail.home_status}",
                    f"  Query status: {detail.query_status}",
                    f"  Markers:      {detail.failure_marker_count}",
                ]
            )
        if pending_confirmation:
            lines.extend(
                [
                    "",
                    "Confirm action",
                    "  Replace selected route?",
                    f"  Current: {current_route}",
                    f"  New:     {cursor_route}",
                ]
            )
        lines.extend(["", _shortcuts_for_tab(tab, pending_confirmation=pending_confirmation)])
        return "\n".join(lines)
    if tab == "Activate":
        steps = build_activate_steps(workflow_state)
        next_action_label, next_action_reason = resolve_next_action(workflow_state)
        stage_impact = build_operation_impact(_find_operation(workflow_state, "sidecar_stage"), action_label="Prepare local runtime files")
        validate_impact = build_operation_impact(_find_operation(workflow_state, "service_validate"), action_label="Validate local SOCKS proxy")
        lines = [
            "Activate selected route",
            "",
            "Summary",
            f"  Selected route: {workflow_state['selection']['selected_candidate_label'] or 'None selected'}",
            f"  Local service:  {build_workflow_summary(workflow_state).service_state_label}",
            "",
            "Next action / Available actions",
            f"  {next_action_label}",
            f"  {next_action_reason}",
            "",
            "Details",
            "Steps",
            *_render_activate_steps(steps),
            "",
            "Impact",
            f"  {stage_impact.summary}: {'Confirmation required' if stage_impact.confirmation_required else 'No confirmation'}",
            f"  {validate_impact.summary}: {'Uses network' if validate_impact.uses_network else 'No network use'}",
            "  This does not modify production Xray/XrayR/x-ui.",
        ]
        if not workflow_state["control_plane"]["pool_state"]["plan_exists"]:
            lines.extend(
                [
                    "",
                    "  No staged runtime plan exists yet.",
                    "  Prepare local runtime files before restarting the local service.",
                ]
            )
        lines.extend(["", _shortcuts_for_tab(tab, pending_confirmation=pending_confirmation)])
        return "\n".join(lines)
    if tab == "Status":
        sidecar = workflow_state["control_plane"]["sidecar_state"]
        selected_route = workflow_state["selection"]["selected_candidate_label"] or "None selected"
        lines = [
            "Status",
            "",
            "Summary",
            f"  Service:       {build_workflow_summary(workflow_state).service_state_label}",
            f"  Enabled:       {_enabled_label(sidecar['service_enabled'])}",
            f"  Local SOCKS:   {build_workflow_summary(workflow_state).local_proxy_state_label}",
            f"  Last check:    {_last_check_label(sidecar['last_validation'])}",
            "",
            "Next action / Available actions",
            "  Run validation" if sidecar["socks_tcp_connect"] != "true" else "  Ready for local use",
            "",
            "Details",
            f"  Selected route: {selected_route}",
            f"  Warning:        {sidecar['warning'] or 'None'}",
            "  Service state is unknown because validation has not been run in this session."
            if sidecar["service_active"] == "unknown"
            else "  Validation state reflects the latest managed local runtime check.",
        ]
        lines.extend(["", _shortcuts_for_tab(tab, pending_confirmation=pending_confirmation)])
        return "\n".join(lines)
    if tab == "Logs":
        artifacts = workflow_state["artifacts"]
        lines = [
            "Logs",
            "",
            "Summary",
            "Recent actions",
            *_render_logs_history(workbench),
            "",
            "Next action / Available actions",
            "  Review command previews and local workflow file status.",
            "",
            "Details",
            "Workflow files",
            f"  candidates.json              {'present' if artifacts['candidates_exists'] else 'missing'}",
            f"  probe_summary.json           {'present' if artifacts['probe_summary_exists'] else 'missing'}",
            f"  passed_candidates.json       {'present' if artifacts['passed_candidates_exists'] else 'missing'}",
            f"  consistency                  {'OK' if artifacts['artifact_check'] and artifacts['artifact_check'].get('overall_consistent') is True else 'Review'}",
            "",
            "Snapshots",
            *_render_logs_snapshots(workbench),
            "",
            "Commands",
            f"  fetch:    {workflow_state['commands']['fetch']}",
            f"  probe:    {workflow_state['commands']['probe']}",
            f"  validate: {workflow_state['commands']['service_validate']}",
            "",
            "Developer details",
            f"  candidates_hash:       {artifacts['candidates_hash']}",
            f"  probe_summary_hash:    {artifacts['probe_summary_hash']}",
            f"  passed_candidates_hash:{artifacts['passed_candidates_hash']}",
            f"  latest_snapshot_id:    {artifacts['latest_snapshot_id']}",
        ]
        lines.extend(["", _shortcuts_for_tab(tab, pending_confirmation=pending_confirmation)])
        return "\n".join(lines)
    if tab == "Settings":
        groups = build_settings_groups(workflow_state["config_form"])
        lines = [
            "Settings",
            "",
            "Summary",
            f"  Config valid: {workflow_state['preflight']['config_valid']}",
            f"  Undo available: {workflow_state['config_editor']['undo_available']}",
            "",
            "Next action / Available actions",
            "  Edit one allowlisted setting and save it through the structured form.",
            "",
            "Details",
            *_render_settings_groups(groups),
        ]
        selected_field = workbench.get("selected_config_field")
        if isinstance(selected_field, dict):
            lines.extend(
                [
                    "",
                    "Selected field",
                    f"  {selected_field.get('title') or selected_field.get('key')}: {selected_field.get('current_value')}",
                ]
            )
        diff = workflow_state["config_form"]["redacted_diff"] or workflow_state["config_editor"]["redacted_diff"]
        if diff:
            lines.extend(["", "Redacted diff", f"  {diff}"])
        lines.extend(["", _shortcuts_for_tab(tab, pending_confirmation=pending_confirmation)])
        return "\n".join(lines)
    return "\n".join(
        [
            "Configured workflow tabs:",
            ", ".join(workflow_state["tabs"]),
        ]
    )


def save_selection_from_index(
    *,
    candidates_path: str | Path,
    selected_index: int,
    output_path: str | Path,
) -> dict[str, object]:
    """Save one selected-candidate artifact from the currently highlighted row."""
    payload = load_candidate_payload(candidates_path)
    record = select_candidate_by_index(payload, selected_index)
    artifact = build_selected_candidate_artifact(record, selection_method="index")
    write_selected_candidate_artifact(output_path, artifact)
    return artifact


def main(argv: Sequence[str] | None = None) -> int:
    """Run the optional Textual TUI entry point."""
    args = build_parser().parse_args(argv)
    try:
        from textual.app import App
        from textual.app import ComposeResult
        from textual.containers import Horizontal
        from textual.containers import Vertical
        from textual.widgets import Button
        from textual.widgets import DataTable
        from textual.widgets import Footer
        from textual.widgets import Header
        from textual.widgets import Input
        from textual.widgets import ProgressBar
        from textual.widgets import RichLog
        from textual.widgets import Select
        from textual.widgets import Static
        from textual.widgets import Switch
    except ModuleNotFoundError as exc:
        if exc.name != "textual":
            raise
        print('Textual TUI is not installed. Install with:\npip install "ScholarOutboundManager[tui]"')
        return 1

    resolved_paths = resolve_user_data_paths(args.config)
    controller = WorkflowController(
        loader_kwargs={
            "config_path": args.config,
            "candidates_path": str(resolved_paths.candidates if args.candidates is None else args.candidates),
            "probe_summary_path": str(resolved_paths.probe_summary if args.probe_summary is None else args.probe_summary),
            "passed_candidates_path": str(resolved_paths.passed_candidates if args.passed_candidates is None else args.passed_candidates),
            "selected_candidate_path": str(resolved_paths.selected_candidate if args.selected_candidate is None else args.selected_candidate),
            "pool_plan_path": str(resolved_paths.pool_plan if args.pool_plan is None else args.pool_plan),
            "session_path": str(resolved_paths.session if args.session is None else args.session),
            "action_journal_path": str(resolved_paths.action_journal),
            "snapshot_root": str(resolved_paths.snapshot_root),
            "output_path": str(resolved_paths.selected_candidate if args.output is None else args.output),
            "strategy": args.strategy,
            "geo_cache_path": str(resolved_paths.geo_cache if args.geo_cache is None else args.geo_cache),
            "host_geo_path": str(resolved_paths.host_geo if args.host_geo is None else args.host_geo),
            "prefer_geo": args.prefer_geo,
            "preferred_region_hint": args.preferred_region_hint,
        },
    )
    workflow_state = controller.workflow_state
    write_session_state(
        str(resolved_paths.session if args.session is None else args.session),
        build_session_state(
            updated_at=workflow_state["session"]["updated_at"],
            workspace=workflow_state["session"]["workspace"],
            last_step=None,
            paths=workflow_state["paths"],
            last_results=workflow_state["session"]["last_results"],
        ),
    )

    class ScholarOutboundWorkflowApp(App[None]):
        """Task-oriented config-centered TUI."""

        BINDINGS = list(TUI_KEY_BINDINGS)
        DEFAULT_CSS = """
        #tui-root { height: 1fr; }
        #nav-rail { width: 24; min-width: 24; }
        #main-column { width: 1fr; height: 1fr; }
        #page-testing { height: 1fr; }
        #testing-runtime-header { height: auto; }
        #testing-summary { height: auto; }
        #testing-table { height: 1fr; width: 1fr; }
        #testing-log { height: 8; }
        """
        current_page = "Home"
        testing_selected_index: int | None = None
        route_selected_index: int = 0
        route_port_results: dict[str, object] = {}
        route_form_syncing = False
        pending_action_handler: Callable[[], str] | None = None
        testing_thread: threading.Thread | None = None
        detail_open: bool = False
        last_notice_key: str | None = None
        app_state: AppState | None = None
        effect_runner: EffectRunner | None = None
        rendering = False

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="tui-root"):
                with Vertical(id="nav-rail"):
                    yield Static("Scholar Outbound Manager", id="nav-title")
                    for page in MAIN_TABS:
                        yield Button(page, id=f"nav-{_textual_safe_id(page)}")
                with Vertical(id="main-column"):
                    yield from self._build_home_page()
                    yield from self._build_settings_page()
                    yield from self._build_testing_page()
                    yield from self._build_route_page()
                    yield from self._build_logs_page()
            with Vertical(id="confirmation-panel"):
                yield Static("Confirm Action", id="confirmation-title")
                yield Static("", id="confirmation-body")
                with Horizontal(id="confirmation-actions"):
                    yield Button("Confirm", id="pending-confirm")
                    yield Button("Cancel", id="pending-cancel")
            with Vertical(id="detail-panel"):
                yield Static("Details", id="detail-title")
                yield Static("", id="detail-body")
                yield Button("Close", id="detail-close")
            with Vertical(id="error-panel"):
                yield Static("TUI refresh failed", id="error-title")
                yield Static("", id="error-body")
            yield Static("", id="shortcut-bar")
            yield Footer()

        def on_mount(self) -> None:
            self._init_tables()
            self.app_state = build_app_state(
                controller=controller,
                config_path=controller._paths()["config"],
                active_page="home",
                testing_selected_index=self.testing_selected_index,
                route_selected_index=self.route_selected_index,
                route_port_results=self.route_port_results,
            )
            self.effect_runner = self._build_effect_runner()
            self._set_page("Home")
            self._close_detail_panel()
            self._safe_refresh_ui("startup")

        def _build_home_page(self):
            with Vertical(id="page-home"):
                yield Static("", id="home-summary")
                with Horizontal(id="home-actions"):
                    yield Button("Open Settings", id="home-open-settings")
                    yield Button("Open Testing", id="home-open-testing")
                    yield Button("Create Snapshot", id="home-snapshot")

        def _build_settings_page(self):
            with Vertical(id="page-settings"):
                yield Static("Settings", classes="page-title")
                yield Static("Config path", classes="field-label")
                yield Input("", id="settings-config-path", disabled=True)
                yield Static("User data dir", classes="field-label")
                yield Input("", id="settings-user-data-dir")
                yield Static("Subscription URL", classes="field-label")
                yield Input("", id="settings-subscription-url", password=True)
                yield Static("User-Agent", classes="field-label")
                yield Input("", id="settings-user-agent")
                yield Static("Xray binary path", classes="field-label")
                yield Input("", id="settings-xray-path")
                yield Static("Managed service name", classes="field-label")
                yield Input("", id="settings-service-name")
                yield Static("Fail closed", classes="field-label")
                yield Switch(value=True, id="settings-fail-closed")
                yield Static("Experimental Hysteria2", classes="field-label")
                yield Switch(value=False, id="settings-hysteria2")
                with Horizontal(id="settings-actions"):
                    yield Button("Save", id="settings-save")
                    yield Button("Undo", id="settings-undo")
                    yield Button("Show Diff", id="settings-diff")
                    yield Button("Test Fetch", id="settings-test-fetch")
                yield Static("", id="settings-diff-panel")

        def _build_testing_page(self):
            with Vertical(id="page-testing"):
                yield Static(
                    "Fetch/Test are live network operations.\n"
                    "They write local artifacts under user_data_dir.\n"
                    "They do not modify production Xray/XrayR/x-ui.",
                    id="testing-banner",
                )
                yield Static("", id="testing-runtime-header")
                with Horizontal(id="testing-actions"):
                    yield Button("Fetch Subscription", id="testing-fetch")
                    yield Button("Test Nodes", id="testing-probe")
                    yield Button("Retest Failed", id="testing-retest")
                    yield Button("Stop", id="testing-stop", disabled=True)
                yield ProgressBar(total=100, id="testing-progress")
                yield Static("", id="testing-summary")
                yield DataTable(id="testing-table")
                yield RichLog(id="testing-log", wrap=True, markup=False)

        def _build_route_page(self):
            with Vertical(id="page-route"):
                with Horizontal(id="route-actions"):
                    yield Button("Add Route", id="route-add")
                    yield Button("Delete Route", id="route-delete")
                    yield Button("Choose Passed Node", id="route-select")
                    yield Button("Test Port", id="route-test-port")
                    yield Button("Apply", id="route-apply")
                    yield Button("Start", id="route-start")
                    yield Button("Stop", id="route-stop")
                    yield Button("Restart", id="route-restart")
                    yield Button("Validate", id="route-validate")
                yield DataTable(id="route-table")
                yield Static("Route name", classes="field-label")
                yield Input("", id="route-name")
                yield Static("Candidate", classes="field-label")
                yield Select([], prompt="Choose passed node", id="route-candidate-select")
                yield Static("Listen host", classes="field-label")
                yield Input("", id="route-listen-host")
                yield Static("Listen port", classes="field-label")
                yield Input("", id="route-listen-port")
                yield Static("Enabled", classes="field-label")
                yield Switch(value=True, id="route-enabled")
                yield Static("", id="route-port-result")
                yield Static("", id="route-validation-errors")
                yield Static("", id="route-boundary")

        def _build_logs_page(self):
            with Vertical(id="page-logs"):
                with Horizontal(id="logs-actions"):
                    yield Button("Artifact Check", id="logs-artifact-check")
                    yield Button("Create Snapshot", id="logs-snapshot")
                    yield Button("Rollback", id="logs-rollback")
                yield DataTable(id="logs-action-table")
                yield DataTable(id="logs-snapshot-table")
                yield RichLog(id="logs-rich-log", wrap=True, markup=False)

        def _init_tables(self) -> None:
            testing_table = self.query_one("#testing-table", DataTable)
            testing_table.add_columns("status", "#", "region", "label", "protocol", "latency", "home", "query", "stage", "markers")
            route_table = self.query_one("#route-table", DataTable)
            route_table.add_columns("enabled", "name", "candidate", "region", "protocol", "host", "port", "port status", "validation")
            action_table = self.query_one("#logs-action-table", DataTable)
            action_table.add_columns("action", "status", "summary")
            snapshot_table = self.query_one("#logs-snapshot-table", DataTable)
            snapshot_table.add_columns("snapshot", "reason")

        def _set_page(self, page: str) -> None:
            self.current_page = page
            controller.selection.active_tab = page
            if self.app_state is not None:
                self.app_state = replace(
                    self.app_state,
                    nav=NavState(active_page=page.lower()),
                    status_bar=StatusBarState(
                        message=self.app_state.status_bar.message,
                        level=self.app_state.status_bar.level,
                        keys=tuple(_key_hints_for_page(page.lower())),
                    ),
                )
            for candidate in MAIN_TABS:
                page_widget = self.query_one(f"#page-{_textual_safe_id(candidate)}", Vertical)
                page_widget.display = candidate == page
                button = self.query_one(f"#nav-{_textual_safe_id(candidate)}", Button)
                button.variant = "primary" if candidate == page else "default"
            self.query_one("#shortcut-bar", Static).update(
                _shortcuts_for_tab(page, pending_confirmation=bool(controller.pending_action))
            )

        def _refresh_ui_impl(self) -> None:
            self.render_state()

        def render_state(self) -> None:
            self._clear_safe_error_state()
            if self.app_state is None:
                return
            self.rendering = True
            try:
                state = self.app_state
                self.query_one("#home-summary", Static).update(self._render_home_summary(state))
                self._render_settings_page_state(state)
                self._render_testing_page_state(state)
                self._render_route_page_state(state)
                self._render_logs_page_state(state)
                self._refresh_confirmation_panel()
                self.query_one("#shortcut-bar", Static).update(
                    _shortcuts_for_tab(self.current_page, pending_confirmation=bool(controller.pending_action))
                )
            finally:
                self.rendering = False

        def _render_home_summary(self, state: AppState) -> str:
            settings = state.settings
            summary = state.testing.summary
            selected_labels = [entry.candidate_label for entry in state.route.entries if entry.enabled and entry.candidate_label]
            active_ports = [entry.listen_port for entry in state.route.entries if entry.enabled]
            return "\n".join(
                [
                    "Scholar Outbound Manager",
                    "",
                    f"Config: {settings.get('config_path')}",
                    f"User data: {settings.get('user_data_dir')}",
                    "",
                    "Subscription",
                    f"  Configured: {'yes' if settings.get('subscription_url_configured') else 'no'}",
                    f"  Last fetch: {summary.last_fetch_status or 'unknown'}",
                    f"  Candidates: {summary.candidate_count}",
                    f"  Supported: {summary.supported_count}",
                    "",
                    "Testing",
                    f"  Tested: {summary.attempted_count}",
                    f"  Passed: {summary.passed_count}",
                    f"  Failed: {summary.failed_count}",
                    f"  Query blocked: {summary.query_blocked_count}",
                    "",
                    "Route",
                    f"  Routes enabled: {sum(1 for entry in state.route.entries if entry.enabled)} / {len(state.route.entries)}",
                    f"  Ports: {', '.join(str(port) for port in active_ports) if active_ports else 'none'}",
                    f"  Selected: {', '.join(selected_labels) if selected_labels else 'none'}",
                    "",
                    "Sidecar",
                    f"  Service: {settings.get('service_active') or 'unknown'}",
                    f"  Enabled: {settings.get('service_enabled') or 'unknown'}",
                    f"  SOCKS: {settings.get('socks_status') or 'unknown'}",
                    "",
                    f"Next: {settings.get('next_recommended_action') or 'Review Testing and Route state.'}",
                ]
            )

        def _render_settings_page_state(self, state: AppState) -> None:
            settings = state.settings
            self.query_one("#settings-diff-panel", Static).update(str(settings.get("redacted_diff") or "No pending redacted diff."))
            self.query_one("#settings-config-path", Input).value = str(settings.get("config_path") or "")
            self.query_one("#settings-user-data-dir", Input).value = str(settings.get("user_data_dir") or "")
            self.query_one("#settings-subscription-url", Input).value = str(settings.get("subscription_url_masked") or "")
            self.query_one("#settings-user-agent", Input).value = str(settings.get("subscription_user_agent") or "")
            self.query_one("#settings-xray-path", Input).value = str(settings.get("xray_binary_path") or "")
            self.query_one("#settings-service-name", Input).value = str(settings.get("service_name") or "")
            self.query_one("#settings-fail-closed", Switch).value = bool(settings.get("fail_closed"))
            self.query_one("#settings-hysteria2", Switch).value = bool(settings.get("experimental_hysteria2"))

        def _render_testing_page_state(self, state: AppState) -> None:
            self.testing_selected_index = state.testing.selected_index
            testing_model = build_testing_table_model(self._build_app_render_model(state))
            self.query_one("#testing-runtime-header", Static).update(
                "\n".join(
                    [
                        "Testing nodes",
                        f"Phase: {state.testing.runtime.phase}",
                        f"Progress: {state.testing.runtime.progress_mode.replace('_', ' ')}",
                        f"Parallel workers: {state.testing.runtime.parallel_workers or state.settings.get('probe_concurrency') or 'unknown'}",
                        f"Current candidate: {state.testing.runtime.current_candidate_label or '-'}",
                        f"Status: {state.testing.job.message}",
                    ]
                )
            )
            progress = self.query_one("#testing-progress", ProgressBar)
            progress.update(
                total=max(state.testing.runtime.total, 1),
                progress=state.testing.runtime.current,
            )
            self.query_one("#testing-summary", Static).update("\n".join(_render_testing_summary_lines({"summary": asdict(state.testing.summary)})))
            self.query_one("#testing-banner", Static).update(_testing_banner_text(state.testing.stale_warning))
            testing_table = self.query_one("#testing-table", DataTable)
            testing_table.clear()
            for row in testing_model.rows:
                testing_table.add_row(*row)
            testing_log = self.query_one("#testing-log", RichLog)
            testing_log.clear()
            for line in state.testing.recent_events:
                testing_log.write(line)
            self.query_one("#testing-fetch", Button).disabled = not bool(state.settings.get("subscription_url_configured"))
            self.query_one("#testing-probe", Button).disabled = state.testing.summary.candidate_count <= 0
            self.query_one("#testing-retest", Button).disabled = state.testing.summary.failed_count <= 0
            self.query_one("#testing-stop", Button).disabled = not state.testing.job.can_cancel

        def _render_route_page_state(self, state: AppState) -> None:
            self.route_selected_index = state.route.selected_index
            route_model = build_route_table_model(self._build_app_render_model(state))
            route_table = self.query_one("#route-table", DataTable)
            route_table.clear()
            for row in route_model.rows:
                route_table.add_row(*row)
            route_entry = state.route.entries[state.route.selected_index] if state.route.entries else None
            self.route_form_syncing = True
            try:
                self.query_one("#route-name", Input).value = route_entry.name if route_entry is not None else "Scholar"
                self.query_one("#route-listen-host", Input).value = route_entry.listen_host if route_entry is not None else "127.0.0.1"
                self.query_one("#route-listen-port", Input).value = str(route_entry.listen_port if route_entry is not None else 19080)
                self.query_one("#route-enabled", Switch).value = True if route_entry is None else route_entry.enabled
                route_select = self.query_one("#route-candidate-select", Select)
                options = [(f"{option.label} · {option.region_hint or '-'} · {option.protocol} · {option.stage}", option.candidate_id) for option in state.route.candidate_options]
                route_select.set_options(options)
                if route_entry is None or route_entry.candidate_id is None:
                    route_select.clear()
                elif route_select.value != route_entry.candidate_id:
                    route_select.value = route_entry.candidate_id
                route_select.disabled = not bool(state.route.candidate_options) or state.route.stale_warning is not None
            finally:
                self.route_form_syncing = False
            self.query_one("#route-select", Button).disabled = self.query_one("#route-candidate-select", Select).disabled
            self.query_one("#route-apply", Button).disabled = not state.route.apply_available
            port_result = None if route_entry is None else state.route.port_checks.get(route_entry.route_id)
            self.query_one("#route-port-result", Static).update("" if port_result is None else f"Port check: {port_result.status} - {port_result.message}")
            self.query_one("#route-validation-errors", Static).update("\n".join(state.route.validation_errors) if state.route.validation_errors else "No route validation errors.")
            self.query_one("#route-boundary", Static).update("Only ScholarOutboundManager sidecar is managed. Production Xray/XrayR/x-ui is never modified.")

        def _render_logs_page_state(self, state: AppState) -> None:
            action_table = self.query_one("#logs-action-table", DataTable)
            action_table.clear()
            for row in state.logs.get("action_rows", []):
                action_table.add_row(*row)
            snapshot_table = self.query_one("#logs-snapshot-table", DataTable)
            snapshot_table.clear()
            for row in state.logs.get("snapshot_rows", []):
                snapshot_table.add_row(*row)
            rich_log = self.query_one("#logs-rich-log", RichLog)
            rich_log.clear()
            for line in state.logs.get("rollback_warning", []):
                rich_log.write(line)

        def _build_app_render_model(self, state: AppState) -> dict[str, object]:
            return {
                "settings": dict(state.settings),
                "testing": {
                    "summary": asdict(state.testing.summary),
                    "rows": [asdict(row) for row in state.testing.rows],
                    "runtime": asdict(state.testing.runtime),
                    "job": asdict(state.testing.job),
                    "recent_events": list(state.testing.recent_events),
                },
                "route": {
                    "entries": [asdict(entry) for entry in state.route.entries],
                    "candidate_selector_enabled": bool(state.route.candidate_options) and state.route.stale_warning is None,
                    "can_apply": state.route.apply_available,
                    "validation_errors": list(state.route.validation_errors),
                    "production_boundary": "Only ScholarOutboundManager sidecar is managed. Production Xray/XrayR/x-ui is never modified.",
                },
                "logs_screen": dict(state.logs),
            }

        def _safe_refresh_ui(self, reason: str = "refresh") -> None:
            succeeded, safe_message = _run_safe_refresh(
                reason=reason,
                refresh_func=self._refresh_ui_impl,
                render_error=self._render_safe_error_state,
                journal_path=controller._action_journal_path,  # type: ignore[attr-defined]
            )
            if not succeeded and safe_message:
                self.notify(f"TUI refresh failed: {safe_message}", severity="error")

        def _clear_safe_error_state(self) -> None:
            error_panel = self.query_one("#error-panel", Vertical)
            error_panel.display = False
            self.query_one("#error-title", Static).update("TUI refresh failed")
            self.query_one("#error-body", Static).update("")

        def _render_safe_error_state(self, title: str, message: str) -> None:
            error_panel = self.query_one("#error-panel", Vertical)
            error_panel.display = True
            self.query_one("#error-title", Static).update(title)
            self.query_one("#error-body", Static).update(message)

        def _notify_user(self, message: str, *, key: str | None = None, severity: str = "information") -> None:
            notice_key = key or message
            if self.last_notice_key == notice_key:
                return
            self.last_notice_key = notice_key
            self.notify(message, severity=severity)

        def _open_detail_panel(self, title: str, body: str) -> None:
            panel = self.query_one("#detail-panel", Vertical)
            panel.display = True
            self.query_one("#detail-title", Static).update(title)
            self.query_one("#detail-body", Static).update(body)
            self.detail_open = True

        def _close_detail_panel(self) -> None:
            panel = self.query_one("#detail-panel", Vertical)
            panel.display = False
            self.query_one("#detail-title", Static).update("Details")
            self.query_one("#detail-body", Static).update("")
            self.detail_open = False

        def _build_current_detail(self) -> tuple[str, str]:
            if self.app_state is None:
                return "Details", "No additional detail is available for this page."
            if self.current_page == "Testing":
                return "Testing detail", build_testing_detail_body(self._build_app_render_model(self.app_state).get("testing", {}))
            if self.current_page == "Route":
                return "Route detail", build_route_detail_body(self._build_app_render_model(self.app_state).get("route", {}))
            if self.current_page == "Home":
                return "Home detail", (
                    f"Next action: {self.app_state.settings.get('next_recommended_action') or 'none'}\n"
                    f"Latest action: {(self.app_state.logs.get('last_action') or {}).get('summary') if isinstance(self.app_state.logs.get('last_action'), dict) else 'none'}"
                )
            return "Details", "No additional detail is available for this page."

        def dispatch_event(self, event) -> None:
            if self.app_state is None:
                return
            try:
                new_state, effects = reduce_app_state(self.app_state, event)
                self.app_state = new_state
                self._safe_refresh_ui("state dispatch")
                runner = self.effect_runner
                backend_events = [] if runner is None else runner.run_many(effects)
                for backend_event in backend_events:
                    self.dispatch_event(backend_event)
            except Exception as exc:
                self._contain_runtime_exception("TUI event dispatch failed", exc)

        def _build_effect_runner(self) -> EffectRunner:
            return EffectRunner(
                CallbackBackend(
                    create_snapshot=lambda reason: controller.create_snapshot(reason),
                    start_fetch=lambda: self._start_testing_operation("fetch", "fetching"),
                    start_probe=lambda: self._start_testing_operation("probe", "probing"),
                    save_route_draft=lambda entries: save_route_draft_state(
                        user_data_paths=resolve_user_data_paths(controller._paths()["config"]),
                        entries=list(entries),
                    ),
                    run_port_check=lambda route_id: self._run_port_check_for_route(route_id),
                    run_action=lambda action_key: controller.handle_operation(action_key),
                    reload_app_state=self._reload_app_state,
                )
            )

        def _reload_app_state(self) -> AppState:
            controller.reload()
            return build_app_state(
                controller=controller,
                config_path=controller._paths()["config"],
                active_page=self.current_page.lower(),
                testing_selected_index=self.testing_selected_index,
                route_selected_index=self.route_selected_index,
                route_port_results=self.route_port_results,
            )

        def _contain_runtime_exception(self, title: str, exc: Exception) -> None:
            safe_message = redact_exception_message(str(exc))
            if self.app_state is not None:
                self.app_state = replace(
                    self.app_state,
                    modal=ModalState(kind="error", title=title, body_lines=(safe_message,), action_key=None),
                    status_bar=StatusBarState(
                        message=safe_message,
                        level="error",
                        keys=self.app_state.status_bar.keys,
                    ),
                )
            self._render_safe_error_state(title, _build_refresh_error_body(safe_message))

        def _refresh_confirmation_panel(self) -> None:
            panel = self.query_one("#confirmation-panel", Vertical)
            pending = controller.pending_action
            panel.display = pending is not None
            if pending is None:
                self.query_one("#confirmation-body", Static).update("")
                return
            self.query_one("#confirmation-title", Static).update(f"Confirm: {pending.title}")
            self.query_one("#confirmation-body", Static).update(_build_confirmation_body(pending))

        def _run_tui_action(self, description: str, func: Callable[[], str | None], *, notify: bool = True) -> None:
            message, succeeded = _run_safe_tui_action(controller, description, func)
            self._safe_refresh_ui("after action")
            if notify and message:
                self._notify_user(message, key=f"{description}:{message}")
            elif notify and succeeded and controller.action_state.status_message:
                self._notify_user(str(controller.action_state.status_message), key=f"{description}:{controller.action_state.status_message}")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            button_id = event.button.id or ""
            if button_id.startswith("nav-"):
                page = {
                    "nav-home": "Home",
                    "nav-settings": "Settings",
                    "nav-testing": "Testing",
                    "nav-route": "Route",
                    "nav-logs": "Logs",
                }.get(button_id, "Home")
                self.dispatch_event(Navigate(page=page.lower()))
                self._set_page(page)
                return
            button_actions: dict[str, Callable[[], None]] = {
                "home-open-settings": self.action_open_settings,
                "home-open-testing": self.action_open_testing,
                "home-snapshot": self.action_create_snapshot,
                "settings-save": self.action_save_draft,
                "settings-undo": self.action_undo_save,
                "settings-diff": self.action_show_config_diff,
                "settings-test-fetch": self.action_run_fetch,
                "testing-fetch": self.action_run_fetch,
                "testing-probe": self.action_run_probe,
                "testing-retest": self.action_run_retest_failed,
                "testing-stop": self.action_stop_testing_job,
                "route-add": self.action_route_add,
                "route-delete": self.action_route_delete,
                "route-select": self.action_run_select,
                "route-test-port": self.action_route_test_port,
                "route-apply": self.action_run_stage_sidecar,
                "route-start": self.action_route_start_placeholder,
                "route-stop": self.action_route_stop_placeholder,
                "route-restart": self.action_run_restart_sidecar,
                "route-validate": self.action_run_validate_sidecar,
                "logs-artifact-check": self.action_run_artifact_check,
                "logs-snapshot": self.action_create_snapshot,
                "logs-rollback": self.action_rollback_latest_snapshot,
                "pending-confirm": self.action_confirm_selected,
                "pending-cancel": self.action_cancel_pending,
                "detail-close": self.action_close_detail,
            }
            action = button_actions.get(button_id)
            if action is not None:
                action()

        def on_input_changed(self, event: Input.Changed) -> None:
            if self.current_page != "Route" or self.route_form_syncing or self.rendering:
                return
            if event.input.id == "route-name":
                self._update_route_field("name", event.value)
            elif event.input.id == "route-listen-host":
                self._update_route_field("listen_host", event.value)
            elif event.input.id == "route-listen-port":
                try:
                    self._update_route_field("listen_port", int(event.value))
                except ValueError:
                    self._update_route_field("listen_port", 0)
            self._safe_refresh_ui("route field edit")

        def on_switch_changed(self, event: Switch.Changed) -> None:
            if self.current_page != "Route" or self.route_form_syncing or self.rendering:
                return
            if event.switch.id == "route-enabled":
                self._update_route_field("enabled", bool(event.value))
                self._safe_refresh_ui("route toggle")

        def on_select_changed(self, event) -> None:
            if self.current_page != "Route" or self.rendering:
                return
            if getattr(event.select, "id", "") != "route-candidate-select":
                return
            value = event.value
            entries = list(self.app_state.route.entries) if self.app_state is not None else []
            current_entry = entries[self.route_selected_index] if entries and 0 <= self.route_selected_index < len(entries) else None
            current_candidate_id = None
            if isinstance(current_entry, dict):
                current_candidate_id = current_entry.get("candidate_id")
            elif current_entry is not None:
                current_candidate_id = current_entry.candidate_id
            if _should_ignore_route_select_change(
                route_form_syncing=self.route_form_syncing,
                event_value=value,
                current_candidate_id=current_candidate_id if isinstance(current_candidate_id, str) else None,
            ):
                return
            route_id = ""
            if isinstance(current_entry, dict):
                route_id = str(current_entry.get("route_id") or "")
            elif current_entry is not None:
                route_id = current_entry.route_id
            self.dispatch_event(RouteCandidateChosen(route_id=route_id, candidate_id=value))

        def action_open_home(self) -> None:
            self.dispatch_event(Navigate(page="home"))
            self._set_page("Home")

        def action_open_settings(self) -> None:
            self.dispatch_event(Navigate(page="settings"))
            self._set_page("Settings")

        def action_open_testing(self) -> None:
            self.dispatch_event(Navigate(page="testing"))
            self._set_page("Testing")

        def action_open_route(self) -> None:
            self.dispatch_event(Navigate(page="route"))
            self._set_page("Route")

        def action_open_logs(self) -> None:
            self.dispatch_event(Navigate(page="logs"))
            self._set_page("Logs")

        def action_reload_state(self) -> None:
            self.dispatch_event(RefreshRequested())

        def action_save_draft(self) -> None:
            self._run_tui_action("Save config draft", lambda: controller.save_config().message)

        def action_undo_save(self) -> None:
            self._run_tui_action("Undo config save", controller.undo_config_save)

        def action_show_config_diff(self) -> None:
            self._run_tui_action(
                "Show redacted config diff",
                lambda: str((self.app_state.settings.get("redacted_diff") if self.app_state is not None else "") or "No pending redacted config diff is available."),
            )

        def action_cursor_down(self) -> None:
            if self.current_page == "Testing":
                self.dispatch_event(TestingMoveCursor(delta=1))
                return
            if self.current_page == "Route":
                if self.app_state is not None and self.app_state.route.entries:
                    next_index = min(len(self.app_state.route.entries) - 1, self.app_state.route.selected_index + 1)
                    self.dispatch_event(RouteSelectRow(index=next_index))
                return
            self._run_tui_action("Move selection", lambda: (controller.move_candidate(1), "Selection moved down.")[1])

        def action_cursor_up(self) -> None:
            if self.current_page == "Testing":
                self.dispatch_event(TestingMoveCursor(delta=-1))
                return
            if self.current_page == "Route":
                if self.app_state is not None:
                    next_index = max(0, self.app_state.route.selected_index - 1)
                    self.dispatch_event(RouteSelectRow(index=next_index))
                return
            self._run_tui_action("Move selection", lambda: (controller.move_candidate(-1), "Selection moved up.")[1])

        def action_confirm_selected(self) -> None:
            if controller.pending_action is not None:
                self._run_tui_action(
                    "Confirm selected action",
                    self._confirm_pending_action,
                )
                return
            if self.current_page == "Testing":
                self.dispatch_event(TestingInspectSelected())
            elif self.current_page == "Route":
                self.dispatch_event(RouteInspectSelected())
            else:
                self.action_open_detail()

        def action_open_detail(self) -> None:
            title, body = self._build_current_detail()
            self._open_detail_panel(title, body)

        def action_close_detail(self) -> None:
            self._close_detail_panel()

        def action_cancel_pending(self) -> None:
            self._run_tui_action(
                "Cancel pending action",
                lambda: (setattr(self, "pending_action_handler", None), controller.clear_pending_action(), "Pending action cleared.")[2],
                notify=False,
            )

        def action_run_fetch(self) -> None:
            self.dispatch_event(TestingFetchRequested())

        def action_run_probe(self) -> None:
            self.dispatch_event(TestingProbeRequested())

        def action_run_retest_failed(self) -> None:
            self._run_tui_action(
                "Retest failed candidates",
                lambda: "Retest Failed is not implemented for the current backend yet.",
            )

        def action_stop_testing_job(self) -> None:
            if self.app_state is None or self.app_state.testing.job.status not in {"fetching", "probing", "finalizing"}:
                self._run_tui_action("Stop testing job", lambda: "No running fetch/probe worker is attached in this phase.", notify=False)
                return
            self.dispatch_event(TestingStopRequested())

        def action_run_artifact_check(self) -> None:
            self._run_tui_action("Run artifact check", lambda: controller.handle_operation("artifact_check"))

        def action_run_select(self) -> None:
            self._run_tui_action("Choose passed node", self._choose_selected_route_candidate)

        def action_run_stage_sidecar(self) -> None:
            self._run_tui_action(
                "Apply route workbench",
                lambda: self._request_confirmation("sidecar_stage", handler=self._apply_route_draft),
            )

        def action_run_restart_sidecar(self) -> None:
            self._run_tui_action("Restart sidecar", lambda: self._request_confirmation("service_restart"))

        def action_run_validate_sidecar(self) -> None:
            self._run_tui_action("Validate sidecar", lambda: controller.handle_operation("service_validate"))

        def action_route_start_placeholder(self) -> None:
            self._run_tui_action(
                "Start sidecar",
                lambda: self._request_confirmation(
                    "service_start",
                    handler=lambda: (
                        controller.clear_pending_action(),
                        "Managed start remains explicit and out of scope in this phase; no systemd start was executed.",
                    )[1],
                ),
            )

        def action_route_stop_placeholder(self) -> None:
            self._run_tui_action(
                "Stop sidecar",
                lambda: self._request_confirmation(
                    "service_stop",
                    handler=lambda: (
                        controller.clear_pending_action(),
                        "Managed stop remains explicit and out of scope in this phase; no systemd stop was executed.",
                    )[1],
                ),
            )

        def action_route_add(self) -> None:
            self._run_tui_action("Add route", self._add_route_entry)

        def action_route_delete(self) -> None:
            self._run_tui_action("Delete route", self._delete_route_entry)

        def action_route_test_port(self) -> None:
            self._run_tui_action("Test route port", self._test_selected_route_port)

        def action_create_snapshot(self) -> None:
            self._run_tui_action("Create snapshot", controller.create_snapshot_message)

        def action_contextual_x(self) -> None:
            if self.current_page == "Testing":
                self.action_stop_testing_job()
                return
            if self.current_page == "Logs":
                self.action_create_snapshot()
                return
            self.action_create_snapshot()

        def action_rollback_latest_snapshot(self) -> None:
            self._run_tui_action("Rollback latest snapshot", lambda: self._request_confirmation("rollback_snapshot"))

        def action_show_help(self) -> None:
            self.dispatch_event(HelpRequested())

        def _start_testing_operation(self, action_key: str, status: str) -> None:
            if self.testing_thread is not None and self.testing_thread.is_alive():
                self._notify_user("A Testing job is already running.", key="testing-job-running")
                return
            if self.app_state is None:
                return
            job_id = f"{action_key}-{int(time.time())}"
            total = max(self.app_state.testing.summary.testable_candidates, 1)
            if action_key == "probe":
                self.dispatch_event(
                    ProbeStarted(
                        job_id=job_id,
                        total=total,
                        parallel_workers=int(self.app_state.settings.get("probe_concurrency") or 1),
                        progress_mode="phase_only",
                    )
                )

            def run_job() -> None:
                try:
                    controller.handle_operation(action_key)
                    result = controller.action_state.last_result
                    if action_key == "probe":
                        if result is not None and result.succeeded:
                            self.call_from_thread(
                                self.dispatch_event,
                                ProbeProcessCompleted(job_id=job_id, exit_code=result.exit_code or 0),
                            )
                        else:
                            failure_message = "Probe failed."
                            exit_code = None
                            if result is not None:
                                exit_code = result.exit_code
                                failure_message = redact_text(result.summary or result.redacted_stderr or result.redacted_stdout or failure_message)
                            self.call_from_thread(
                                self.dispatch_event,
                                ProbeFailed(job_id=job_id, error=failure_message, exit_code=exit_code),
                            )
                    else:
                        self.call_from_thread(self.dispatch_event, RefreshRequested())
                except Exception as exc:  # pragma: no cover - safe wrapper covers UI path
                    safe_message = redact_exception_message(str(exc))
                    if action_key == "probe":
                        self.call_from_thread(self.dispatch_event, ProbeFailed(job_id=job_id, error=safe_message))

            self.testing_thread = threading.Thread(target=run_job, daemon=True)
            self.testing_thread.start()

        def _load_testing_state(self):
            state = build_testing_store_state(
                config_path=controller._paths()["config"],
                user_data_paths=resolve_user_data_paths(controller._paths()["config"]),
                selected_index=self.testing_selected_index,
            )
            self.testing_selected_index = state.selected_index
            return state

        def _testing_workflow_state(self) -> dict[str, object]:
            if self.app_state is not None:
                return self._build_app_render_model(self.app_state).get("testing", {})
            state = self._load_testing_state()
            return {
                "summary": asdict(state.summary),
                "rows": [asdict(row) for row in state.rows],
            }

        def _run_port_check_for_route(self, route_id: str):
            entry = next((entry for entry in self.app_state.route.entries if entry.route_id == route_id), None) if self.app_state is not None else None
            if entry is None:
                raise ValueError("Route entry is not available for port check.")
            current_index = self.route_selected_index
            try:
                self.route_selected_index = next(
                    index for index, route_entry in enumerate(self.app_state.route.entries) if route_entry.route_id == route_id
                )
                self._test_selected_route_port()
            finally:
                self.route_selected_index = current_index
            result = self.route_port_results.get(route_id)
            if result is None:
                raise ValueError("Port check did not return a result.")
            return result

        def _load_route_state(self):
            state = build_route_workbench_state(
                config_path=controller._paths()["config"],
                user_data_paths=resolve_user_data_paths(controller._paths()["config"]),
                selected_index=self.route_selected_index,
                port_results=self.route_port_results,
            )
            self.route_selected_index = state.selected_index
            return state

        def _store_route_state(self, state) -> None:
            paths = resolve_user_data_paths(controller._paths()["config"])
            save_route_draft_state(user_data_paths=paths, entries=state.entries)
            if self.app_state is not None:
                self.app_state = replace(
                    self.app_state,
                    route=build_route_store_state(
                        config_path=controller._paths()["config"],
                        user_data_paths=paths,
                        selected_index=state.selected_index,
                        port_results=self.route_port_results,
                    ),
                )

        def _move_testing_selection(self, delta: int) -> str:
            state = self._load_testing_state()
            if not state.rows:
                return "No candidate rows are available yet."
            current = 0 if self.testing_selected_index is None else self.testing_selected_index
            self.testing_selected_index = max(0, min(len(state.rows) - 1, current + delta))
            return "Selection moved down." if delta > 0 else "Selection moved up."

        def _move_route_selection(self, delta: int) -> str:
            state = self._load_route_state()
            if not state.entries:
                return "No route entries are available yet."
            current = self.route_selected_index
            self.route_selected_index = max(0, min(len(state.entries) - 1, current + delta))
            return "Route selection moved down." if delta > 0 else "Route selection moved up."

        def _update_route_field(self, field: str, value: object) -> str:
            route_state = self._load_route_state()
            entries = [
                {
                    "route_id": entry.route_id,
                    "name": entry.name,
                    "enabled": entry.enabled,
                    "candidate_id": entry.candidate_id,
                    "candidate_label": entry.candidate_label,
                    "region_hint": entry.region_hint,
                    "protocol": entry.protocol,
                    "listen_host": entry.listen_host,
                    "listen_port": entry.listen_port,
                    "port_status": entry.port_status,
                    "validation_status": entry.validation_status,
                    "error": entry.error,
                }
                for entry in route_state.entries
            ]
            if not entries:
                return "No route entry is available."
            entry = entries[self.route_selected_index]
            entry[field] = value
            rebuilt = build_route_workbench_state(
                config_path=controller._paths()["config"],
                user_data_paths=resolve_user_data_paths(controller._paths()["config"]),
                selected_index=self.route_selected_index,
                port_results=self.route_port_results,
                route_entries=entries,
            )
            self._store_route_state(rebuilt)
            return f"Updated {field}."

        def _choose_selected_route_candidate(self) -> str:
            route_state = self._load_route_state()
            select_widget = self.query_one("#route-candidate-select", Select)
            value = select_widget.value
            if not isinstance(value, str) or not value:
                return "Choose a passed candidate first."
            updated = update_route_entry_candidate(route_state, entry_index=self.route_selected_index, candidate_id=value)
            self._store_route_state(updated)
            label = updated.entries[self.route_selected_index].candidate_label or value
            return f"{updated.entries[self.route_selected_index].name} candidate set to {label}."

        def _choose_route_candidate_id(self, value: str) -> str:
            route_state = self._load_route_state()
            current_candidate_id = route_state.entries[self.route_selected_index].candidate_id
            if value == current_candidate_id:
                return f"{route_state.entries[self.route_selected_index].name} candidate is already selected."
            updated = update_route_entry_candidate(route_state, entry_index=self.route_selected_index, candidate_id=value)
            self._store_route_state(updated)
            label = updated.entries[self.route_selected_index].candidate_label or value
            controller.action_state.status_message = f"{updated.entries[self.route_selected_index].name} candidate set to {label}."
            return str(controller.action_state.status_message)

        def _add_route_entry(self) -> str:
            state = self._load_route_state()
            updated = add_route_entry(state)
            self._store_route_state(updated)
            self.route_selected_index = updated.selected_index
            return "Added route draft."

        def _delete_route_entry(self) -> str:
            state = self._load_route_state()
            updated, warning = delete_route_entry(state)
            if warning is not None:
                return warning
            self._store_route_state(updated)
            self.route_selected_index = updated.selected_index
            return "Deleted selected route draft."

        def _test_selected_route_port(self) -> str:
            state = self._load_route_state()
            updated = check_selected_route_port(
                state,
                managed_service_name=str((self.app_state.settings.get("service_name") if self.app_state is not None else "") or ""),
            )
            self.route_port_results = {
                entry.route_id: result
                for entry, result in ((updated.entries[updated.selected_index], updated.current_port_result),)
                if result is not None
            } | {key: value for key, value in self.route_port_results.items() if key != updated.entries[updated.selected_index].route_id}
            self._store_route_state(updated)
            if updated.current_port_result is None:
                return "Port check did not return a result."
            return updated.current_port_result.message

        def _apply_route_draft(self) -> str:
            state = self._load_route_state()
            if state.validation_errors:
                return state.validation_errors[0]
            paths = resolve_user_data_paths(controller._paths()["config"])
            message = save_route_entries_to_config_or_selected_routes(
                controller._paths()["config"],
                user_data_paths=paths,
                entries=state.entries,
            )
            controller.reload()
            self.route_port_results = {}
            return message

        def _request_confirmation(self, action_key: str, handler: Callable[[], str] | None = None) -> str:
            policy = get_action_policy(action_key)
            pending = PendingAction(
                key=action_key,
                title=_pending_title_for_action(action_key),
                requires_confirmation=policy.requires_confirmation,
                risk_note=policy.user_facing_risk,
            )
            controller.pending_action = pending
            controller.action_state.pending_confirmation = action_key
            controller.action_state.status_message = f"Pending: {pending.title}. Press Enter to confirm or Esc to cancel."
            self.pending_action_handler = handler
            return str(controller.action_state.status_message)

        def _confirm_pending_action(self) -> str:
            pending = controller.pending_action
            if pending is None:
                return "No pending action to confirm."
            handler = self.pending_action_handler
            self.pending_action_handler = None
            if handler is not None:
                result = handler()
                controller.pending_action = None
                controller.action_state.pending_confirmation = None
                controller.action_state.status_message = result
                return result
            return controller.handle_operation(pending.key)

    ScholarOutboundWorkflowApp().run()
    return 0


__all__ = [
    "MAIN_TABS",
    "TUI_KEY_BINDINGS",
    "_build_tab_specs",
    "_textual_safe_id",
    "build_parser",
    "control_plane_state_to_workflow_dict",
    "load_dashboard_state",
    "load_workflow_state",
    "main",
    "render_tab_text",
    "save_selection_from_index",
]
