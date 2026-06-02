"""Optional workflow-oriented Textual TUI entry point and helpers."""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from collections.abc import Sequence
from pathlib import Path

from scholar_outbound_manager.selection import build_selected_candidate_artifact
from scholar_outbound_manager.selection import load_candidate_payload
from scholar_outbound_manager.selection import select_candidate_by_index
from scholar_outbound_manager.selection import write_selected_candidate_artifact
from scholar_outbound_manager.tui.action_runner import ActionResult
from scholar_outbound_manager.tui.artifact_rollback import ArtifactSnapshot
from scholar_outbound_manager.tui.action_runner import FakeActionRunner
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_SESSION_PATH
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ACTION_JOURNAL_PATH
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ARTIFACT_SNAPSHOT_ROOT
from scholar_outbound_manager.tui.control_plane import ControlPlaneState
from scholar_outbound_manager.tui.control_plane import control_plane_state_to_dict
from scholar_outbound_manager.tui.control_plane import load_control_plane_state
from scholar_outbound_manager.tui.controller import WorkbenchMessage
from scholar_outbound_manager.tui.controller import WorkbenchController as BaseWorkbenchController
from scholar_outbound_manager.tui.screens import build_ascii_tab_strip
from scholar_outbound_manager.tui.state import build_session_state
from scholar_outbound_manager.tui.state import write_session_state
from scholar_outbound_manager.tui.view_model import ActivateStep
from scholar_outbound_manager.tui.view_model import RouteSummary
from scholar_outbound_manager.tui.view_model import SettingsFieldView
from scholar_outbound_manager.tui.view_model import build_activate_steps
from scholar_outbound_manager.tui.view_model import build_operation_impact
from scholar_outbound_manager.tui.view_model import build_route_detail
from scholar_outbound_manager.tui.view_model import build_route_summaries
from scholar_outbound_manager.tui.view_model import build_settings_groups
from scholar_outbound_manager.tui.view_model import build_workflow_summary
from scholar_outbound_manager.tui.view_model import redact_text
from scholar_outbound_manager.tui.view_model import resolve_next_action
from scholar_outbound_manager.tui.workflow import MAIN_TABS


TUI_KEY_BINDINGS: tuple[tuple[str, str, str], ...] = (
    ("q", "quit", "Quit"),
    ("r", "reload_state", "Reload State"),
    ("j", "cursor_down", "Move Down"),
    ("k", "cursor_up", "Move Up"),
    ("enter", "confirm_selected", "Confirm"),
    ("escape", "cancel_pending", "Cancel Pending"),
    ("e", "edit_config_field", "Edit Config Field"),
    ("d", "show_config_diff", "Show Config Diff"),
    ("s", "save_draft", "Save Draft"),
    ("u", "undo_save", "Undo Save"),
    ("f", "run_fetch", "Run Fetch"),
    ("p", "run_probe", "Run Probe"),
    ("a", "run_artifact_check", "Run Artifact Check"),
    ("c", "run_select", "Run Select"),
    ("g", "run_stage_sidecar", "Run Stage Sidecar"),
    ("v", "run_validate_sidecar", "Run Validate"),
    ("x", "create_snapshot", "Create Snapshot"),
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
    if len(redacted) <= 240:
        return redacted
    return redacted[:237] + "..."


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
        controller.message = WorkbenchMessage("error", description, safe_message)
        controller.action_state.status_message = safe_message
        controller.workflow_state = _build_workflow_state(controller)
        return f"{description} failed: {safe_message}", False
    controller.workflow_state = _build_workflow_state(controller)
    return message, True


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
        return "Shortcuts: Enter confirm | Esc cancel | q quit"
    shortcuts = {
        "Overview": "Shortcuts: Tab change page | Enter next action | r refresh | l logs | q quit",
        "Candidates": "Shortcuts: j/k move | Enter select route | d details | c choose | r re-test routes | q quit",
        "Activate": "Shortcuts: Enter run next step | v validate | l logs | Esc back | q quit",
        "Status": "Shortcuts: v validate | a activate | l logs | r refresh | q quit",
        "Logs": "Shortcuts: j/k scroll | c copy command | r refresh | q quit",
        "Settings": "Shortcuts: j/k move | e edit | s save | u undo | d diff | q quit",
    }
    return shortcuts.get(tab, "Shortcuts: r refresh | q quit")


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
        if (tab == "Overview" and initial_id == "tab") or index == 0:
            initial_id = safe_id if tab == "Overview" else initial_id
    if initial_id == "tab":
        initial_id = specs[0]["id"]
    return specs, initial_id


def build_parser() -> argparse.ArgumentParser:
    """Build the TUI-specific parser."""
    parser = argparse.ArgumentParser(prog="scholar-outbound-manager-tui")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--candidates", default="candidates.json")
    parser.add_argument("--probe-summary", default="state_data/probe_summary.json")
    parser.add_argument("--passed-candidates", default="state_data/passed_candidates.json")
    parser.add_argument("--selected-candidate", default="state_data/selected_candidate.json")
    parser.add_argument("--pool-plan", default="state_data/sidecar_pool_plan.json")
    parser.add_argument("--session", default=DEFAULT_TUI_SESSION_PATH)
    parser.add_argument("--output", default="state_data/selected_candidate.json")
    parser.add_argument("--strategy", default="auto", choices=("auto", "manual", "geo_nearest", "geo-nearest", "region_hint", "region-hint", "first"))
    parser.add_argument("--geo-cache", default="state_data/geo/candidate_geo_cache.json")
    parser.add_argument("--host-geo", default="state_data/geo/host_geo.json")
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
    candidates_path: str = "candidates.json",
    probe_summary_path: str = "state_data/probe_summary.json",
    passed_candidates_path: str = "state_data/passed_candidates.json",
    selected_candidate_path: str = "state_data/selected_candidate.json",
    pool_plan_path: str = "state_data/sidecar_pool_plan.json",
    session_path: str = DEFAULT_TUI_SESSION_PATH,
    action_journal_path: str = DEFAULT_TUI_ACTION_JOURNAL_PATH,
    snapshot_root: str = DEFAULT_TUI_ARTIFACT_SNAPSHOT_ROOT,
    output_path: str = "state_data/selected_candidate.json",
    strategy: str = "auto",
    geo_cache_path: str = "state_data/geo/candidate_geo_cache.json",
    host_geo_path: str = "state_data/geo/host_geo.json",
    prefer_geo: bool = True,
    preferred_region_hint: str | None = None,
) -> dict[str, object]:
    """Build a workflow-oriented, redacted TUI state model."""
    control_plane = load_control_plane_state(
        config_path=config_path,
        candidates_path=candidates_path,
        probe_summary_path=probe_summary_path,
        passed_candidates_path=passed_candidates_path,
        selected_candidate_path=selected_candidate_path,
        pool_plan_path=pool_plan_path,
        session_path=session_path,
        action_journal_path=action_journal_path,
        snapshot_root=snapshot_root,
        output_path=output_path,
        strategy=strategy,
        geo_cache_path=geo_cache_path,
        host_geo_path=host_geo_path,
        prefer_geo=prefer_geo,
        preferred_region_hint=preferred_region_hint,
    )
    return control_plane_state_to_workflow_dict(control_plane)


