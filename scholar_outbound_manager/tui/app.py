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
from scholar_outbound_manager.tui.view_model import redact_text
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


def _render_config_field_lines(form: dict[str, object]) -> list[str]:
    rendered = [
        "sensitive fields excluded: subscription URLs, proxy URIs, UUIDs, passwords, auth, tokens, public keys, server names, and obfs passwords.",
    ]
    for field in form.get("fields", []):
        if not isinstance(field, dict):
            continue
        rendered.append(
            " - {key} | type={value_type} | editable={editable} | restart_required={requires_restart}".format(
                key=field.get("key"),
                value_type=field.get("value_type"),
                editable=field.get("editable"),
                requires_restart=field.get("requires_restart"),
            )
        )
    return rendered


def _render_operation_status_line(control_plane: dict[str, object], operation_key: str) -> str:
    operations = (
        control_plane.get("command_state", {}).get("operations", [])
        if isinstance(control_plane, dict)
        else []
    )
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("key") != operation_key:
            continue
        return (
            f"{operation_key}: confirm_required={operation.get('requires_confirmation')} "
            f"network={operation.get('network_access')} "
            f"systemd={operation.get('systemd_access')} "
            f"risk={operation.get('risk_note')}"
        )
    return f"{operation_key}: operation metadata unavailable"


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
        if (tab == "Dashboard" and initial_id == "tab") or index == 0:
            initial_id = safe_id if tab == "Dashboard" else initial_id
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
    for row in rows:
        if not isinstance(row, dict):
            continue
        rendered.append(
            {
                **row,
                "selected": row.get("index") == selected_index,
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
    if tab == "Dashboard":
        dashboard = workflow_state["dashboard"]
        blocking_reason = workflow_state["control_plane"]["workflow_state"]["blocking_reason"]
        return "\n".join(
            [
                "Workflow-oriented TUI",
                workflow_state["tab_strip"],
                f"repo_status: {dashboard['repo_status']}",
                f"current_git_commit: {dashboard['current_git_commit']}",
                f"config_dirty: {dashboard['config_dirty']}",
                f"config_valid: {dashboard['config_valid']}",
                f"undo_available: {dashboard['undo_available']}",
                f"candidate_count: {dashboard['candidate_count']}",
                f"passed_count: {dashboard['passed_count']}",
                f"selected_candidate_label: {dashboard['selected_candidate_label']}",
                f"blocking_reason: {blocking_reason}",
                f"next_recommended_action: {dashboard['next_recommended_action']}",
                f"last_action: {_format_last_action(dashboard['last_action'])}",
                f"snapshot_count: {dashboard['snapshot_count']}",
                f"latest_snapshot_id: {dashboard['latest_snapshot_id']}",
                *(["pending_action: " + str(workbench.get("pending_action"))] if workbench.get("pending_action") else []),
                *_render_action_history(workbench),
            ]
        )
    if tab == "Config":
        editor = workflow_state["config_editor"]
        form = workflow_state["config_form"]
        lines = [
            "Step 1: Config",
            f"config exists: {workflow_state['preflight']['config_exists']}",
            f"config valid: {workflow_state['preflight']['config_valid']}",
            f"validation errors: {workflow_state['preflight']['config_validation_errors']}",
            f"undo_available: {editor['undo_available']}",
            f"config_save_available: {workflow_state['operation_availability']['config_save_available']}",
            f"config_undo_available: {workflow_state['operation_availability']['config_undo_available']}",
            "fields:",
            *_render_config_field_lines(form),
            f"selected_config_field: {workbench.get('selected_config_field')}",
            "Preview:",
            form["redacted_diff"] or editor["redacted_diff"] or editor["redacted_preview"],
            "Hints: q quit | r reload | j/k move field | e edit field | d show diff | s save | u undo | x snapshot | z rollback | ? help",
        ]
        return "\n".join(lines)
    if tab == "Fetch & Probe":
        return "\n".join(
            [
                workflow_state["warnings"][0],
                f"fetch: {workflow_state['commands']['fetch']}",
                f"probe: {workflow_state['commands']['probe']}",
                _render_operation_status_line(workflow_state["control_plane"], "fetch"),
                _render_operation_status_line(workflow_state["control_plane"], "probe"),
                f"fetch_available: {workflow_state['operation_availability']['fetch_available']}",
                f"probe_available: {workflow_state['operation_availability']['probe_available']}",
                *_render_action_history(workbench),
            ]
        )
    if tab == "Artifacts":
        return "\n".join(
            [
                f"artifact check: {workflow_state['commands']['artifact_check']}",
                f"artifact result: {workflow_state['artifacts']['artifact_check']}",
                f"artifact_check_available: {workflow_state['operation_availability']['artifact_check_available']}",
                f"snapshot_count: {workflow_state['artifacts']['snapshot_count']}",
                f"latest_snapshot_id: {workflow_state['artifacts']['latest_snapshot_id']}",
                f"latest_snapshot_reason: {workflow_state['artifacts']['latest_snapshot_reason']}",
                f"artifact_snapshot_available: {workflow_state['operation_availability']['artifact_snapshot_available']}",
                f"artifact_rollback_available: {workflow_state['operation_availability']['artifact_rollback_available']}",
                f"candidates_hash: {workflow_state['artifacts']['candidates_hash']}",
                f"probe_summary_hash: {workflow_state['artifacts']['probe_summary_hash']}",
                f"passed_candidates_hash: {workflow_state['artifacts']['passed_candidates_hash']}",
                f"warnings: {workflow_state['artifacts']['warnings']}",
                "rollback_warning: rollback restores local artifacts only and does not undo network or systemd side effects.",
                "rollback_warning_2: rollback does not restart the sidecar and does not modify production Xray/XrayR/x-ui.",
                *_render_snapshot_rows(workbench),
            ]
        )
    if tab == "Selection":
        detail = workbench.get("selected_candidate_detail")
        return "\n".join(
            [
                workflow_state["selection"]["sensitive_notice"],
                *_render_candidate_rows(workbench),
                f"selected_candidate_detail: {detail}",
                f"selected_candidate_id: {workflow_state['selection']['selected_candidate_id']}",
                f"selected_candidate_label: {workflow_state['selection']['selected_candidate_label']}",
                f"selected_region_hint: {workflow_state['selection']['selected_region_hint']}",
                f"preferred_region_hint: {workflow_state['selection']['preferred_region_hint']}",
                f"selection_method: {workflow_state['selection']['selection_method']}",
                f"selection_reason: {workflow_state['selection']['selection_reason']}",
                f"select preview: {workflow_state['commands']['select']}",
                f"select_available: {workflow_state['operation_availability']['select_available']}",
                "Hints: j/k move candidate | enter inspect | c choose selected candidate | r reload",
            ]
        )
    if tab == "Sidecar":
        control_plane = workflow_state["control_plane"]
        return "\n".join(
            [
                f"selected_candidate_label: {workflow_state['selection']['selected_candidate_label']}",
                workflow_state["commands"]["sidecar_stage"],
                workflow_state["commands"]["service_restart"],
                workflow_state["commands"]["service_validate"],
                workflow_state["commands"]["service_snippet"],
                _render_operation_status_line(control_plane, "sidecar_stage"),
                _render_operation_status_line(control_plane, "service_restart"),
                _render_operation_status_line(control_plane, "service_validate"),
                f"sidecar_stage_available: {workflow_state['operation_availability']['sidecar_stage_available']}",
                f"service_validate_available: {workflow_state['operation_availability']['service_validate_available']}",
                f"service_active: {control_plane['sidecar_state']['service_active']}",
                f"service_enabled: {control_plane['sidecar_state']['service_enabled']}",
                f"socks_tcp_connect: {control_plane['sidecar_state']['socks_tcp_connect']}",
                f"last_validation: {control_plane['sidecar_state']['last_validation']}",
                f"warning: {control_plane['sidecar_state']['warning']}",
                f"next_recommended_action: {workflow_state['dashboard']['next_recommended_action']}",
                "production_boundary: Production Xray/XrayR/x-ui are not modified automatically.",
            ]
        )
    if tab == "Pool":
        control_plane = workflow_state["control_plane"]
        return "\n".join(
            [
                f"plan_exists: {control_plane['pool_state']['plan_exists']}",
                f"pool_stage: {workflow_state['commands']['pool_stage']}",
                f"port_warning: {control_plane['pool_state']['port_warning']}",
                f"pool_rows: {control_plane['pool_state']['rows']}",
            ]
        )
    if tab == "Troubleshooting":
        return "\n".join(
            [
                "artifact check",
                "select list",
                "artifact explain-probe --protocol hysteria2",
                "artifact explain-probe --error-category ssl_eof",
                "artifact explain-probe --label-regex 美国 --error-category ssl_eof",
                "Hysteria2 remains experimental and disabled by default.",
                "Persistent ssl_eof usually means transport-layer failure, not Scholar blocking.",
                "Artifact mismatch: rerun fetch + probe and do not select from stale passed artifacts.",
            ]
        )
    if tab == "Snippets":
        return "\n".join(
            [
                workflow_state["snippets"]["warning"],
                workflow_state["commands"]["service_snippet"],
                f"snippet_available: {workflow_state['operation_availability']['snippet_available']}",
            ]
        )
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
        from textual.widgets import Footer
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
            yield Footer()

        def _refresh_all_tabs(self) -> None:
            _refresh_tab_bodies(
                list(controller.workflow_state["tabs"]),
                controller.workflow_state,
                lambda body_id, text: self.query_one(f"#{body_id}", Static).update(text),
            )

        def _run_tui_action(self, description: str, func: Callable[[], str | None]) -> None:
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
            self._run_tui_action(
                "Show config diff",
                lambda: controller.workflow_state["config_form"]["redacted_diff"]
                or controller.workflow_state["config_editor"]["redacted_diff"]
                or "No pending redacted config diff is available.",
            )

        def action_cursor_down(self) -> None:
            def _move_down() -> str:
                if controller.selection.active_tab == "Config":
                    controller.move_config_field(1)
                else:
                    controller.move_candidate(1)
                return "Selection moved down."

            self._run_tui_action("Move selection", _move_down)

        def action_cursor_up(self) -> None:
            def _move_up() -> str:
                if controller.selection.active_tab == "Config":
                    controller.move_config_field(-1)
                else:
                    controller.move_candidate(-1)
                return "Selection moved up."

            self._run_tui_action("Move selection", _move_up)

        def action_confirm_selected(self) -> None:
            self._run_tui_action("Inspect selected candidate", lambda: str(controller.preview_selected_candidate()))

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
                lambda: "Keys: q quit | r reload | j/k move | enter inspect | esc cancel | e edit field | d show diff | s save | u undo | f fetch | p probe | a artifact-check | c choose | g stage | v validate | x snapshot | z rollback | ? help",
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
