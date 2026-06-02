"""Optional workflow-oriented Textual TUI entry point and helpers."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scholar_outbound_manager.selection import build_selected_candidate_artifact
from scholar_outbound_manager.selection import load_candidate_payload
from scholar_outbound_manager.selection import select_candidate_by_index
from scholar_outbound_manager.selection import write_selected_candidate_artifact
from scholar_outbound_manager.tui.action_runner import ActionResult
from scholar_outbound_manager.tui.action_runner import ActionRunOptions
from scholar_outbound_manager.tui.action_runner import ActionRunner
from scholar_outbound_manager.tui.action_runner import FakeActionRunner
from scholar_outbound_manager.tui.action_runner import SubprocessActionRunner
from scholar_outbound_manager.tui.action_runner import append_action_journal
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_SESSION_PATH
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ACTION_JOURNAL_PATH
from scholar_outbound_manager.tui.control_plane import ControlPlaneState
from scholar_outbound_manager.tui.control_plane import control_plane_state_to_dict
from scholar_outbound_manager.tui.control_plane import load_control_plane_state
from scholar_outbound_manager.tui.screens import build_ascii_tab_strip
from scholar_outbound_manager.tui.state import build_session_state
from scholar_outbound_manager.tui.state import write_session_state
from scholar_outbound_manager.tui.workflow import MAIN_TABS


TUI_KEY_BINDINGS: tuple[tuple[str, str, str], ...] = (
    ("q", "quit", "Quit"),
    ("r", "reload_state", "Reload State"),
    ("s", "save_draft", "Save Draft"),
    ("u", "undo_save", "Undo Save"),
    ("f", "run_fetch", "Run Fetch"),
    ("p", "run_probe", "Run Probe"),
    ("a", "run_artifact_check", "Run Artifact Check"),
    ("c", "run_select", "Run Select"),
    ("g", "run_stage_sidecar", "Run Stage Sidecar"),
    ("v", "run_validate_sidecar", "Run Validate"),
    ("?", "show_help", "Help"),
)


@dataclass(slots=True)
class WorkflowActionState:
    pending_confirmation: str | None
    last_result: ActionResult | None
    status_message: str | None


class WorkflowController:
    """Pure-Python workflow controller with confirmation and runner integration."""

    def __init__(
        self,
        *,
        loader_kwargs: dict[str, object],
        runner: ActionRunner | None = None,
        action_journal_path: str = DEFAULT_TUI_ACTION_JOURNAL_PATH,
    ) -> None:
        self._loader_kwargs = dict(loader_kwargs)
        self._runner = SubprocessActionRunner() if runner is None else runner
        self._action_journal_path = action_journal_path
        self.workflow_state = load_workflow_state(**self._loader_kwargs)
        self.action_state = WorkflowActionState(pending_confirmation=None, last_result=None, status_message=None)

    def reload(self) -> None:
        self.workflow_state = load_workflow_state(**self._loader_kwargs)
        self.action_state.pending_confirmation = None
        self.action_state.status_message = "Workflow state reloaded."

    def handle_operation(self, operation_key: str) -> str:
        spec = self._find_operation(operation_key)
        if spec is None:
            self.action_state.status_message = f"Unknown operation: {operation_key}"
            return str(self.action_state.status_message)
        if spec.requires_confirmation and self.action_state.pending_confirmation != operation_key:
            self.action_state.pending_confirmation = operation_key
            self.action_state.status_message = f"Pending confirmation: press the same key again to run {spec.title}."
            return str(self.action_state.status_message)
        self.action_state.pending_confirmation = None
        result = self._runner.run(spec, self._build_run_options(spec))
        append_action_journal(result, journal_path=self._action_journal_path)
        self.action_state.last_result = result
        self.workflow_state = load_workflow_state(**self._loader_kwargs)
        self.action_state.status_message = self._summarize_result(result)
        return str(self.action_state.status_message)

    def _find_operation(self, operation_key: str):
        operations = self.workflow_state["control_plane"]["command_state"]["operations"]
        for operation in operations:
            if operation["key"] == operation_key:
                return self._dict_to_operation(operation)
        return None

    def _build_run_options(self, spec) -> ActionRunOptions:
        return ActionRunOptions(
            cwd=None,
            timeout_seconds=30.0,
            allow_network=spec.network_access,
            allow_systemd=spec.systemd_access,
            allow_sensitive_artifact_write=spec.sensitive_outputs,
        )

    def _summarize_result(self, result: ActionResult) -> str:
        stderr_tail = result.redacted_stderr[-160:] if result.redacted_stderr else ""
        if result.succeeded:
            return result.summary
        if stderr_tail:
            return f"{result.summary} Next step: inspect stderr tail: {stderr_tail}"
        return f"{result.summary} Next step: review the action journal and current control-plane state."

    def _dict_to_operation(self, payload: dict[str, object]):
        from scholar_outbound_manager.tui.commands import OperationSpec

        return OperationSpec(
            key=str(payload["key"]),
            title=str(payload["title"]),
            command=[str(part) for part in payload["command"]],
            requires_confirmation=bool(payload["requires_confirmation"]),
            network_access=bool(payload["network_access"]),
            systemd_access=bool(payload["systemd_access"]),
            sensitive_outputs=bool(payload["sensitive_outputs"]),
            expected_artifacts=[str(part) for part in payload["expected_artifacts"]],
            success_exit_codes=tuple(int(code) for code in payload.get("success_exit_codes", (0,))),
            description=str(payload.get("description") or ""),
            risk_note=None if payload.get("risk_note") is None else str(payload.get("risk_note")),
        )


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


def render_tab_text(tab: str, workflow_state: dict[str, object]) -> str:
    """Render one tab body from the redacted workflow state."""
    if tab == "Dashboard":
        dashboard = workflow_state["dashboard"]
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
                f"next_recommended_action: {dashboard['next_recommended_action']}",
                f"last_action: {dashboard['last_action']}",
            ]
        )
    if tab == "Config":
        editor = workflow_state["config_editor"]
        return "\n".join(
            [
                "Step 1: Config",
                f"config exists: {workflow_state['preflight']['config_exists']}",
                f"config valid: {workflow_state['preflight']['config_valid']}",
                f"validation errors: {workflow_state['preflight']['config_validation_errors']}",
                f"undo_available: {editor['undo_available']}",
                "Preview:",
                editor["redacted_diff"] or editor["redacted_preview"],
                "Hints: q quit | r reload | f fetch | p probe | a artifact-check | c select | g stage | v validate | s save | u undo | ? help",
            ]
        )
    if tab == "Fetch & Probe":
        return "\n".join(
            [
                workflow_state["warnings"][0],
                f"fetch: {workflow_state['commands']['fetch']}",
                f"probe: {workflow_state['commands']['probe']}",
                f"fetch_available: {workflow_state['operation_availability']['fetch_available']}",
                f"probe_available: {workflow_state['operation_availability']['probe_available']}",
            ]
        )
    if tab == "Artifacts":
        return "\n".join(
            [
                f"artifact check: {workflow_state['commands']['artifact_check']}",
                f"artifact result: {workflow_state['artifacts']['artifact_check']}",
                f"artifact_check_available: {workflow_state['operation_availability']['artifact_check_available']}",
                f"candidates_hash: {workflow_state['artifacts']['candidates_hash']}",
                f"probe_summary_hash: {workflow_state['artifacts']['probe_summary_hash']}",
                f"passed_candidates_hash: {workflow_state['artifacts']['passed_candidates_hash']}",
                f"warnings: {workflow_state['artifacts']['warnings']}",
            ]
        )
    if tab == "Selection":
        return "\n".join(
            [
                workflow_state["selection"]["sensitive_notice"],
                f"selected_candidate_id: {workflow_state['selection']['selected_candidate_id']}",
                f"selected_candidate_label: {workflow_state['selection']['selected_candidate_label']}",
                f"selected_region_hint: {workflow_state['selection']['selected_region_hint']}",
                f"preferred_region_hint: {workflow_state['selection']['preferred_region_hint']}",
                f"selection_method: {workflow_state['selection']['selection_method']}",
                f"selection_reason: {workflow_state['selection']['selection_reason']}",
                f"select preview: {workflow_state['commands']['select']}",
                f"select_available: {workflow_state['operation_availability']['select_available']}",
            ]
        )
    if tab == "Sidecar":
        control_plane = workflow_state["control_plane"]
        return "\n".join(
            [
                workflow_state["commands"]["sidecar_stage"],
                workflow_state["commands"]["service_restart"],
                workflow_state["commands"]["service_validate"],
                f"sidecar_stage_available: {workflow_state['operation_availability']['sidecar_stage_available']}",
                f"service_validate_available: {workflow_state['operation_availability']['service_validate_available']}",
                f"service_active: {control_plane['sidecar_state']['service_active']}",
                f"service_enabled: {control_plane['sidecar_state']['service_enabled']}",
                f"socks_tcp_connect: {control_plane['sidecar_state']['socks_tcp_connect']}",
                f"last_validation: {control_plane['sidecar_state']['last_validation']}",
                f"warning: {control_plane['sidecar_state']['warning']}",
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
                "artifact explain-probe --label-regex 美国 --error-category ssl_eof",
                "Hysteria2 remains experimental and disabled by default.",
                "Persistent ssl_eof usually means transport-layer failure, not Scholar blocking.",
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
                            yield Static(render_tab_text(tab_spec["title"], controller.workflow_state))
            yield Footer()

        def action_reload_state(self) -> None:
            controller.reload()
            self.notify(str(controller.action_state.status_message))

        def action_save_draft(self) -> None:
            self.notify("Config save remains an explicit future action in this phase.")

        def action_undo_save(self) -> None:
            self.notify("Undo remains an explicit future action in this phase.")

        def action_run_fetch(self) -> None:
            self.notify(controller.handle_operation("fetch"))

        def action_run_probe(self) -> None:
            self.notify(controller.handle_operation("probe"))

        def action_run_artifact_check(self) -> None:
            self.notify(controller.handle_operation("artifact_check"))

        def action_run_select(self) -> None:
            self.notify(controller.handle_operation("select"))

        def action_run_stage_sidecar(self) -> None:
            self.notify(controller.handle_operation("sidecar_stage"))

        def action_run_validate_sidecar(self) -> None:
            self.notify(controller.handle_operation("service_validate"))

        def action_show_help(self) -> None:
            self.notify("Keys: q quit | r reload | f fetch | p probe | a artifact-check | c select | g stage | v validate | s save | u undo | ? help")

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
