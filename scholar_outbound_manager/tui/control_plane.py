"""Textual-independent TUI control-plane state and operation models."""

from __future__ import annotations

import os
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path

from scholar_outbound_manager.config import ConfigError
from scholar_outbound_manager.config import load_config
from scholar_outbound_manager.tui.artifact_rollback import list_artifact_snapshots
from scholar_outbound_manager.selection import build_candidate_catalog
from scholar_outbound_manager.selection import load_candidate_payload
from scholar_outbound_manager.selection import load_selected_candidate_artifact
from scholar_outbound_manager.selection_policy import SelectionPolicyOptions
from scholar_outbound_manager.selection_policy import select_candidate_with_policy
from scholar_outbound_manager.state.artifact_lineage import check_artifact_consistency
from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.tui.action_runner import load_last_action
from scholar_outbound_manager.tui.commands import OperationSpec
from scholar_outbound_manager.tui.commands import build_artifact_check_command
from scholar_outbound_manager.tui.commands import build_fetch_command
from scholar_outbound_manager.tui.commands import build_pool_stage_command
from scholar_outbound_manager.tui.commands import build_probe_command
from scholar_outbound_manager.tui.commands import build_select_command
from scholar_outbound_manager.tui.commands import build_service_restart_command
from scholar_outbound_manager.tui.commands import build_service_snippet_command
from scholar_outbound_manager.tui.commands import build_service_stage_command
from scholar_outbound_manager.tui.commands import build_service_validate_command
from scholar_outbound_manager.tui.commands import build_snippet_warning
from scholar_outbound_manager.tui.commands import preview_command
from scholar_outbound_manager.tui.config_form import ConfigFormState
from scholar_outbound_manager.tui.config_form import build_config_form_state
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ACTION_JOURNAL_PATH
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ARTIFACT_SNAPSHOT_ROOT
from scholar_outbound_manager.tui.config_editor import has_undo_journal_entry
from scholar_outbound_manager.tui.config_editor import load_config_draft
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_SESSION_PATH
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_UNDO_JOURNAL_PATH
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.state import build_session_state
from scholar_outbound_manager.tui.state import load_session_state
from scholar_outbound_manager.tui.view_model import build_candidate_table_rows
from scholar_outbound_manager.tui.view_model import build_pool_plan_rows
from scholar_outbound_manager.tui.view_model import build_snippet_view
from scholar_outbound_manager.tui.view_model import redact_text
from scholar_outbound_manager.tui.workflow import MAIN_TABS
from scholar_outbound_manager.tui.workflow import build_workflow_steps


UNKNOWN_STATE = "unknown"


@dataclass(slots=True)
class ConfigState:
    exists: bool
    valid: bool
    dirty: bool
    undo_available: bool
    redacted_preview: str
    redacted_diff: str
    validation_errors: list[str]
    enabled_subscription_count: int | None
    probe_allow_network_probe: bool | None
    routing_mode: str | None
    routing_fail_closed: bool | None


@dataclass(slots=True)
class ArtifactState:
    candidates_exists: bool
    probe_summary_exists: bool
    passed_candidates_exists: bool
    selected_candidate_exists: bool
    artifact_check: dict[str, object] | None
    overall_consistent: bool | None
    warnings: list[str]
    candidates_hash: str | None
    probe_summary_hash: str | None
    passed_candidates_hash: str | None
    snapshot_count: int
    latest_snapshot_id: str | None
    latest_snapshot_reason: str | None


@dataclass(slots=True)
class SelectionState:
    rows: list[dict[str, object]]
    selected_candidate_id: str | None
    selected_candidate_label: str | None
    selected_region_hint: str | None
    selection_method: str | None
    selection_reason: str | None
    preferred_region_hint: str | None


@dataclass(slots=True)
class WorkflowModelState:
    steps: list[dict[str, object]]
    blocking_reason: str | None
    next_recommended_action: str


@dataclass(slots=True)
class CommandState:
    fetch_command_preview: str
    probe_command_preview: str
    artifact_check_command_preview: str
    select_command_preview: str
    sidecar_stage_command_preview: str
    service_restart_command_preview: str
    service_validate_command_preview: str
    snippet_command_preview: str
    pool_stage_command_preview: str
    operations: list[OperationSpec]