def control_plane_state_to_workflow_dict(control_plane: ControlPlaneState) -> dict[str, object]:
    """Adapt the control-plane dataclass tree to the legacy workflow-state shape."""
    payload = control_plane_state_to_dict(control_plane)
    return {
        "tabs": payload["tabs"],
        "tab_strip": build_ascii_tab_strip(),
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
        from textual.containers import Vertical
        from textual.widgets import Header
        from textual.widgets import Static
        from textual.widgets import TabbedContent
        from textual.widgets import TabPane
    except ModuleNotFoundError as exc:
        if exc.name != "textual":
            raise
        print('Textual TUI is not installed. Install with:\npip install "ScholarOutboundManager[tui]"')
        return 1

    controller = WorkflowController(
        loader_kwargs={
            "config_path": args.config,
            "candidates_path": args.candidates,
            "probe_summary_path": args.probe_summary,
            "passed_candidates_path": args.passed_candidates,
            "selected_candidate_path": args.selected_candidate,
            "pool_plan_path": args.pool_plan,
            "session_path": args.session,
            "action_journal_path": DEFAULT_TUI_ACTION_JOURNAL_PATH,
            "snapshot_root": DEFAULT_TUI_ARTIFACT_SNAPSHOT_ROOT,
            "output_path": args.output,
            "strategy": args.strategy,
            "geo_cache_path": args.geo_cache,
            "host_geo_path": args.host_geo,
            "prefer_geo": args.prefer_geo,
            "preferred_region_hint": args.preferred_region_hint,
        },
    )
    workflow_state = controller.workflow_state
    write_session_state(
        args.session,
        build_session_state(
            updated_at=workflow_state["session"]["updated_at"],
            workspace=workflow_state["session"]["workspace"],
            last_step=None,
            paths=workflow_state["paths"],
            last_results=workflow_state["session"]["last_results"],
        ),
    )

    class ScholarOutboundWorkflowApp(App[None]):
        """Minimal tabbed workflow-oriented TUI."""

        BINDINGS = list(TUI_KEY_BINDINGS)

        def _current_tab_title(self) -> str:
            try:
                tabbed = self.query_one(TabbedContent)
                active_id = str(tabbed.active or "")
            except Exception:
                return controller.selection.active_tab
            for tab_name in controller.workflow_state["tabs"]:
                if _textual_safe_id(tab_name) == active_id:
                    return tab_name
            return controller.selection.active_tab

        def _sync_active_tab(self) -> None:
            controller.selection.active_tab = self._current_tab_title()

        def compose(self) -> ComposeResult:
            tab_specs, initial_tab_id = _build_tab_specs(list(controller.workflow_state["tabs"]))
            yield Header()
            with TabbedContent(initial=initial_tab_id):
                for tab_spec in tab_specs:
                    with TabPane(tab_spec["title"], id=tab_spec["id"]):
                        with Vertical():
                            yield Static(
                                render_tab_text(tab_spec["title"], controller.workflow_state),
                                id=_tab_body_id(tab_spec["title"]),
                            )
            yield Static(
                _shortcuts_for_tab(controller.selection.active_tab, pending_confirmation=bool(controller.pending_action)),
                id="shortcut-bar",
            )

        def _refresh_all_tabs(self) -> None:
            _refresh_tab_bodies(
                list(controller.workflow_state["tabs"]),
                controller.workflow_state,
                lambda body_id, text: self.query_one(f"#{body_id}", Static).update(text),
            )
            self.query_one("#shortcut-bar", Static).update(
                _shortcuts_for_tab(self._current_tab_title(), pending_confirmation=bool(controller.pending_action))
            )

        def _run_tui_action(self, description: str, func: Callable[[], str | None]) -> None:
            self._sync_active_tab()
            message, succeeded = _run_safe_tui_action(controller, description, func)
            self._refresh_all_tabs()
            if message:
                self.notify(message)
            elif succeeded and controller.action_state.status_message:
                self.notify(str(controller.action_state.status_message))

        def action_reload_state(self) -> None:
            self._run_tui_action("Reload state", lambda: (controller.reload(), str(controller.action_state.status_message))[1])

        def action_save_draft(self) -> None:
            self._run_tui_action("Save config draft", lambda: controller.save_config().message)

        def action_undo_save(self) -> None:
            self._run_tui_action("Undo config save", controller.undo_config_save)

        def action_edit_config_field(self) -> None:
            def _describe_selected_field() -> str:
                selected = controller.build_workbench_state().get("selected_config_field")
                if not isinstance(selected, dict):
                    return "No editable structured config fields are available."
                return f"Structured config field: {selected['key']} current={selected['current_value']}"

            self._run_tui_action("Inspect config field", _describe_selected_field)

        def action_show_config_diff(self) -> None:
            def _show_contextual_details() -> str:
                if controller.selection.active_tab == "Candidates":
                    return str(build_route_detail(controller.build_workbench_state().get("selected_candidate_detail")) or "No route details are available.")
                return (
                    controller.workflow_state["config_form"]["redacted_diff"]
                    or controller.workflow_state["config_editor"]["redacted_diff"]
                    or "No pending redacted config diff is available."
                )

            self._run_tui_action("Show details", _show_contextual_details)

        def action_cursor_down(self) -> None:
            def _move_down() -> str:
                if controller.selection.active_tab == "Settings":
                    controller.move_config_field(1)
                else:
                    controller.move_candidate(1)
                return "Selection moved down."

            self._run_tui_action("Move selection", _move_down)

        def action_cursor_up(self) -> None:
            def _move_up() -> str:
                if controller.selection.active_tab == "Settings":
                    controller.move_config_field(-1)
                else:
                    controller.move_candidate(-1)
                return "Selection moved up."

            self._run_tui_action("Move selection", _move_up)

        def action_confirm_selected(self) -> None:
            def _primary_action() -> str:
                if controller.selection.active_tab == "Candidates":
                    return controller.handle_operation("choose_selected_candidate")
                if controller.selection.active_tab == "Activate":
                    return controller.handle_operation("sidecar_stage")
                if controller.selection.active_tab == "Status":
                    return controller.handle_operation("service_validate")
                return str(controller.preview_selected_candidate())

            self._run_tui_action("Primary action", _primary_action)

        def action_cancel_pending(self) -> None:
            self._run_tui_action("Cancel pending action", lambda: (controller.clear_pending_action(), "Pending action cleared.")[1])

        def action_run_fetch(self) -> None:
            self._run_tui_action("Run fetch", lambda: controller.handle_operation("fetch"))

        def action_run_probe(self) -> None:
            self._run_tui_action("Run probe", lambda: controller.handle_operation("probe"))

        def action_run_artifact_check(self) -> None:
            self._run_tui_action("Run artifact check", lambda: controller.handle_operation("artifact_check"))

        def action_run_select(self) -> None:
            self._run_tui_action("Choose selected candidate", lambda: controller.handle_operation("choose_selected_candidate"))

        def action_run_stage_sidecar(self) -> None:
            self._run_tui_action("Stage sidecar", lambda: controller.handle_operation("sidecar_stage"))

        def action_run_validate_sidecar(self) -> None:
            self._run_tui_action("Validate sidecar", lambda: controller.handle_operation("service_validate"))

        def action_create_snapshot(self) -> None:
            self._run_tui_action("Create snapshot", controller.create_snapshot_message)

        def action_rollback_latest_snapshot(self) -> None:
            self._run_tui_action("Rollback latest snapshot", controller.rollback_latest_snapshot)

        def action_show_help(self) -> None:
            self._run_tui_action(
                "Show help",
                lambda: _shortcuts_for_tab(controller.selection.active_tab, pending_confirmation=bool(controller.pending_action)),
            )

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
