"""Optional workflow-oriented Textual TUI entry point and helpers."""

from __future__ import annotations

import argparse
import json
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
from scholar_outbound_manager.tui.action_runner import append_action_journal
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
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.screens import build_ascii_tab_strip
from scholar_outbound_manager.tui.state import build_session_state
from scholar_outbound_manager.tui.state import write_session_state
from scholar_outbound_manager.tui.view_model import ActivateStep
from scholar_outbound_manager.tui.view_model import build_home_cards
from scholar_outbound_manager.tui.view_model import build_logs_summary
from scholar_outbound_manager.tui.view_model import RouteSummary
from scholar_outbound_manager.tui.view_model import SettingsFieldView
from scholar_outbound_manager.tui.view_model import build_activate_steps
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
        return "Keys: 1-5 pages | Enter confirm | Esc cancel | q quit"
    shortcuts = {
        "Home": "Keys: 1-5 pages | f fetch | p test nodes | x snapshot | q quit",
        "Settings": "Keys: 1-5 pages | s save | u undo | d diff | f test fetch | q quit",
        "Testing": "Keys: 1-5 pages | f fetch | p test nodes | j/k move | q quit",
        "Route": "Keys: 1-5 pages | c choose node | g stage | v validate | q quit",
        "Logs": "Keys: 1-5 pages | a artifact check | x snapshot | z rollback | q quit",
    }
    return shortcuts.get(tab, "Keys: 1-5 pages | r refresh | q quit")


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


