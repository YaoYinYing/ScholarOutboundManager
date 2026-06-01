"""Optional workflow-oriented Textual TUI entry point and helpers."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

from scholar_outbound_manager.selection import build_candidate_catalog
from scholar_outbound_manager.selection import build_selected_candidate_artifact
from scholar_outbound_manager.selection import load_candidate_payload
from scholar_outbound_manager.selection import load_selected_candidate_artifact
from scholar_outbound_manager.selection import select_candidate_by_index
from scholar_outbound_manager.selection import write_selected_candidate_artifact
from scholar_outbound_manager.selection_policy import SelectionPolicyOptions
from scholar_outbound_manager.selection_policy import select_candidate_with_policy
from scholar_outbound_manager.state.artifact_lineage import check_artifact_consistency
from scholar_outbound_manager.tui.commands import build_artifact_check_command
from scholar_outbound_manager.tui.commands import build_fetch_command
from scholar_outbound_manager.tui.commands import build_pool_stage_command
from scholar_outbound_manager.tui.commands import build_probe_command
from scholar_outbound_manager.tui.commands import build_service_stage_command
from scholar_outbound_manager.tui.commands import build_snippet_warning
from scholar_outbound_manager.tui.commands import preview_command
from scholar_outbound_manager.tui.screens import build_ascii_tab_strip
from scholar_outbound_manager.tui.state import DEFAULT_TUI_SESSION_PATH
from scholar_outbound_manager.tui.state import build_session_state
from scholar_outbound_manager.tui.state import load_session_state
from scholar_outbound_manager.tui.state import session_state_to_dict
from scholar_outbound_manager.tui.state import write_session_state
from scholar_outbound_manager.tui.view_model import build_candidate_table_rows
from scholar_outbound_manager.tui.view_model import build_dashboard_model
from scholar_outbound_manager.tui.view_model import build_snippet_view
from scholar_outbound_manager.tui.workflow import MAIN_TABS
from scholar_outbound_manager.tui.workflow import build_workflow_steps


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
    payload = load_candidate_payload(candidates_path)
    entries = build_candidate_catalog(payload)
    rows = build_candidate_table_rows(entries)
    _, _, decision = select_candidate_with_policy(
        payload,
        SelectionPolicyOptions(
            strategy=strategy,
            geo_cache_path=geo_cache_path,
            host_geo_path=host_geo_path,
            prefer_geo=prefer_geo,
            preferred_region_hint=preferred_region_hint,
            prefer_region_hint=preferred_region_hint is not None,
            fallback_to_first=True,
        ),
    )
    return {
        "candidates_path": str(candidates_path),
        "output_path": str(output_path),
        "rows": rows,
        "selected_index": decision.selected_index,
        "selected_candidate_id": decision.selected_candidate_id,
        "selection_method": decision.method,
        "selection_reason": decision.reason,
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
    output_path: str = "state_data/selected_candidate.json",
    strategy: str = "auto",
    geo_cache_path: str = "state_data/geo/candidate_geo_cache.json",
    host_geo_path: str = "state_data/geo/host_geo.json",
    prefer_geo: bool = True,
    preferred_region_hint: str | None = None,
) -> dict[str, object]:
    """Build a workflow-oriented, redacted TUI state model."""
    existing_session = _try_load_session(session_path)
    candidate_rows: list[dict[str, object]] = []
    selected_candidate_id: str | None = None
    selected_candidate_label: str | None = None

    effective_candidates_path = passed_candidates_path if Path(passed_candidates_path).exists() else candidates_path
    if Path(effective_candidates_path).exists():
        try:
            dashboard_state = load_dashboard_state(
                candidates_path=effective_candidates_path,
                output_path=output_path,
                strategy=strategy,
                geo_cache_path=geo_cache_path,
                host_geo_path=host_geo_path,
                prefer_geo=prefer_geo,
                preferred_region_hint=preferred_region_hint,
            )
            candidate_rows = list(dashboard_state["rows"])
            selected_candidate_id = dashboard_state["selected_candidate_id"]
            if candidate_rows:
                selected_row = candidate_rows[int(dashboard_state["selected_index"])]
                selected_candidate_label = str(selected_row.get("label") or "")
        except Exception:
            candidate_rows = []

    if Path(selected_candidate_path).exists():
        try:
            selected_record = load_selected_candidate_artifact(selected_candidate_path)
            selected_candidate_id = selected_record.candidate_id
            selected_candidate_label = selected_record.candidate.raw_name or selected_candidate_label
        except Exception:
            pass

    artifact_check_result = None
    if Path(candidates_path).exists() and Path(probe_summary_path).exists() and Path(passed_candidates_path).exists():
        artifact_check_result = check_artifact_consistency(
            candidates_path=candidates_path,
            probe_summary_path=probe_summary_path,
            passed_candidates_path=passed_candidates_path,
        )

    session_state = build_session_state(
        updated_at=_utc_now_iso8601(),
        workspace=os.getcwd(),
        last_step=None if existing_session is None else existing_session.last_step,
        paths={
            "config": config_path,
            "candidates": candidates_path,
            "probe_summary": probe_summary_path,
            "passed_candidates": passed_candidates_path,
            "selected_candidate": selected_candidate_path,
            "pool_plan": pool_plan_path,
        },
        last_results={} if existing_session is None else existing_session.last_results,
    )

    dashboard = build_dashboard_model(
        {
            "repo_status": "dirty" if _current_repo_dirty() else "clean",
            "current_git_commit": _current_git_commit(),
            "venv_detected": os.environ.get("VIRTUAL_ENV") is not None,
            "config_exists": Path(config_path).exists(),
            "xray_binary_exists": Path(".runtime/xray/xray").exists(),
            "service_active": None,
            "service_enabled": None,
            "socks_tcp_connect": None,
            "last_scholar_validation": None if artifact_check_result is None else artifact_check_result.get("overall_consistent"),
            "candidate_count": len(candidate_rows),
            "passed_count": _count_passed(candidate_rows),
            "selected_candidate_label": selected_candidate_label,
            "current_sidecar_port": 19080,
        }
    )

    wizard_steps = build_workflow_steps(artifact_check_result=artifact_check_result)
    snippets_view = build_snippet_view([], warning=build_snippet_warning())
    fetch_command = build_fetch_command(config_path=config_path, output_path=candidates_path)
    probe_command = build_probe_command(
        config_path=config_path,
        candidates_path=candidates_path,
        summary_output=probe_summary_path,
        passed_candidates_output=passed_candidates_path,
    )

    state = {
        "tabs": list(MAIN_TABS),
        "tab_strip": build_ascii_tab_strip(),
        "dashboard": dashboard,
        "wizard_steps": [
            {
                "key": step.key,
                "title": step.title,
                "allow_continue": step.allow_continue,
                "warning": step.warning,
                "blocking_reason": step.blocking_reason,
            }
            for step in wizard_steps
        ],
        "paths": session_state.paths,
        "session": session_state_to_dict(session_state),
        "artifacts": {
            "candidates_exists": Path(candidates_path).exists(),
            "probe_summary_exists": Path(probe_summary_path).exists(),
            "passed_candidates_exists": Path(passed_candidates_path).exists(),
            "selected_candidate_exists": Path(selected_candidate_path).exists(),
            "pool_plan_exists": Path(pool_plan_path).exists(),
            "artifact_check": artifact_check_result,
        },
        "preflight": {
            "config_exists": Path(config_path).exists(),
            "xray_binary_exists": Path(".runtime/xray/xray").exists(),
            "probe_allow_network_probe": None,
            "routing_fail_closed": None,
        },
        "selection": {
            "rows": candidate_rows,
            "selected_candidate_id": selected_candidate_id,
            "sensitive_notice": "selected_candidate.json is sensitive and will not be displayed.",
        },
        "commands": {
            "fetch": preview_command(fetch_command),
            "probe": preview_command(probe_command),
            "artifact_check": preview_command(
                build_artifact_check_command(
                    candidates_path=candidates_path,
                    probe_summary_path=probe_summary_path,
                    passed_candidates_path=passed_candidates_path,
                )
            ),
            "sidecar_stage": preview_command(
                build_service_stage_command(
                    config_path=config_path,
                    selected_candidate_path=selected_candidate_path,
                )
            ),
            "pool_stage": preview_command(
                build_pool_stage_command(
                    config_path=config_path,
                    candidates_path=passed_candidates_path,
                    plan_path=pool_plan_path,
                )
            ),
        },
        "warnings": [
            "This will perform live network fetch/probe from this VPS.",
            build_snippet_warning(),
        ],
        "snippets": snippets_view,
    }
    return state


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

    workflow_state = load_workflow_state(
        config_path=args.config,
        candidates_path=args.candidates,
        probe_summary_path=args.probe_summary,
        passed_candidates_path=args.passed_candidates,
        selected_candidate_path=args.selected_candidate,
        pool_plan_path=args.pool_plan,
        session_path=args.session,
        output_path=args.output,
        strategy=args.strategy,
        geo_cache_path=args.geo_cache,
        host_geo_path=args.host_geo,
        prefer_geo=args.prefer_geo,
        preferred_region_hint=args.preferred_region_hint,
    )
    write_session_state(args.session, build_session_state(updated_at=_utc_now_iso8601(), workspace=os.getcwd(), paths=workflow_state["paths"], last_results=workflow_state["session"]["last_results"]))

    class ScholarOutboundWorkflowApp(App[None]):
        """Minimal tabbed workflow-oriented TUI."""

        def compose(self) -> ComposeResult:
            yield Header()
            with TabbedContent(initial="Dashboard"):
                for tab in workflow_state["tabs"]:
                    with TabPane(tab, id=tab):
                        with Vertical():
                            yield Static(self._tab_text(tab))
            yield Footer()

        def _tab_text(self, tab: str) -> str:
            if tab == "Dashboard":
                dashboard = workflow_state["dashboard"]
                return "\n".join(
                    [
                        "Workflow-oriented TUI",
                        workflow_state["tab_strip"],
                        f"repo_status: {dashboard['repo_status']}",
                        f"current_git_commit: {dashboard['current_git_commit']}",
                        f"candidate_count: {dashboard['candidate_count']}",
                        f"passed_count: {dashboard['passed_count']}",
                        f"selected_candidate_label: {dashboard['selected_candidate_label']}",
                    ]
                )
            if tab == "Preflight":
                return "\n".join(
                    [
                        "Step 1: Preflight",
                        f"config exists: {workflow_state['preflight']['config_exists']}",
                        f"xray binary exists: {workflow_state['preflight']['xray_binary_exists']}",
                        f"command preview: {workflow_state['commands']['fetch']}",
                    ]
                )
            if tab == "Fetch & Probe":
                return "\n".join(
                    [
                        workflow_state["warnings"][0],
                        f"fetch: {workflow_state['commands']['fetch']}",
                        f"probe: {workflow_state['commands']['probe']}",
                    ]
                )
            if tab == "Artifacts":
                return "\n".join(
                    [
                        f"artifact check: {workflow_state['commands']['artifact_check']}",
                        f"artifact result: {workflow_state['artifacts']['artifact_check']}",
                    ]
                )
            if tab == "Selection":
                return workflow_state["selection"]["sensitive_notice"]
            if tab == "Sidecar":
                return workflow_state["commands"]["sidecar_stage"]
            if tab == "Pool":
                return workflow_state["commands"]["pool_stage"]
            if tab == "Troubleshooting":
                return "Meaning, safe command, expected result, and next action belong here."
            return workflow_state["snippets"]["warning"]

    ScholarOutboundWorkflowApp().run()
    return 0


def _try_load_session(path: str | Path):
    try:
        return load_session_state(path)
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _count_passed(rows: list[dict[str, object]]) -> int:
    return sum(1 for row in rows if row.get("passed") is True)


def _current_git_commit() -> str | None:
    import subprocess

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _current_repo_dirty() -> bool:
    import subprocess

    try:
        completed = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
    except OSError:
        return False
    return bool(completed.stdout.strip())


def _utc_now_iso8601() -> str:
    from datetime import datetime
    from datetime import timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
