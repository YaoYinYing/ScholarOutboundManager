"""Session state and service operations for the TUI.

SessionState is the single source of truth for all live TUI state.
SessionServices provides all mutation and I/O methods.
Neither module depends on Textual — they are testable without a TUI.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

from scholar_outbound_manager.config import ConfigError
from scholar_outbound_manager.config import load_config
from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.selection import build_candidate_catalog
from scholar_outbound_manager.selection import build_candidate_display_label
from scholar_outbound_manager.selection import infer_region_hint
from scholar_outbound_manager.selection import load_candidate_payload
from scholar_outbound_manager.selection import load_selected_candidate_artifact
from scholar_outbound_manager.selection_policy import SelectionPolicyOptions
from scholar_outbound_manager.selection_policy import select_candidate_with_policy
from scholar_outbound_manager.state.artifact_lineage import check_artifact_consistency
from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.tui.action_policy import get_action_policy
from scholar_outbound_manager.tui.action_runner import ActionRunOptions
from scholar_outbound_manager.tui.action_runner import ActionResult
from scholar_outbound_manager.tui.action_runner import SubprocessActionRunner
from scholar_outbound_manager.tui.action_runner import append_action_journal
from scholar_outbound_manager.tui.artifact_rollback import ArtifactRollbackResult
from scholar_outbound_manager.tui.artifact_rollback import ArtifactSnapshot
from scholar_outbound_manager.tui.artifact_rollback import create_artifact_snapshot
from scholar_outbound_manager.tui.artifact_rollback import list_artifact_snapshots
from scholar_outbound_manager.tui.artifact_rollback import rollback_artifact_snapshot
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
from scholar_outbound_manager.tui.commands import preview_command
from scholar_outbound_manager.tui.config_editor import ConfigSaveResult
from scholar_outbound_manager.tui.config_editor import ConfigUndoResult
from scholar_outbound_manager.tui.config_editor import build_redacted_config_diff
from scholar_outbound_manager.tui.config_editor import has_undo_journal_entry
from scholar_outbound_manager.tui.config_editor import load_config_draft
from scholar_outbound_manager.tui.config_editor import undo_last_config_save
from scholar_outbound_manager.tui.config_form import ConfigFieldSpec
from scholar_outbound_manager.tui.config_form import apply_config_form_patch
from scholar_outbound_manager.tui.config_form import build_config_form_state
from scholar_outbound_manager.tui.config_form import build_config_patch_from_field_update
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ACTION_JOURNAL_PATH
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ARTIFACT_SNAPSHOT_ROOT
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_UNDO_JOURNAL_PATH
from scholar_outbound_manager.tui.path_resolver import UserDataPaths
from scholar_outbound_manager.tui.path_resolver import load_raw_config_mapping
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.port_check import PortCheckResult
from scholar_outbound_manager.tui.port_check import check_route_port
from scholar_outbound_manager.tui.view_model import redact_text
from scholar_outbound_manager.tui.view_model import truncate_display_value

# ---------------------------------------------------------------------------
# SessionState — single source of truth
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CandidateTestRow:
    """One redacted candidate row for the Testing DataTable."""

    candidate_id: str
    index: int
    status_icon: str
    region_hint: str | None
    label: str
    protocol: str
    latency_ms: int | None
    home_status: str
    query_status: str
    stage: str
    markers: tuple[str, ...]
    passed: bool | None
    selected_for_route: bool


@dataclass(slots=True)
class RouteEntryView:
    """One route entry for the Route DataTable."""

    route_id: str
    name: str
    enabled: bool
    candidate_id: str | None
    candidate_label: str | None
    region_hint: str | None
    protocol: str
    listen_host: str
    listen_port: int
    port_status: str
    validation_status: str


@dataclass(slots=True)
class RouteCandidateOption:
    """One passed-candidate option for the Route candidate Select."""

    candidate_id: str
    label: str
    region_hint: str | None
    protocol: str
    stage: str


@dataclass(slots=True)
class ActionHistoryEntry:
    """One redacted action journal entry."""

    created_at: str
    key: str | None
    title: str | None
    summary: str | None
    exit_code: int | None
    succeeded: bool | None
    snapshot_id: str | None


@dataclass(slots=True)
class SessionState:
    """Complete live TUI state derived from config and on-disk artifacts."""

    # Paths
    config_path: Path
    user_data_paths: UserDataPaths

    # Config
    config_loaded: bool = False
    config_valid: bool = False
    config_validation_errors: tuple[str, ...] = ()
    config_dirty: bool = False
    config_undo_available: bool = False
    config_redacted_diff: str | None = None
    subscription_url_configured: bool = False
    subscription_url_masked: str = ""
    subscription_user_agent: str = "Clash.Meta"
    xray_binary_path: str = ""
    xray_binary_exists: bool = False
    fail_closed: bool = True
    experimental_hysteria2: bool = False
    service_name: str = "scholar-outbound-sidecar.service"
    probe_concurrency: int = 1
    probe_allow_network_probe: bool = False
    routing_mode: str = "dedicated_inbound"

    # Config form
    config_fields: tuple[ConfigFieldSpec, ...] = ()

    # Artifacts
    candidates_exists: bool = False
    probe_summary_exists: bool = False
    passed_candidates_exists: bool = False
    selected_candidate_exists: bool = False
    pool_plan_exists: bool = False
    artifact_lineage_consistent: bool | None = None
    artifact_warnings: tuple[str, ...] = ()

    # Testing summary
    testing_phase: str = "idle"
    testing_job_id: str | None = None
    testing_progress_current: int = 0
    testing_progress_total: int = 1
    testing_candidate_count: int = 0
    testing_supported_count: int = 0
    testing_experimental_disabled_count: int = 0
    testing_attempted_count: int = 0
    testing_passed_count: int = 0
    testing_failed_count: int = 0
    testing_skipped_count: int = 0
    testing_full_access_count: int = 0
    testing_query_blocked_count: int = 0
    testing_transport_failed_count: int = 0
    testing_last_fetch_status: str | None = None
    testing_last_probe_status: str | None = None
    testing_stale_warning: str | None = None
    testing_rows: tuple[CandidateTestRow, ...] = ()
    testing_selected_index: int = 0
    testing_recent_events: tuple[str, ...] = ()

    # Route
    route_entries: tuple[RouteEntryView, ...] = ()
    route_selected_index: int = 0
    route_candidate_options: tuple[RouteCandidateOption, ...] = ()
    route_validation_errors: tuple[str, ...] = ()
    route_apply_available: bool = False
    route_stale_warning: str | None = None

    # Sidecar
    sidecar_service_active: str = "unknown"
    sidecar_service_enabled: str = "unknown"
    sidecar_socks_status: str = "unknown"
    sidecar_last_validation: str | None = None

    # Logs
    last_action: dict[str, object] | None = None
    action_history: tuple[ActionHistoryEntry, ...] = ()
    snapshot_count: int = 0
    latest_snapshot_id: str | None = None

    # Workflow
    next_recommended_action: str = "Configure subscription and test nodes."
    blocking_reason: str | None = None

    # Commands
    fetch_command_preview: str = ""
    probe_command_preview: str = ""
    select_command_preview: str = ""
    sidecar_stage_command_preview: str = ""
    service_restart_command_preview: str = ""
    service_validate_command_preview: str = ""
    snippet_command_preview: str = ""
    pool_stage_command_preview: str = ""


# ---------------------------------------------------------------------------
# SessionServices — all mutation and I/O
# ---------------------------------------------------------------------------


class SessionServices:
    """Own all mutation, I/O, and state derivation for the TUI.

    No Textual dependency.  Testable without a display.
    """

    def __init__(self, config_path: str | Path) -> None:
        self._config_path = Path(config_path)
        self._runner = SubprocessActionRunner()
        self._action_journal_path = DEFAULT_TUI_ACTION_JOURNAL_PATH
        self._snapshot_root = DEFAULT_TUI_ARTIFACT_SNAPSHOT_ROOT
        self._undo_journal_path = DEFAULT_TUI_UNDO_JOURNAL_PATH

    # ------------------------------------------------------------------
    # State snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> SessionState:
        """Return a complete SessionState derived from current disk state."""
        paths = resolve_user_data_paths(self._config_path)
        state = SessionState(config_path=self._config_path, user_data_paths=paths)

        # Config
        self._load_config_state(state, paths)

        # Artifacts
        self._load_artifact_state(state, paths)

        # Testing
        self._load_testing_state(state, paths)

        # Route
        self._load_route_state(state, paths)

        # Sidecar
        self._load_sidecar_state(state, paths)

        # Logs
        self._load_logs_state(state, paths)

        # Workflow
        self._derive_workflow_state(state)

        return state

    # ------------------------------------------------------------------
    # Config mutations
    # ------------------------------------------------------------------

    def update_config_field(self, field_key: str, value: object) -> ConfigSaveResult:
        patch = build_config_patch_from_field_update(field_key, value)
        result = apply_config_form_patch(
            str(self._config_path),
            patch,
            undo_journal_path=self._undo_journal_path,
        )
        return result

    def save_config(self) -> ConfigSaveResult:
        fields = build_config_form_state(str(self._config_path)).fields
        if not fields:
            raise ValueError("No structured config fields are available.")
        return self.update_config_field(fields[0].key, fields[0].current_value)

    def undo_config(self) -> ConfigUndoResult:
        return undo_last_config_save(
            config_path=str(self._config_path),
            undo_journal_path=self._undo_journal_path,
        )

    # ------------------------------------------------------------------
    # Testing operations
    # ------------------------------------------------------------------

    def fetch_subscription(self) -> ActionResult:
        paths = resolve_user_data_paths(self._config_path)
        spec = build_fetch_command(str(self._config_path), str(paths.candidates), str(paths.probe_summary))
        result = self._runner.run(spec, self._run_options(spec, paths))
        append_action_journal(result, journal_path=self._action_journal_path)
        return result

    def probe_candidates(self) -> ActionResult:
        paths = resolve_user_data_paths(self._config_path)
        spec = build_probe_command(str(self._config_path), str(paths.candidates), str(paths.probe_summary), str(paths.passed_candidates))
        result = self._runner.run(spec, self._run_options(spec, paths))
        append_action_journal(result, journal_path=self._action_journal_path)
        return result

    # ------------------------------------------------------------------
    # Route operations
    # ------------------------------------------------------------------

    def choose_route_candidate(self, route_id: str, candidate_id: str) -> str:
        """Update one route entry's candidate and persist route drafts."""
        paths = resolve_user_data_paths(self._config_path)
        entries = _load_route_entries(paths)
        updated = False
        for entry in entries:
            if entry.get("route_id") == route_id:
                entry["candidate_id"] = candidate_id
                matching = next((o for o in _build_route_candidate_options(paths) if o.candidate_id == candidate_id), None)
                if matching is not None:
                    entry["candidate_label"] = matching.label
                    entry["region_hint"] = matching.region_hint
                    entry["protocol"] = matching.protocol
                updated = True
                break
        if updated:
            _save_route_entries(paths, entries)
            label = _find_candidate_label(candidate_id, paths)
            return f"Route candidate set to {label}."
        return "Route entry not found."

    def update_route_field(self, route_id: str, field: str, value: object) -> str:
        paths = resolve_user_data_paths(self._config_path)
        entries = _load_route_entries(paths)
        for entry in entries:
            if entry.get("route_id") == route_id:
                entry[field] = value
                break
        _save_route_entries(paths, entries)
        return f"Updated {field}."

    def add_route_entry(self) -> str:
        paths = resolve_user_data_paths(self._config_path)
        entries = _load_route_entries(paths)
        new_entry = {
            "route_id": f"route-{len(entries) + 1}",
            "name": f"Route {len(entries) + 1}",
            "enabled": True,
            "candidate_id": None,
            "candidate_label": None,
            "region_hint": None,
            "protocol": "unknown",
            "listen_host": "127.0.0.1",
            "listen_port": 19080 + len(entries),
            "port_status": "unchecked",
            "validation_status": "unchecked",
        }
        entries.append(new_entry)
        _save_route_entries(paths, entries)
        return "Added route draft."

    def delete_route_entry(self, index: int) -> str:
        paths = resolve_user_data_paths(self._config_path)
        entries = _load_route_entries(paths)
        if len(entries) <= 1:
            return "Cannot delete the last route entry."
        if 0 <= index < len(entries):
            del entries[index]
            _save_route_entries(paths, entries)
            return "Deleted selected route draft."
        return "Invalid route index."

    def test_route_port(self, route_id: str) -> PortCheckResult:
        paths = resolve_user_data_paths(self._config_path)
        entries = _load_route_entries(paths)
        raw_config = load_raw_config_mapping(str(self._config_path))
        service_name = str(raw_config.get("sidecar", {}).get("service_name", "scholar-outbound-sidecar.service"))
        for entry in entries:
            if entry.get("route_id") == route_id:
                host = str(entry.get("listen_host", "127.0.0.1"))
                port = int(entry.get("listen_port", 19080))
                return check_route_port(
                    host,
                    port,
                    managed_service_name=service_name,
                    runtime_metadata_path=paths.root / ".runtime" / "scholar_sidecar.status.json",
                )
        raise ValueError(f"Route entry not found: {route_id}")

    def apply_routes(self) -> ActionResult:
        paths = resolve_user_data_paths(self._config_path)
        spec = build_service_stage_command(str(self._config_path), str(paths.selected_candidate))
        result = self._runner.run(spec, self._run_options(spec, paths))
        append_action_journal(result, journal_path=self._action_journal_path)
        return result

    # ------------------------------------------------------------------
    # Sidecar operations
    # ------------------------------------------------------------------

    def stage_sidecar(self) -> ActionResult:
        paths = resolve_user_data_paths(self._config_path)
        spec = build_service_stage_command(str(self._config_path), str(paths.selected_candidate))
        result = self._runner.run(spec, self._run_options(spec, paths))
        append_action_journal(result, journal_path=self._action_journal_path)
        return result

    def restart_sidecar(self) -> ActionResult:
        paths = resolve_user_data_paths(self._config_path)
        spec = build_service_restart_command(str(self._config_path))
        result = self._runner.run(spec, self._run_options(spec, paths))
        append_action_journal(result, journal_path=self._action_journal_path)
        return result

    def validate_sidecar(self) -> ActionResult:
        paths = resolve_user_data_paths(self._config_path)
        spec = build_service_validate_command(str(self._config_path))
        result = self._runner.run(spec, self._run_options(spec, paths))
        append_action_journal(result, journal_path=self._action_journal_path)
        return result

    def sidecar_snippet(self) -> str:
        paths = resolve_user_data_paths(self._config_path)
        raw_config = load_raw_config_mapping(str(self._config_path))
        host = str(raw_config.get("sidecar", {}).get("listen_host", "127.0.0.1"))
        port = int(raw_config.get("sidecar", {}).get("listen_port", 19080))
        tag = str(raw_config.get("sidecar", {}).get("socks_tag", "scholar-sidecar-socks-out"))
        return json.dumps(
            {
                "tag": tag,
                "protocol": "socks",
                "settings": {"servers": [{"address": host, "port": port}]},
            },
            indent=2,
        )

    def stage_pool(self) -> ActionResult:
        paths = resolve_user_data_paths(self._config_path)
        spec = build_pool_stage_command(str(self._config_path), str(paths.passed_candidates), str(paths.pool_plan))
        result = self._runner.run(spec, self._run_options(spec, paths))
        append_action_journal(result, journal_path=self._action_journal_path)
        return result

    # ------------------------------------------------------------------
    # Artifact operations
    # ------------------------------------------------------------------

    def create_snapshot(self, reason: str) -> ArtifactSnapshot:
        paths = resolve_user_data_paths(self._config_path)
        return create_artifact_snapshot(
            reason=reason,
            snapshot_root=self._snapshot_root,
            candidates_path=str(paths.candidates),
            probe_summary_path=str(paths.probe_summary),
            passed_candidates_path=str(paths.passed_candidates),
            selected_candidate_path=str(paths.selected_candidate),
            pool_plan_path=str(paths.pool_plan),
        )

    def rollback_snapshot(self, snapshot_id: str | None = None) -> ArtifactRollbackResult:
        sid = snapshot_id or self._latest_snapshot_id()
        if sid is None:
            raise ValueError("No artifact snapshot is available for rollback.")
        return rollback_artifact_snapshot(sid, snapshot_root=self._snapshot_root)

    def check_artifact_consistency(self) -> dict[str, object]:
        paths = resolve_user_data_paths(self._config_path)
        if not paths.candidates.exists():
            return {"overall_consistent": None, "warnings": ["candidates.json is missing."]}
        return check_artifact_consistency(
            candidates_path=str(paths.candidates),
            probe_summary_path=str(paths.probe_summary),
            passed_candidates_path=str(paths.passed_candidates),
        )

    def recent_action_history(self, limit: int = 10) -> list[ActionHistoryEntry]:
        path = Path(self._action_journal_path)
        if not path.exists():
            return []
        entries: list[ActionHistoryEntry] = []
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            entries.append(
                ActionHistoryEntry(
                    created_at=str(payload.get("created_at") or ""),
                    key=payload.get("operation_key") if isinstance(payload.get("operation_key"), str) else None,
                    title=payload.get("title") if isinstance(payload.get("title"), str) else None,
                    summary=_summarize_history(payload),
                    exit_code=payload.get("exit_code") if isinstance(payload.get("exit_code"), int) else None,
                    succeeded=payload.get("succeeded") if isinstance(payload.get("succeeded"), bool) else None,
                    snapshot_id=payload.get("snapshot_id") if isinstance(payload.get("snapshot_id"), str) else None,
                )
            )
            if len(entries) >= limit:
                break
        return entries

    def journal_error(self, description: str, safe_message: str) -> None:
        append_action_journal(
            ActionResult(
                key="tui_error",
                title=description,
                command=["internal", "tui_error"],
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
                warnings=["TUI action failed."],
            ),
            journal_path=self._action_journal_path,
        )

    # ------------------------------------------------------------------
    # Internal: state loaders
    # ------------------------------------------------------------------

    def _load_config_state(self, state: SessionState, paths: UserDataPaths) -> None:
        try:
            config = load_config(str(self._config_path))
            state.config_loaded = True
            state.config_valid = True
            state.subscription_url_configured = any(s.enabled for s in config.subscriptions)
            state.subscription_url_masked = _mask_url(config.subscriptions[0].url) if config.subscriptions else ""
            state.subscription_user_agent = "Clash.Meta"
            state.xray_binary_path = config.xray.binary_path
            state.xray_binary_exists = Path(config.xray.binary_path).exists()
            state.fail_closed = config.routing.fail_closed
            state.probe_concurrency = config.probe.concurrency
            state.probe_allow_network_probe = config.probe.allow_network_probe
            state.routing_mode = config.routing.mode
            state.service_name = "scholar-outbound-sidecar.service"
            state.config_undo_available = has_undo_journal_entry(
                config_path=str(self._config_path),
                undo_journal_path=self._undo_journal_path,
            )
            state.config_fields = tuple(build_config_form_state(str(self._config_path)).fields)
        except (ConfigError, OSError, ValueError):
            state.config_loaded = False
            state.config_valid = False

    def _load_artifact_state(self, state: SessionState, paths: UserDataPaths) -> None:
        state.candidates_exists = paths.candidates.exists()
        state.probe_summary_exists = paths.probe_summary.exists()
        state.passed_candidates_exists = paths.passed_candidates.exists()
        state.selected_candidate_exists = paths.selected_candidate.exists()
        state.pool_plan_exists = paths.pool_plan.exists()

        if state.candidates_exists and state.probe_summary_exists and state.passed_candidates_exists:
            try:
                consistency = check_artifact_consistency(
                    candidates_path=str(paths.candidates),
                    probe_summary_path=str(paths.probe_summary),
                    passed_candidates_path=str(paths.passed_candidates),
                )
                state.artifact_lineage_consistent = consistency.get("overall_consistent")
                warnings = consistency.get("warnings")
                state.artifact_warnings = tuple(warnings) if isinstance(warnings, list) else ()
            except Exception:
                state.artifact_lineage_consistent = None

    def _load_testing_state(self, state: SessionState, paths: UserDataPaths) -> None:
        if not state.candidates_exists:
            return

        try:
            payload = load_candidate_payload(str(paths.candidates))
            if isinstance(payload, dict) and "candidates" in payload:
                raw_candidates = payload["candidates"]
            elif isinstance(payload, list):
                raw_candidates = payload
            else:
                return

            if not isinstance(raw_candidates, list):
                return

            probe_results = _load_probe_results(paths)
            selected_candidate_id = _load_selected_candidate_id(paths)

            rows: list[CandidateTestRow] = []
            for idx, raw in enumerate(raw_candidates):
                if not isinstance(raw, dict):
                    continue
                candidate_id = str(raw.get("candidate_id") or f"candidate-{idx}")
                protocol = str(raw.get("protocol") or "unknown")
                supported = raw.get("supported") if isinstance(raw.get("supported"), bool) else True
                label = build_candidate_display_label(raw) or str(raw.get("raw_name") or candidate_id)
                region_hint = infer_region_hint(raw)

                if not supported:
                    rows.append(
                        CandidateTestRow(
                            candidate_id=candidate_id,
                            index=idx,
                            status_icon="⏭",
                            region_hint=region_hint,
                            label=label,
                            protocol=protocol,
                            latency_ms=None,
                            home_status="-",
                            query_status="-",
                            stage="experimental_disabled",
                            markers=(),
                            passed=False,
                            selected_for_route=candidate_id == selected_candidate_id,
                        )
                    )
                    continue

                probe = probe_results.get(candidate_id)
                if probe is not None:
                    status_icon = "✓" if probe.get("passed") else "✗"
                    stage = probe.get("stage", "unknown")
                    home = str(probe.get("home_status") or "-")
                    query = str(probe.get("query_status") or "-")
                    latency = probe.get("latency_ms") if isinstance(probe.get("latency_ms"), int) else None
                    markers = tuple(probe.get("failure_markers", [])) if isinstance(probe.get("failure_markers"), list) else ()
                    passed = probe.get("passed") if isinstance(probe.get("passed"), bool) else None
                else:
                    status_icon = "○"
                    stage = "untested"
                    home = "-"
                    query = "-"
                    latency = None
                    markers = ()
                    passed = None

                rows.append(
                    CandidateTestRow(
                        candidate_id=candidate_id,
                        index=idx,
                        status_icon=status_icon,
                        region_hint=region_hint,
                        label=label,
                        protocol=protocol,
                        latency_ms=latency,
                        home_status=home,
                        query_status=query,
                        stage=stage,
                        markers=markers,
                        passed=passed,
                        selected_for_route=candidate_id == selected_candidate_id,
                    )
                )

            state.testing_rows = tuple(rows)
            state.testing_candidate_count = len(rows)
            state.testing_supported_count = sum(1 for r in rows if r.stage != "experimental_disabled")
            state.testing_experimental_disabled_count = sum(1 for r in rows if r.stage == "experimental_disabled")
            state.testing_passed_count = sum(1 for r in rows if r.passed is True)
            state.testing_failed_count = sum(1 for r in rows if r.passed is False)
            state.testing_attempted_count = sum(1 for r in rows if r.stage != "untested")
            state.testing_full_access_count = sum(1 for r in rows if r.stage == "full_access")
            state.testing_query_blocked_count = sum(1 for r in rows if r.stage == "query_blocked")
            state.testing_transport_failed_count = sum(1 for r in rows if r.stage == "transport_failed")

            if state.testing_selected_index >= len(rows):
                state.testing_selected_index = 0

        except Exception:
            pass

    def _load_route_state(self, state: SessionState, paths: UserDataPaths) -> None:
        entries_raw = _load_route_entries(paths)
        candidate_options = _build_route_candidate_options(paths)
        state.route_candidate_options = tuple(candidate_options)

        entries: list[RouteEntryView] = []
        for entry in entries_raw:
            entries.append(
                RouteEntryView(
                    route_id=str(entry.get("route_id", "")),
                    name=str(entry.get("name", "Scholar")),
                    enabled=bool(entry.get("enabled", True)),
                    candidate_id=entry.get("candidate_id") if isinstance(entry.get("candidate_id"), str) else None,
                    candidate_label=entry.get("candidate_label") if isinstance(entry.get("candidate_label"), str) else None,
                    region_hint=entry.get("region_hint") if isinstance(entry.get("region_hint"), str) else None,
                    protocol=str(entry.get("protocol", "unknown")),
                    listen_host=str(entry.get("listen_host", "127.0.0.1")),
                    listen_port=int(entry.get("listen_port", 19080)),
                    port_status=str(entry.get("port_status", "unchecked")),
                    validation_status=str(entry.get("validation_status", "unchecked")),
                )
            )

        if not entries:
            entries.append(
                RouteEntryView(
                    route_id="route-1",
                    name="Scholar",
                    enabled=True,
                    candidate_id=None,
                    candidate_label=None,
                    region_hint=None,
                    protocol="unknown",
                    listen_host="127.0.0.1",
                    listen_port=19080,
                    port_status="unchecked",
                    validation_status="unchecked",
                )
            )
            _save_route_entries(paths, [{
                "route_id": e.route_id,
                "name": e.name,
                "enabled": e.enabled,
                "candidate_id": e.candidate_id,
                "candidate_label": e.candidate_label,
                "region_hint": e.region_hint,
                "protocol": e.protocol,
                "listen_host": e.listen_host,
                "listen_port": e.listen_port,
                "port_status": e.port_status,
                "validation_status": e.validation_status,
            } for e in entries])

        state.route_entries = tuple(entries)
        if state.route_selected_index >= len(entries):
            state.route_selected_index = 0

        state.route_apply_available = (
            state.passed_candidates_exists
            and any(e.candidate_id is not None for e in entries)
            and state.artifact_lineage_consistent is not False
        )

    def _load_sidecar_state(self, state: SessionState, paths: UserDataPaths) -> None:
        raw_config = load_raw_config_mapping(str(self._config_path))
        service_name = str(raw_config.get("sidecar", {}).get("service_name", "scholar-outbound-sidecar.service"))

        try:
            result = subprocess.run(
                ["systemctl", "is-active", service_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            state.sidecar_service_active = result.stdout.strip() if result.returncode == 0 else "inactive"
        except Exception:
            state.sidecar_service_active = "unknown"

        try:
            result = subprocess.run(
                ["systemctl", "is-enabled", service_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            state.sidecar_service_enabled = result.stdout.strip() if result.returncode == 0 else "disabled"
        except Exception:
            state.sidecar_service_enabled = "unknown"

    def _load_logs_state(self, state: SessionState, paths: UserDataPaths) -> None:
        last = _load_last_action(self._action_journal_path)
        state.last_action = last
        state.action_history = tuple(self.recent_action_history(limit=10))
        snapshots = list_artifact_snapshots(self._snapshot_root)
        state.snapshot_count = len(snapshots)
        state.latest_snapshot_id = snapshots[0].snapshot_id if snapshots else None

    def _derive_workflow_state(self, state: SessionState) -> None:
        if not state.config_loaded:
            state.next_recommended_action = "Create or open a valid config.yaml."
            state.blocking_reason = "Config is missing or invalid."
        elif not state.subscription_url_configured:
            state.next_recommended_action = "Configure a subscription URL in Settings."
            state.blocking_reason = "No subscription URL is configured."
        elif not state.candidates_exists or state.testing_candidate_count == 0:
            state.next_recommended_action = "Fetch subscription to populate candidates."
            state.blocking_reason = "No candidate nodes are available."
        elif state.testing_passed_count == 0:
            state.next_recommended_action = "Test nodes to find passing candidates."
            state.blocking_reason = "No nodes have passed Scholar probing."
        elif not any(e.candidate_id is not None for e in state.route_entries):
            state.next_recommended_action = "Assign a passed candidate to a route."
            state.blocking_reason = "No route has a selected candidate."
        elif state.sidecar_service_active not in {"active"}:
            state.next_recommended_action = "Apply routes and start the sidecar service."
            state.blocking_reason = "Sidecar service is not active."
        elif state.sidecar_socks_status not in {"ok"}:
            state.next_recommended_action = "Validate the sidecar SOCKS endpoint."
            state.blocking_reason = "Sidecar SOCKS status is unknown."
        else:
            state.next_recommended_action = "Sidecar is ready. Use the SOCKS snippet in production Xray config."
            state.blocking_reason = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_options(self, spec: OperationSpec, paths: UserDataPaths) -> ActionRunOptions:
        return ActionRunOptions(
            cwd=None,
            timeout_seconds=spec.timeout_seconds,
            allow_network=spec.network_access,
            allow_systemd=spec.systemd_access,
            allow_sensitive_artifact_write=spec.sensitive_outputs,
            snapshot_root=self._snapshot_root,
            artifact_paths={
                "candidates": str(paths.candidates),
                "probe_summary": str(paths.probe_summary),
                "passed_candidates": str(paths.passed_candidates),
                "selected_candidate": str(paths.selected_candidate),
                "pool_plan": str(paths.pool_plan),
            },
        )

    def _latest_snapshot_id(self) -> str | None:
        snapshots = list_artifact_snapshots(self._snapshot_root)
        return snapshots[0].snapshot_id if snapshots else None


# ---------------------------------------------------------------------------
# Internal helpers (not class methods)
# ---------------------------------------------------------------------------


def _mask_url(url: str) -> str:
    """Return one redacted URL safe for display."""
    if not url:
        return ""
    try:
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.hostname:
            return f"{parsed.scheme}://{parsed.hostname}/***configured***"
    except Exception:
        pass
    return "***configured***"


def _load_route_entries(paths: UserDataPaths) -> list[dict[str, object]]:
    if paths.selected_routes.exists():
        try:
            payload = json.loads(paths.selected_routes.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("entries"), list):
                return [dict(e) for e in payload["entries"] if isinstance(e, dict)]
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_route_entries(paths: UserDataPaths, entries: list[dict[str, object]]) -> None:
    paths.selected_routes.parent.mkdir(parents=True, exist_ok=True)
    payload = {"entries": entries}
    # Atomic write
    tmp = paths.selected_routes.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(paths.selected_routes)


def _load_probe_results(paths: UserDataPaths) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}
    if paths.probe_summary.exists():
        try:
            summary = json.loads(paths.probe_summary.read_text(encoding="utf-8"))
            if isinstance(summary, dict):
                records = summary.get("records")
                if isinstance(records, list):
                    for record in records:
                        if isinstance(record, dict):
                            cid = record.get("candidate_id")
                            if isinstance(cid, str):
                                results[cid] = {
                                    "passed": record.get("passed"),
                                    "stage": record.get("scholar_stage", "unknown"),
                                    "home_status": record.get("home_status"),
                                    "query_status": record.get("query_status"),
                                    "latency_ms": record.get("latency_ms"),
                                    "failure_markers": record.get("failure_markers", []),
                                }
        except (json.JSONDecodeError, OSError):
            pass
    return results


def _load_selected_candidate_id(paths: UserDataPaths) -> str | None:
    if paths.selected_candidate.exists():
        try:
            payload = json.loads(paths.selected_candidate.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                cid = payload.get("candidate_id")
                return str(cid) if isinstance(cid, str) else None
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _build_route_candidate_options(paths: UserDataPaths) -> list[RouteCandidateOption]:
    options: list[RouteCandidateOption] = []
    source = paths.passed_candidates if paths.passed_candidates.exists() else paths.candidates
    if not source.exists():
        return options
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        candidates = []
        if isinstance(payload, dict):
            candidates = payload.get("candidates", payload.get("records", []))
        elif isinstance(payload, list):
            candidates = payload

        if not isinstance(candidates, list):
            return options

        for item in candidates:
            if not isinstance(item, dict):
                continue
            passed = item.get("passed")
            if passed is not True:
                continue
            candidate_id = str(item.get("candidate_id", ""))
            if not candidate_id:
                continue
            label = build_candidate_display_label(item) or str(item.get("raw_name") or candidate_id)
            options.append(
                RouteCandidateOption(
                    candidate_id=candidate_id,
                    label=label,
                    region_hint=infer_region_hint(item),
                    protocol=str(item.get("protocol", "unknown")),
                    stage=str(item.get("scholar_stage", item.get("stage", "unknown"))),
                )
            )
    except (json.JSONDecodeError, OSError):
        pass
    return options


def _find_candidate_label(candidate_id: str, paths: UserDataPaths) -> str:
    for opt in _build_route_candidate_options(paths):
        if opt.candidate_id == candidate_id:
            return opt.label
    return candidate_id


def _load_last_action(journal_path: str) -> dict[str, object] | None:
    path = Path(journal_path)
    if not path.exists():
        return None
    try:
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                return {
                    "key": payload.get("operation_key") if isinstance(payload.get("operation_key"), str) else None,
                    "title": payload.get("title") if isinstance(payload.get("title"), str) else None,
                    "summary": payload.get("summary") if isinstance(payload.get("summary"), str) else None,
                    "exit_code": payload.get("exit_code") if isinstance(payload.get("exit_code"), int) else None,
                    "succeeded": payload.get("succeeded") if isinstance(payload.get("succeeded"), bool) else None,
                }
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _summarize_history(payload: dict[str, object]) -> str | None:
    title = payload.get("title")
    succeeded = payload.get("succeeded")
    exit_code = payload.get("exit_code")
    if not isinstance(title, str) or not title:
        return None
    if succeeded is True:
        return f"{title} completed successfully."
    if succeeded is False:
        return f"{title} failed with exit code {exit_code}."
    return title