@dataclass(slots=True)
class OperationAvailability:
    fetch_available: bool
    probe_available: bool
    artifact_check_available: bool
    select_available: bool
    sidecar_stage_available: bool
    service_restart_available: bool
    service_validate_available: bool
    snippet_available: bool
    config_save_available: bool
    config_undo_available: bool
    artifact_snapshot_available: bool
    artifact_rollback_available: bool


@dataclass(slots=True)
class SidecarState:
    service_active: str
    service_enabled: str
    socks_tcp_connect: str
    last_validation: str
    warning: str | None
    xray_binary_exists: bool
    xray_binary_path: str | None


@dataclass(slots=True)
class PoolState:
    plan_exists: bool
    rows: list[dict[str, object]]
    port_warning: str | None


@dataclass(slots=True)
class LastActionState:
    key: str | None
    title: str | None
    summary: str | None
    exit_code: int | None
    succeeded: bool | None
    redacted_stdout_tail: str
    redacted_stderr_tail: str
    warnings: list[str]
    snapshot_id: str | None = None
    rollback_hint: str | None = None


@dataclass(slots=True)
class ControlPlaneState:
    workspace: str
    tabs: list[str]
    config_state: ConfigState
    config_form_state: ConfigFormState
    artifact_state: ArtifactState
    selection_state: SelectionState
    workflow_state: WorkflowModelState
    command_state: CommandState
    operation_availability: OperationAvailability
    sidecar_state: SidecarState
    pool_state: PoolState
    warnings: list[str]
    last_action: LastActionState | None
    session: dict[str, object]
    snippets: dict[str, object]
    repo_status: str
    current_git_commit: str | None
    venv_detected: bool
    current_sidecar_port: int