def control_plane_state_to_workflow_dict(control_plane: ControlPlaneState) -> dict[str, object]:
    """Adapt the control-plane dataclass tree to the legacy workflow-state shape."""
    payload = control_plane_state_to_dict(control_plane)
    config_path = str(payload["session"]["paths"]["config"])
    config_summary = summarize_config_centered_state(config_path)
    wizard = build_first_run_wizard_state(config_path)
    rows = list(payload["selection_state"]["rows"])
    passed_count = sum(1 for row in rows if row.get("passed") is True)
    route_count = len(config_summary.route_entries)
    enabled_route_count = sum(1 for row in config_summary.route_entries if row.get("enabled") is True)
    markers = {
        "full_access": 0,
        "query_blocked": 0,
        "transport_failed": 0,
    }
    for row in rows:
        stage = str(row.get("stage") or "")
        if stage in markers:
            markers[stage] += 1
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
            "last_fetch_status": "ready" if payload["artifact_state"]["candidates_exists"] else "not_fetched",
            "candidate_count": len(rows),
            "supported_count": len(rows),
            "experimental_disabled_count": 0 if config_summary.experimental_hysteria2 else 0,
            "tested_count": len(rows),
            "passed_count": passed_count,
            "failed_count": max(0, len(rows) - passed_count),
            "last_probe_status": "ready" if payload["artifact_state"]["probe_summary_exists"] else "not_tested",
            "full_access_count": markers["full_access"],
            "query_blocked_count": markers["query_blocked"],
            "transport_failed_count": markers["transport_failed"],
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
        "testing": {
            "candidate_rows": rows,
            "tested_count": len(rows),
            "passed_count": passed_count,
            "failed_count": max(0, len(rows) - passed_count),
            "full_access_count": markers["full_access"],
            "query_blocked_count": markers["query_blocked"],
            "transport_failed_count": markers["transport_failed"],
            "toolbar_actions": ["Fetch Subscription", "Test Nodes", "Retest Failed", "Stop"],
        },
        "route": {
            "entries": config_summary.route_entries,
            "selected_candidate_label": payload["selection_state"]["selected_candidate_label"],
            "selected_candidate_id": payload["selection_state"]["selected_candidate_id"],
            "service_name": config_summary.service_name,
            "production_boundary": "Only manages the ScholarOutboundManager sidecar. It does not modify production Xray/XrayR/x-ui.",
            "actions": ["Add Route", "Remove Route", "Apply", "Start", "Stop", "Restart", "Validate"],
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
        lines = [
            "Testing",
            "",
            "Toolbar: [Fetch Subscription] [Test Nodes] [Retest Failed] [Stop]",
            f"Progress: {testing.get('passed_count')} passed / {testing.get('tested_count')} tested",
            "",
            "Candidate table",
            "  " + " | ".join(table.columns),
        ]
        for row in table.rows[:8]:
            lines.append("  " + " | ".join(row))
        if not table.rows:
            lines.append(f"  {table.empty_message}")
        return "\n".join(lines)
    if tab == "Route":
        route = workflow_state.get("route", {})
        table = build_route_table_model(workflow_state)
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
                f"  Candidate: {route.get('selected_candidate_label') or 'none'}",
                f"  Managed service: {route.get('service_name')}",
                "  Actions: [Add Route] [Remove Route] [Apply] [Start] [Stop] [Restart] [Validate]",
                f"  Boundary: {route.get('production_boundary')}",
            ]
        )
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
        from textual.widgets import RichLog
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
        current_page = "Home"

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="tui-root"):
                with Vertical(id="nav-rail"):
                    yield Static("Scholar Outbound Manager", id="nav-title")
                    for page in controller.workflow_state["tabs"]:
                        yield Button(page, id=f"nav-{_textual_safe_id(page)}")
                with Vertical(id="main-column"):
                    yield from self._build_home_page()
                    yield from self._build_settings_page()
                    yield from self._build_testing_page()
                    yield from self._build_route_page()
                    yield from self._build_logs_page()
                with Vertical(id="inspector-column"):
                    yield Static("Inspector", id="inspector-title")
                    yield Static("", id="inspector-body")
            yield Static("", id="shortcut-bar")
            yield Footer()

        def on_mount(self) -> None:
            self._init_tables()
            self._set_page("Home")
            self._refresh_ui()

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
                yield Input("", id="settings-config-path", disabled=True)
                yield Input("", id="settings-user-data-dir")
                yield Input("", id="settings-subscription-url", password=True)
                yield Input("", id="settings-user-agent")
                yield Input("", id="settings-xray-path")
                yield Input("", id="settings-service-name")
                yield Switch(value=True, id="settings-fail-closed")
                yield Switch(value=False, id="settings-hysteria2")
                with Horizontal(id="settings-actions"):
                    yield Button("Save", id="settings-save")
                    yield Button("Undo", id="settings-undo")
                    yield Button("Show Diff", id="settings-diff")
                    yield Button("Test Fetch", id="settings-test-fetch")
                yield Static("", id="settings-diff-panel")

        def _build_testing_page(self):
            with Vertical(id="page-testing"):
                with Horizontal(id="testing-actions"):
                    yield Button("Fetch Subscription", id="testing-fetch")
                    yield Button("Test Nodes", id="testing-probe")
                    yield Button("Retest Failed", id="testing-retest")
                    yield Button("Stop", id="testing-stop", disabled=True)
                yield Static("", id="testing-status")
                yield DataTable(id="testing-table")
                yield Static("", id="testing-detail")

        def _build_route_page(self):
            with Vertical(id="page-route"):
                with Horizontal(id="route-actions"):
                    yield Button("Choose Passed Node", id="route-select")
                    yield Button("Apply", id="route-apply")
                    yield Button("Start", id="route-start")
                    yield Button("Stop", id="route-stop")
                    yield Button("Restart", id="route-restart")
                    yield Button("Validate", id="route-validate")
                yield DataTable(id="route-table")
                yield Input("", id="route-listen-host")
                yield Input("", id="route-listen-port")
                yield Switch(value=True, id="route-enabled")
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
            testing_table.add_columns(*build_testing_table_model(controller.workflow_state).columns)
            route_table = self.query_one("#route-table", DataTable)
            route_table.add_columns(*build_route_table_model(controller.workflow_state).columns)
            action_table = self.query_one("#logs-action-table", DataTable)
            action_table.add_columns("action", "status", "summary")
            snapshot_table = self.query_one("#logs-snapshot-table", DataTable)
            snapshot_table.add_columns("snapshot", "reason")

        def _set_page(self, page: str) -> None:
            self.current_page = page
            controller.selection.active_tab = page
            for candidate in controller.workflow_state["tabs"]:
                page_widget = self.query_one(f"#page-{_textual_safe_id(candidate)}", Vertical)
                page_widget.display = candidate == page
                button = self.query_one(f"#nav-{_textual_safe_id(candidate)}", Button)
                button.variant = "primary" if candidate == page else "default"
            self.query_one("#shortcut-bar", Static).update(
                _shortcuts_for_tab(page, pending_confirmation=bool(controller.pending_action))
            )

        def _refresh_ui(self) -> None:
            self.query_one("#home-summary", Static).update(render_tab_text("Home", controller.workflow_state))
            self.query_one("#settings-diff-panel", Static).update(
                controller.workflow_state.get("settings", {}).get("redacted_diff") or "No pending redacted diff."
            )
            settings = build_settings_summary(controller.workflow_state)
            self.query_one("#settings-config-path", Input).value = settings.config_path
            self.query_one("#settings-user-data-dir", Input).value = settings.user_data_dir
            self.query_one("#settings-subscription-url", Input).value = settings.subscription_url_masked
            self.query_one("#settings-user-agent", Input).value = settings.subscription_user_agent
            self.query_one("#settings-xray-path", Input).value = settings.xray_binary_path
            self.query_one("#settings-service-name", Input).value = settings.service_name
            self.query_one("#settings-fail-closed", Switch).value = settings.fail_closed
            self.query_one("#settings-hysteria2", Switch).value = settings.experimental_hysteria2

            testing = controller.workflow_state.get("testing", {})
            self.query_one("#testing-status", Static).update(
                f"Testing summary: passed {testing.get('passed_count')} / tested {testing.get('tested_count')}"
            )
            testing_table = self.query_one("#testing-table", DataTable)
            testing_table.clear()
            testing_model = build_testing_table_model(controller.workflow_state)
            for row in testing_model.rows:
                testing_table.add_row(*row)
            selected_detail = controller.build_workbench_state().get("selected_candidate_detail")
            self.query_one("#testing-detail", Static).update(
                render_tab_text("Testing", controller.workflow_state) if not isinstance(selected_detail, dict) else str(build_route_detail(selected_detail) or "")
            )

            route_table = self.query_one("#route-table", DataTable)
            route_table.clear()
            route_model = build_route_table_model(controller.workflow_state)
            for row in route_model.rows:
                route_table.add_row(*row)
            first_route = controller.workflow_state.get("route", {}).get("entries", [])
            route_entry = first_route[0] if isinstance(first_route, list) and first_route else {}
            self.query_one("#route-listen-host", Input).value = str(route_entry.get("listen_host") or "127.0.0.1")
            self.query_one("#route-listen-port", Input).value = str(route_entry.get("listen_port") or "19080")
            self.query_one("#route-enabled", Switch).value = bool(route_entry.get("enabled", True))
            self.query_one("#route-boundary", Static).update(
                controller.workflow_state.get("route", {}).get("production_boundary") or ""
            )

            logs = build_logs_summary(controller.workflow_state)
            action_table = self.query_one("#logs-action-table", DataTable)
            action_table.clear()
            for row in logs.action_rows:
                action_table.add_row(*row)
            snapshot_table = self.query_one("#logs-snapshot-table", DataTable)
            snapshot_table.clear()
            for row in logs.snapshot_rows:
                snapshot_table.add_row(*row)
            rich_log = self.query_one("#logs-rich-log", RichLog)
            rich_log.clear()
            for line in logs.rollback_warning:
                rich_log.write(line)

            self._refresh_inspector()
            self.query_one("#shortcut-bar", Static).update(
                _shortcuts_for_tab(self.current_page, pending_confirmation=bool(controller.pending_action))
            )

        def _refresh_inspector(self) -> None:
            if self.current_page == "Home":
                body = [
                    f"Next action: {controller.workflow_state.get('home', {}).get('next_recommended_action')}",
                    f"Latest action: {controller.workflow_state.get('home', {}).get('latest_action_summary') or 'none'}",
                ]
            elif self.current_page == "Settings":
                body = [
                    "Config-centered editing surface.",
                    "Subscription URL remains masked in the UI.",
                    "Undo restores config.yaml only.",
                ]
            elif self.current_page == "Testing":
                body = [
                    "Fetch/Test are explicit live operations.",
                    "Table rows remain redacted.",
                    "No raw probe_summary paths are shown here.",
                ]
            elif self.current_page == "Route":
                body = [
                    "Only the managed sidecar is in scope.",
                    "No production Xray/XrayR/x-ui mutation.",
                    "Validate is explicit and review-safe.",
                ]
            else:
                body = [
                    "Rollback restores local artifacts only.",
                    "It does not undo network effects.",
                    "It does not restart sidecar.",
                ]
            self.query_one("#inspector-body", Static).update("\n".join(body))

        def _run_tui_action(self, description: str, func: Callable[[], str | None]) -> None:
            message, succeeded = _run_safe_tui_action(controller, description, func)
            self._refresh_ui()
            if message:
                self.notify(message)
            elif succeeded and controller.action_state.status_message:
                self.notify(str(controller.action_state.status_message))

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
                self._set_page(page)
                self._refresh_inspector()
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
                "testing-retest": self.action_run_probe,
                "route-select": self.action_run_select,
                "route-apply": self.action_run_stage_sidecar,
                "route-start": self.action_route_start_placeholder,
                "route-stop": self.action_route_stop_placeholder,
                "route-restart": self.action_run_restart_sidecar,
                "route-validate": self.action_run_validate_sidecar,
                "logs-artifact-check": self.action_run_artifact_check,
                "logs-snapshot": self.action_create_snapshot,
                "logs-rollback": self.action_rollback_latest_snapshot,
            }
            action = button_actions.get(button_id)
            if action is not None:
                action()

        def action_open_home(self) -> None:
            self._set_page("Home")

        def action_open_settings(self) -> None:
            self._set_page("Settings")

        def action_open_testing(self) -> None:
            self._set_page("Testing")

        def action_open_route(self) -> None:
            self._set_page("Route")

        def action_open_logs(self) -> None:
            self._set_page("Logs")

        def action_reload_state(self) -> None:
            self._run_tui_action("Reload state", lambda: (controller.reload(), str(controller.action_state.status_message))[1])

        def action_save_draft(self) -> None:
            self._run_tui_action("Save config draft", lambda: controller.save_config().message)

        def action_undo_save(self) -> None:
            self._run_tui_action("Undo config save", controller.undo_config_save)

        def action_show_config_diff(self) -> None:
            self._run_tui_action(
                "Show redacted config diff",
                lambda: (
                    controller.workflow_state["config_form"]["redacted_diff"]
                    or controller.workflow_state["config_editor"]["redacted_diff"]
                    or "No pending redacted config diff is available."
                ),
            )

        def action_cursor_down(self) -> None:
            self._run_tui_action("Move selection", lambda: (controller.move_candidate(1), "Selection moved down.")[1])

        def action_cursor_up(self) -> None:
            self._run_tui_action("Move selection", lambda: (controller.move_candidate(-1), "Selection moved up.")[1])

        def action_confirm_selected(self) -> None:
            self._run_tui_action("Confirm selected action", lambda: controller.handle_operation("choose_selected_candidate"))

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

        def action_run_restart_sidecar(self) -> None:
            self._run_tui_action("Restart sidecar", lambda: controller.handle_operation("service_restart"))

        def action_run_validate_sidecar(self) -> None:
            self._run_tui_action("Validate sidecar", lambda: controller.handle_operation("service_validate"))

        def action_route_start_placeholder(self) -> None:
            self._run_tui_action(
                "Start sidecar",
                lambda: "Managed start remains explicit and out of scope in this phase; restart/validate are the safe wired actions.",
            )

        def action_route_stop_placeholder(self) -> None:
            self._run_tui_action(
                "Stop sidecar",
                lambda: "Managed stop remains explicit and out of scope in this phase; no external Xray process is touched.",
            )

        def action_create_snapshot(self) -> None:
            self._run_tui_action("Create snapshot", controller.create_snapshot_message)

        def action_rollback_latest_snapshot(self) -> None:
            self._run_tui_action("Rollback latest snapshot", controller.rollback_latest_snapshot)

        def action_show_help(self) -> None:
            self._run_tui_action("Show help", lambda: _shortcuts_for_tab(self.current_page, pending_confirmation=bool(controller.pending_action)))

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