def load_control_plane_state(
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
) -> ControlPlaneState:
    """Build one review-safe control plane state from the local workspace."""
    resolved_paths = resolve_user_data_paths(config_path)
    if candidates_path == "candidates.json":
        candidates_path = str(resolved_paths.candidates)
    if probe_summary_path == "state_data/probe_summary.json":
        probe_summary_path = str(resolved_paths.probe_summary)
    if passed_candidates_path == "state_data/passed_candidates.json":
        passed_candidates_path = str(resolved_paths.passed_candidates)
    if selected_candidate_path == "state_data/selected_candidate.json":
        selected_candidate_path = str(resolved_paths.selected_candidate)
    if pool_plan_path == "state_data/sidecar_pool_plan.json":
        pool_plan_path = str(resolved_paths.pool_plan)
    if session_path == DEFAULT_TUI_SESSION_PATH:
        session_path = str(resolved_paths.session)
    if action_journal_path == DEFAULT_TUI_ACTION_JOURNAL_PATH:
        action_journal_path = str(resolved_paths.action_journal)
    if snapshot_root == DEFAULT_TUI_ARTIFACT_SNAPSHOT_ROOT:
        snapshot_root = str(resolved_paths.snapshot_root)
    undo_journal_path = str(resolved_paths.undo_journal)

    existing_session = _try_load_session(session_path)
    config_draft = None
    config_exists = Path(config_path).exists()
    if config_exists:
        try:
            config_draft = load_config_draft(config_path)
        except Exception:
            config_draft = None
    try:
        config_form_state = build_config_form_state(config_path)
    except Exception:
        config_form_state = ConfigFormState(fields=[], dirty=False, valid=False, validation_errors=[], redacted_diff="")
    undo_available = has_undo_journal_entry(config_path=config_path, undo_journal_path=undo_journal_path)

    parsed_config = None
    if config_draft is not None and config_draft.parsed_ok:
        try:
            parsed_config = load_config(config_path)
        except (ConfigError, OSError, ValueError):
            parsed_config = None

    effective_candidates_path = passed_candidates_path if Path(passed_candidates_path).exists() else candidates_path
    rows: list[dict[str, object]] = []
    selected_candidate_id: str | None = None
    selected_candidate_label: str | None = None
    selected_region_hint: str | None = None
    selection_method: str | None = None
    selection_reason: str | None = None
    if Path(effective_candidates_path).exists():
        try:
            payload = load_candidate_payload(effective_candidates_path)
            entries = build_candidate_catalog(payload)
            rows = build_candidate_table_rows(entries)
            selection_options = SelectionPolicyOptions(
                selected_candidate_path=selected_candidate_path if Path(selected_candidate_path).exists() else None,
                strategy=strategy,
                geo_cache_path=geo_cache_path,
                host_geo_path=host_geo_path,
                prefer_geo=prefer_geo,
                preferred_region_hint=preferred_region_hint,
                prefer_region_hint=preferred_region_hint is not None,
                fallback_to_first=True,
            )
            try:
                _, _, decision = select_candidate_with_policy(payload, selection_options)
            except Exception:
                if selection_options.selected_candidate_path is None:
                    raise
                selection_options = SelectionPolicyOptions(
                    strategy=strategy,
                    geo_cache_path=geo_cache_path,
                    host_geo_path=host_geo_path,
                    prefer_geo=prefer_geo,
                    preferred_region_hint=preferred_region_hint,
                    prefer_region_hint=preferred_region_hint is not None,
                    fallback_to_first=True,
                )
                _, _, decision = select_candidate_with_policy(payload, selection_options)
            selected_candidate_id = decision.selected_candidate_id
            selection_method = decision.method
            selection_reason = decision.reason
            if rows:
                selected_row = rows[int(decision.selected_index)]
                selected_candidate_label = str(selected_row.get("label") or "")
                selected_region_hint = _coerce_optional_str(selected_row.get("region"))
        except Exception:
            rows = []

    if Path(selected_candidate_path).exists() and selected_candidate_label is None:
        try:
            selected_record = load_selected_candidate_artifact(selected_candidate_path)
            selected_candidate_id = selected_record.candidate_id
            selected_candidate_label = redact_text(str(selected_record.candidate.raw_name or ""))
        except Exception:
            pass

    artifact_check = None
    if Path(candidates_path).exists() and Path(probe_summary_path).exists() and Path(passed_candidates_path).exists():
        artifact_check = check_artifact_consistency(
            candidates_path=candidates_path,
            probe_summary_path=probe_summary_path,
            passed_candidates_path=passed_candidates_path,
        )
    overall_consistent = None if artifact_check is None else artifact_check.get("overall_consistent")
    warnings = [] if artifact_check is None else list(artifact_check.get("warnings") or [])
    snapshots = list_artifact_snapshots(snapshot_root)
    latest_snapshot = snapshots[0] if snapshots else None

    config_state = ConfigState(
        exists=config_exists,
        valid=False if config_draft is None else config_draft.parsed_ok,
        dirty=False if config_draft is None else config_draft.dirty,
        undo_available=undo_available,
        redacted_preview="" if config_draft is None else config_draft.redacted_preview,
        redacted_diff="" if config_draft is None else config_draft.diff_preview,
        validation_errors=[] if config_draft is None else list(config_draft.validation_errors),
        enabled_subscription_count=None if parsed_config is None else sum(1 for source in parsed_config.subscriptions if source.enabled),
        probe_allow_network_probe=None if parsed_config is None else parsed_config.probe.allow_network_probe,
        routing_mode=None if parsed_config is None else parsed_config.routing.mode,
        routing_fail_closed=None if parsed_config is None else parsed_config.routing.fail_closed,
    )
    artifact_state = ArtifactState(
        candidates_exists=Path(candidates_path).exists(),
        probe_summary_exists=Path(probe_summary_path).exists(),
        passed_candidates_exists=Path(passed_candidates_path).exists(),
        selected_candidate_exists=Path(selected_candidate_path).exists(),
        artifact_check=artifact_check,
        overall_consistent=overall_consistent,
        warnings=warnings,
        candidates_hash=_try_compute_artifact_hash(candidates_path),
        probe_summary_hash=_try_compute_artifact_hash(probe_summary_path),
        passed_candidates_hash=_try_compute_artifact_hash(passed_candidates_path),
        snapshot_count=len(snapshots),
        latest_snapshot_id=None if latest_snapshot is None else latest_snapshot.snapshot_id,
        latest_snapshot_reason=None if latest_snapshot is None else latest_snapshot.reason,
    )
    selection_state = SelectionState(
        rows=rows,
        selected_candidate_id=selected_candidate_id,
        selected_candidate_label=selected_candidate_label,
        selected_region_hint=selected_region_hint,
        selection_method=selection_method if rows else None,
        selection_reason=selection_reason if rows else None,
        preferred_region_hint=preferred_region_hint,
    )

    fetch_command = build_fetch_command(config_path=config_path, output_path=candidates_path)
    probe_command = build_probe_command(
        config_path=config_path,
        candidates_path=candidates_path,
        summary_output=probe_summary_path,
        passed_candidates_output=passed_candidates_path,
    )
    select_command = build_select_command(
        candidates_path=passed_candidates_path,
        candidate_index=0,
        output_path=selected_candidate_path,
    )
    artifact_check_command = build_artifact_check_command(
        candidates_path=candidates_path,
        probe_summary_path=probe_summary_path,
        passed_candidates_path=passed_candidates_path,
    )
    sidecar_stage_command = build_service_stage_command(
        config_path=config_path,
        selected_candidate_path=selected_candidate_path,
    )
    service_restart_command = build_service_restart_command()
    service_validate_command = build_service_validate_command()
    snippet_command = build_service_snippet_command()
    pool_stage_command = build_pool_stage_command(
        config_path=config_path,
        candidates_path=passed_candidates_path,
        plan_path=pool_plan_path,
    )
    command_state = CommandState(
        fetch_command_preview=preview_command(fetch_command),
        probe_command_preview=preview_command(probe_command),
        artifact_check_command_preview=preview_command(artifact_check_command),
        select_command_preview=preview_command(select_command),
        sidecar_stage_command_preview=preview_command(sidecar_stage_command),
        service_restart_command_preview=preview_command(service_restart_command),
        service_validate_command_preview=preview_command(service_validate_command),
        snippet_command_preview=preview_command(snippet_command),
        pool_stage_command_preview=preview_command(pool_stage_command),
        operations=[
            OperationSpec(
                key="fetch",
                title="Fetch Candidates",
                command=fetch_command,
                requires_confirmation=True,
                network_access=True,
                systemd_access=False,
                sensitive_outputs=True,
                expected_artifacts=[candidates_path],
                description="Download and parse subscription content into a local sensitive candidates artifact.",
                risk_note="Live network operation. Writes a sensitive local artifact.",
            ),
            OperationSpec(
                key="probe",
                title="Probe Candidates",
                command=probe_command,
                requires_confirmation=True,
                network_access=True,
                systemd_access=False,
                sensitive_outputs=True,
                expected_artifacts=[probe_summary_path, passed_candidates_path],
                description="Probe candidates through the managed runtime and persist redacted summary plus passed candidates.",
                risk_note="Live network operation. Writes sensitive passed-candidate artifacts.",
            ),
            OperationSpec(
                key="artifact_check",
                title="Check Artifact Lineage",
                command=artifact_check_command,
                requires_confirmation=False,
                network_access=False,
                systemd_access=False,
                sensitive_outputs=False,
                expected_artifacts=[],
                description="Check candidates, probe summary, and passed candidates for lineage consistency.",
                risk_note=None,
            ),
            OperationSpec(
                key="select",
                title="Select Candidate",
                command=select_command,
                requires_confirmation=True,
                network_access=False,
                systemd_access=False,
                sensitive_outputs=True,
                expected_artifacts=[selected_candidate_path],
                description="Write one sensitive selected-candidate artifact from the current selection policy output.",
                risk_note="Writes selected_candidate.json.",
            ),
            OperationSpec(
                key="sidecar_stage",
                title="Stage Sidecar",
                command=sidecar_stage_command,
                requires_confirmation=True,
                network_access=False,
                systemd_access=False,
                sensitive_outputs=True,
                expected_artifacts=[selected_candidate_path],
                description="Prepare the managed sidecar runtime without touching production Xray or XrayR.",
                risk_note="Writes local runtime artifacts.",
            ),
            OperationSpec(
                key="pool_stage",
                title="Stage Sidecar Pool",
                command=pool_stage_command,
                requires_confirmation=True,
                network_access=False,
                systemd_access=False,
                sensitive_outputs=True,
                expected_artifacts=[pool_plan_path],
                description="Prepare the managed multi-port sidecar pool plan and runtime files.",
                risk_note="Writes local pool plan artifacts.",
            ),
            OperationSpec(
                key="service_restart",
                title="Restart Sidecar Service",
                command=service_restart_command,
                requires_confirmation=True,
                network_access=False,
                systemd_access=True,
                sensitive_outputs=False,
                expected_artifacts=[],
                description="Restart only the ScholarOutboundManager-managed sidecar service.",
                risk_note="Touches systemd for the managed sidecar service.",
            ),
            OperationSpec(
                key="service_validate",
                title="Validate Sidecar Service",
                command=service_validate_command,
                requires_confirmation=True,
                network_access=True,
                systemd_access=True,
                sensitive_outputs=False,
                expected_artifacts=[],
                description="Validate the managed sidecar service with explicit runtime and network checks.",
                risk_note="Touches systemd and performs live validation.",
            ),
            OperationSpec(
                key="snippet",
                title="Render Sidecar Snippet",
                command=snippet_command,
                requires_confirmation=False,
                network_access=False,
                systemd_access=False,
                sensitive_outputs=False,
                expected_artifacts=[],
                description="Render one copyable SOCKS outbound snippet for manual production integration.",
                risk_note=None,
            ),
        ],
    )

    steps = build_workflow_steps(artifact_check_result=artifact_check)
    blocking_reason = next((step.blocking_reason for step in steps if step.blocking_reason), None)
    last_action = _normalize_last_action(load_last_action(action_journal_path))
    workflow_state = WorkflowModelState(
        steps=[
            {
                "key": step.key,
                "title": step.title,
                "allow_continue": step.allow_continue,
                "warning": step.warning,
                "blocking_reason": step.blocking_reason,
            }
            for step in steps
        ],
        blocking_reason=blocking_reason,
        next_recommended_action=_next_recommended_action(
            config_state=config_state,
            config_form_state=config_form_state,
            artifact_state=artifact_state,
            selection_state=selection_state,
            selected_candidate_exists=Path(selected_candidate_path).exists(),
            last_action=last_action,
        ),
    )

    sidecar_state = SidecarState(
        service_active=UNKNOWN_STATE,
        service_enabled=UNKNOWN_STATE,
        socks_tcp_connect=UNKNOWN_STATE,
        last_validation=UNKNOWN_STATE,
        warning="Service state is not checked automatically; use the validate preview explicitly.",
        xray_binary_exists=Path(".runtime/xray/xray").exists(),
        xray_binary_path=None if parsed_config is None else parsed_config.xray.binary_path,
    )
    pool_state = PoolState(
        plan_exists=Path(pool_plan_path).exists(),
        rows=_load_pool_rows(pool_plan_path),
        port_warning="Pool stage preview is safe, but port checks are still explicit operations.",
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

    operation_availability = OperationAvailability(
        fetch_available=config_state.exists and config_state.valid,
        probe_available=config_state.exists and config_state.valid and artifact_state.candidates_exists,
        artifact_check_available=artifact_state.candidates_exists and artifact_state.passed_candidates_exists,
        select_available=artifact_state.passed_candidates_exists and bool(selection_state.rows),
        sidecar_stage_available=Path(selected_candidate_path).exists(),
        service_restart_available=Path(selected_candidate_path).exists(),
        service_validate_available=Path(selected_candidate_path).exists(),
        snippet_available=True,
        config_save_available=config_form_state.valid and config_state.exists,
        config_undo_available=undo_available,
        artifact_snapshot_available=True,
        artifact_rollback_available=latest_snapshot is not None,
    )
    return ControlPlaneState(
        workspace=os.getcwd(),
        tabs=list(MAIN_TABS),
        config_state=config_state,
        config_form_state=config_form_state,
        artifact_state=artifact_state,
        selection_state=selection_state,
        workflow_state=workflow_state,
        command_state=command_state,
        operation_availability=operation_availability,
        sidecar_state=sidecar_state,
        pool_state=pool_state,
        warnings=[
            "Fetch and probe previews correspond to live network operations when executed.",
            build_snippet_warning(),
            "Artifact snapshots and rollback restore local files only; they do not undo network or systemd side effects.",
        ],
        last_action=last_action,
        session=asdict(session_state),
        snippets=build_snippet_view([], warning=build_snippet_warning()),
        repo_status="dirty" if _current_repo_dirty() else "clean",
        current_git_commit=_current_git_commit(),
        venv_detected=os.environ.get("VIRTUAL_ENV") is not None,
        current_sidecar_port=19080,
    )


def control_plane_state_to_dict(state: ControlPlaneState) -> dict[str, object]:
    """Serialize one control plane state for TUI rendering tests."""
    return asdict(state)


def _next_recommended_action(
    *,
    config_state: ConfigState,
    config_form_state: ConfigFormState,
    artifact_state: ArtifactState,
    selection_state: SelectionState,
    selected_candidate_exists: bool,
    last_action: LastActionState | None,
) -> str:
    if not config_state.exists:
        return _with_reason(
            "Create or point the TUI at a local config.yaml before proceeding.",
            reason="Config file is missing.",
        )
    if not config_state.valid:
        return _with_reason(
            "Fix redacted config validation errors before any live fetch, probe, or sidecar step.",
            reason=_first_reason(config_state.validation_errors, fallback="Config validation is failing."),
        )
    if config_form_state.dirty:
        return _with_reason(
            "Review the structured config form diff and save config changes before continuing.",
            reason="Structured config changes are pending.",
        )
    if not artifact_state.candidates_exists:
        return _with_reason(
            "Review the fetch preview, then run fetch explicitly to create candidates.json.",
            reason="No local candidates artifact is present yet.",
        )
    if artifact_state.passed_candidates_exists and not selected_candidate_exists:
        return _with_reason(
            "Review the selection preview and choose one passed candidate before staging the sidecar.",
            reason="Passed candidates exist, but no selected candidate artifact has been written.",
        )
    if not artifact_state.probe_summary_exists or not artifact_state.passed_candidates_exists:
        return _with_reason(
            "Review the probe preview, then run probe explicitly to create passed candidates.",
            reason="Probe summary or passed-candidates artifacts are missing.",
        )
    if artifact_state.overall_consistent is False:
        return _with_reason(
            "Review artifact check output and rerun fetch or probe until lineage is consistent.",
            reason=_first_reason(artifact_state.warnings, fallback="Artifact lineage is inconsistent."),
        )
    if not selected_candidate_exists:
        return _with_reason(
            "Review sidecar stage and confirm runtime preparation before touching the managed service.",
            reason="The managed runtime has not been staged from a selected candidate yet.",
        )
    last_action_key = "" if last_action is None else str(last_action.key or "")
    if last_action_key != "sidecar_stage" and last_action_key != "service_validate":
        return _with_reason(
            "Review sidecar stage and confirm runtime preparation before touching the managed service.",
            reason="No successful sidecar stage action has been recorded in the current workflow.",
        )
    if last_action_key != "service_validate" or last_action.succeeded is not True:
        return _with_reason(
            "Review sidecar validate and confirm the managed service before exporting the snippet.",
            reason="The managed sidecar service has not been validated successfully yet.",
        )
    return _with_reason(
        "Review the snippet preview for manual production integration; production Xray and XrayR remain out of scope.",
        reason="Managed workflow prerequisites are satisfied.",
    )


def _with_reason(message: str, *, reason: str | None) -> str:
    if reason is None:
        return message
    return f"{message} Why: {reason}"


def _first_reason(values: list[str], *, fallback: str) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _load_pool_rows(path: str | Path) -> list[dict[str, object]]:
    plan_path = Path(path)
    if not plan_path.exists():
        return []
    try:
        import json

        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []
    safe_entries = [entry for entry in entries if isinstance(entry, dict)]
    return build_pool_plan_rows(safe_entries)


def _try_load_session(path: str | Path):
    try:
        return load_session_state(path)
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _try_compute_artifact_hash(path: str | Path) -> str | None:
    try:
        if not Path(path).exists():
            return None
        return compute_artifact_hash(path)
    except Exception:
        return None


def _current_repo_dirty() -> bool:
    import subprocess

    result = subprocess.run(
        ["git", "status", "--short"],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    return bool(result.stdout.strip())


def _current_git_commit() -> str | None:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _utc_now_iso8601() -> str:
    from datetime import datetime
    from datetime import timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _normalize_last_action(payload: dict[str, object] | None) -> LastActionState | None:
    if payload is None:
        return None
    return LastActionState(
        key=_coerce_optional_str(payload.get("key")),
        title=_coerce_optional_str(payload.get("title")),
        summary=_coerce_optional_str(payload.get("summary")),
        exit_code=payload.get("exit_code") if isinstance(payload.get("exit_code"), int) else None,
        succeeded=payload.get("succeeded") if isinstance(payload.get("succeeded"), bool) else None,
        redacted_stdout_tail=str(payload.get("redacted_stdout_tail") or ""),
        redacted_stderr_tail=str(payload.get("redacted_stderr_tail") or ""),
        warnings=[str(value) for value in list(payload.get("warnings") or [])],
        snapshot_id=_coerce_optional_str(payload.get("snapshot_id")),
        rollback_hint=_coerce_optional_str(payload.get("rollback_hint")),
    )
