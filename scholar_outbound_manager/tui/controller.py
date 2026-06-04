"""Pure-Python interactive workbench controller for the optional TUI."""

from __future__ import annotations

import json
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
from scholar_outbound_manager.tui.artifact_rollback import ArtifactRollbackResult
from scholar_outbound_manager.tui.artifact_rollback import ArtifactSnapshot
from scholar_outbound_manager.tui.artifact_rollback import create_artifact_snapshot
from scholar_outbound_manager.tui.artifact_rollback import list_artifact_snapshots
from scholar_outbound_manager.tui.artifact_rollback import rollback_artifact_snapshot
from scholar_outbound_manager.tui.config_editor import ConfigSaveResult
from scholar_outbound_manager.tui.config_editor import ConfigUndoResult
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_UNDO_JOURNAL_PATH
from scholar_outbound_manager.tui.config_editor import undo_last_config_save
from scholar_outbound_manager.tui.config_form import apply_config_form_patch
from scholar_outbound_manager.tui.config_form import build_config_patch_from_field_update
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ACTION_JOURNAL_PATH
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ARTIFACT_SNAPSHOT_ROOT
from scholar_outbound_manager.tui.control_plane import ControlPlaneState
from scholar_outbound_manager.tui.control_plane import load_control_plane_state
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.view_model import build_candidate_detail


@dataclass(slots=True)
class WorkbenchSelection:
    active_tab: str
    selected_candidate_index: int | None
    selected_config_field_key: str | None
    selected_snapshot_id: str | None
    selected_action_key: str | None


@dataclass(slots=True)
class WorkbenchMessage:
    level: str
    title: str
    body: str
    redacted: bool = True


@dataclass(slots=True)
class PendingAction:
    key: str
    title: str
    requires_confirmation: bool
    risk_note: str | None


@dataclass(slots=True)
class CandidateChooseResult:
    candidate_id: str
    output_path: str
    snapshot_id: str | None
    message: str


@dataclass(slots=True)
class ActionHistoryEntry:
    created_at: str
    key: str | None
    title: str | None
    summary: str | None
    exit_code: int | None
    succeeded: bool | None
    snapshot_id: str | None


@dataclass(slots=True)
class WorkflowActionState:
    pending_confirmation: str | None
    last_result: ActionResult | None
    status_message: str | None


class WorkbenchController:
    """Own interactive, redacted workbench behavior outside Textual widgets."""

    def __init__(
        self,
        *,
        loader_kwargs: dict[str, object],
        runner: ActionRunner | None = None,
        action_journal_path: str = DEFAULT_TUI_ACTION_JOURNAL_PATH,
        snapshot_root: str = DEFAULT_TUI_ARTIFACT_SNAPSHOT_ROOT,
    ) -> None:
        self._loader_kwargs = dict(loader_kwargs)
        self._runner = SubprocessActionRunner() if runner is None else runner
        self._action_journal_path = action_journal_path
        self._snapshot_root = snapshot_root
        self.state = load_control_plane_state(**self._loader_kwargs)
        self.selection = self._build_default_selection(self.state)
        self.message: WorkbenchMessage | None = None
        self.pending_action: PendingAction | None = None
        self.action_state = WorkflowActionState(pending_confirmation=None, last_result=None, status_message=None)

    def reload(self) -> ControlPlaneState:
        self.state = load_control_plane_state(**self._loader_kwargs)
        self.selection = self._normalize_selection(self.state, self.selection, snapshot_root=self._snapshot_root)
        self.clear_pending_action()
        self.message = WorkbenchMessage("info", "Reloaded", "Workbench state reloaded.")
        self.action_state.status_message = self.message.body
        return self.state

    def move_candidate(self, delta: int) -> WorkbenchSelection:
        rows = self.state.selection_state.rows
        if not rows:
            self.selection.selected_candidate_index = None
            return self.selection
        current = 0 if self.selection.selected_candidate_index is None else self.selection.selected_candidate_index
        self.selection.selected_candidate_index = max(0, min(len(rows) - 1, current + delta))
        return self.selection

    def choose_selected_candidate(self) -> CandidateChooseResult:
        row = self._selected_candidate_row()
        if row is None:
            raise ValueError("No candidate is selected.")
        row_position = self.selection.selected_candidate_index
        source_index = row.get("index")
        if not isinstance(source_index, int):
            raise ValueError("Selected candidate row is missing its source index.")
        snapshot = self.create_snapshot("pre_choose_selected_candidate")
        payload_path = self._candidate_payload_path()
        payload = load_candidate_payload(payload_path)
        record = select_candidate_by_index(payload, source_index)
        artifact = build_selected_candidate_artifact(record, selection_method="index")
        output_path = self._paths()["selected_candidate"]
        write_selected_candidate_artifact(output_path, artifact)
        self.reload()
        self.selection.selected_candidate_index = row_position
        result = CandidateChooseResult(
            candidate_id=record.candidate_id,
            output_path=output_path,
            snapshot_id=snapshot.snapshot_id,
            message=f"Selected candidate {record.candidate_id} and updated selected_candidate.json.",
        )
        self.message = WorkbenchMessage("info", "Candidate Chosen", result.message)
        self.action_state.status_message = result.message
        return result

    def preview_selected_candidate(self) -> dict[str, object]:
        index = self.selection.selected_candidate_index
        if index is None or index >= len(self.state.selection_state.rows):
            return {
                "candidate_id": None,
                "label": None,
                "selected": False,
                "artifact_lineage_warning": self.state.workflow_state.blocking_reason,
            }
        row = self.state.selection_state.rows[index]
        return build_candidate_detail(
            row,
            selected_candidate_id=self.state.selection_state.selected_candidate_id,
            artifact_lineage_warning=self.state.workflow_state.blocking_reason,
        )

    def move_config_field(self, delta: int) -> WorkbenchSelection:
        fields = self.state.config_form_state.fields
        if not fields:
            self.selection.selected_config_field_key = None
            return self.selection
        keys = [field.key for field in fields]
        if self.selection.selected_config_field_key not in keys:
            self.selection.selected_config_field_key = keys[0]
            return self.selection
        current = keys.index(self.selection.selected_config_field_key)
        self.selection.selected_config_field_key = keys[max(0, min(len(keys) - 1, current + delta))]
        return self.selection

    def update_config_field(self, field_key: str, value: object) -> ConfigSaveResult:
        patch = build_config_patch_from_field_update(field_key, value)
        result = apply_config_form_patch(self._paths()["config"], patch, undo_journal_path=self._undo_journal_path())
        self.reload()
        self.selection.selected_config_field_key = field_key
        self.message = WorkbenchMessage("info", "Config Updated", result.message)
        self.action_state.status_message = result.message
        return result

    def save_config(self) -> ConfigSaveResult:
        field_key = self.selection.selected_config_field_key
        if field_key is None:
            raise ValueError("No structured config field is selected.")
        current_value = self._selected_config_value(field_key)
        return self.update_config_field(field_key, current_value)

    def undo_config(self) -> ConfigUndoResult:
        result = undo_last_config_save(config_path=self._paths()["config"], undo_journal_path=self._undo_journal_path())
        self.reload()
        self.message = WorkbenchMessage("info", "Config Undone", result.message)
        self.action_state.status_message = result.message
        return result

    def create_snapshot(self, reason: str) -> ArtifactSnapshot:
        snapshot = create_artifact_snapshot(
            reason=reason,
            snapshot_root=self._snapshot_root,
            candidates_path=self._paths()["candidates"],
            probe_summary_path=self._paths()["probe_summary"],
            passed_candidates_path=self._paths()["passed_candidates"],
            selected_candidate_path=self._paths()["selected_candidate"],
            pool_plan_path=self._paths()["pool_plan"],
        )
        self.reload()
        self.selection.selected_snapshot_id = snapshot.snapshot_id
        self.message = WorkbenchMessage("info", "Snapshot Created", f"Created snapshot {snapshot.snapshot_id}.")
        self.action_state.status_message = self.message.body
        return snapshot

    def rollback_selected_snapshot(self) -> ArtifactRollbackResult:
        snapshot_id = self.selection.selected_snapshot_id or self._latest_snapshot_id()
        if snapshot_id is None:
            raise ValueError("No artifact snapshot is available for rollback.")
        result = rollback_artifact_snapshot(snapshot_id, snapshot_root=self._snapshot_root)
        self.reload()
        self.message = WorkbenchMessage("warning", "Snapshot Restored", result.message)
        self.action_state.status_message = result.message
        return result

    def prepare_action(self, action_key: str) -> PendingAction:
        self.selection.selected_action_key = action_key
        pending = self._pending_from_action_key(action_key)
        self.pending_action = pending
        self.action_state.pending_confirmation = pending.key if pending.requires_confirmation else None
        if pending.requires_confirmation:
            self.action_state.status_message = f"Pending confirmation: press confirm again to run {pending.title}."
        else:
            self.action_state.status_message = f"Prepared safe action: {pending.title}."
        return pending

    def confirm_action(self, action_key: str) -> ActionResult:
        pending = self._pending_from_action_key(action_key)
        if pending.requires_confirmation and (self.pending_action is None or self.pending_action.key != action_key):
            raise ValueError(f"Action '{action_key}' requires prepare_action() before confirmation.")
        self.pending_action = None
        self.action_state.pending_confirmation = None
        result = self._run_action(action_key)
        self.action_state.last_result = result
        self.action_state.status_message = result.summary
        self.message = WorkbenchMessage("info" if result.succeeded else "warning", pending.title, result.summary)
        return result

    def clear_pending_action(self) -> None:
        self.pending_action = None
        self.action_state.pending_confirmation = None

    def handle_operation(self, action_key: str) -> str:
        if self.pending_action is not None and self.pending_action.key == action_key and self.pending_action.requires_confirmation:
            result = self.confirm_action(action_key)
            return result.summary
        pending = self.prepare_action(action_key)
        if pending.requires_confirmation:
            return str(self.action_state.status_message)
        result = self.confirm_action(action_key)
        return result.summary

    def recent_action_history(self, limit: int = 5) -> list[ActionHistoryEntry]:
        path = Path(self._action_journal_path)
        if not path.exists():
            return []
        entries: list[ActionHistoryEntry] = []
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue
            title = _coerce_optional_str(payload.get("title"))
            key = _coerce_optional_str(payload.get("operation_key"))
            exit_code = payload.get("exit_code") if isinstance(payload.get("exit_code"), int) else None
            succeeded = payload.get("succeeded") if isinstance(payload.get("succeeded"), bool) else None
            entries.append(
                ActionHistoryEntry(
                    created_at=str(payload.get("created_at") or ""),
                    key=key,
                    title=title,
                    summary=_summarize_history(title, exit_code, succeeded),
                    exit_code=exit_code,
                    succeeded=succeeded,
                    snapshot_id=_coerce_optional_str(payload.get("snapshot_id")),
                )
            )
            if len(entries) >= limit:
                break
        return entries

    def list_snapshots(self) -> list[ArtifactSnapshot]:
        return list_artifact_snapshots(self._snapshot_root)

    def build_workbench_state(self) -> dict[str, object]:
        selected_candidate = self.preview_selected_candidate()
        selected_field = self._selected_config_field()
        history = [
            {
                "created_at": entry.created_at,
                "key": entry.key,
                "title": entry.title,
                "summary": entry.summary,
                "exit_code": entry.exit_code,
                "succeeded": entry.succeeded,
                "snapshot_id": entry.snapshot_id,
            }
            for entry in self.recent_action_history()
        ]
        snapshot_rows = [
            {
                "snapshot_id": snapshot.snapshot_id,
                "created_at": snapshot.created_at,
                "reason": snapshot.reason,
                "file_count": len(snapshot.files),
            }
            for snapshot in self.list_snapshots()[:5]
        ]
        return {
            "selection": {
                "active_tab": self.selection.active_tab,
                "selected_candidate_index": self.selection.selected_candidate_index,
                "selected_config_field_key": self.selection.selected_config_field_key,
                "selected_snapshot_id": self.selection.selected_snapshot_id,
                "selected_action_key": self.selection.selected_action_key,
            },
            "selected_candidate_detail": selected_candidate,
            "selected_config_field": None if selected_field is None else {
                "key": selected_field.key,
                "title": selected_field.title,
                "current_value": selected_field.current_value,
                "draft_value": selected_field.draft_value,
                "editable": selected_field.editable,
                "requires_restart": selected_field.requires_restart,
                "validation_error": selected_field.validation_error,
            },
            "pending_action": None if self.pending_action is None else {
                "key": self.pending_action.key,
                "title": self.pending_action.title,
                "requires_confirmation": self.pending_action.requires_confirmation,
                "risk_note": self.pending_action.risk_note,
            },
            "message": None if self.message is None else {
                "level": self.message.level,
                "title": self.message.title,
                "body": self.message.body,
                "redacted": self.message.redacted,
            },
            "action_history": history,
            "snapshots": snapshot_rows,
        }

    def _run_action(self, action_key: str) -> ActionResult:
        if action_key == "choose_selected_candidate":
            choose_result = self.choose_selected_candidate()
            return ActionResult(
                key="choose_selected_candidate",
                title="Choose Selected Candidate",
                command=["internal", "choose_selected_candidate"],
                started_at="",
                finished_at="",
                exit_code=0,
                succeeded=True,
                stdout="",
                stderr="",
                redacted_stdout="",
                redacted_stderr="",
                summary=choose_result.message,
                expected_artifacts=[choose_result.output_path],
                warnings=[],
                snapshot_id=choose_result.snapshot_id,
            )
        if action_key == "rollback_snapshot":
            rollback = self.rollback_selected_snapshot()
            return ActionResult(
                key="rollback_snapshot",
                title="Rollback Snapshot",
                command=["internal", "rollback_snapshot"],
                started_at="",
                finished_at="",
                exit_code=0 if rollback.restored else 1,
                succeeded=rollback.restored,
                stdout="",
                stderr="",
                redacted_stdout="",
                redacted_stderr="",
                summary=rollback.message,
                expected_artifacts=rollback.restored_files,
                warnings=rollback.missing_files,
            )
        spec = self._operation_spec(action_key)
        result = self._runner.run(spec, self._build_run_options(spec))
        append_action_journal(result, journal_path=self._action_journal_path)
        self.reload()
        return result

    def _operation_spec(self, action_key: str):
        for operation in self.state.command_state.operations:
            if operation.key == action_key:
                return operation
        raise ValueError(f"Unknown action key: {action_key}")

    def _build_run_options(self, spec) -> ActionRunOptions:
        paths = self._paths()
        return ActionRunOptions(
            cwd=None,
            timeout_seconds=30.0,
            allow_network=spec.network_access,
            allow_systemd=spec.systemd_access,
            allow_sensitive_artifact_write=spec.sensitive_outputs,
            snapshot_root=self._snapshot_root,
            artifact_paths={
                "candidates": paths["candidates"],
                "probe_summary": paths["probe_summary"],
                "passed_candidates": paths["passed_candidates"],
                "selected_candidate": paths["selected_candidate"],
                "pool_plan": paths["pool_plan"],
            },
        )

    def _candidate_payload_path(self) -> str:
        paths = self._paths()
        passed = Path(paths["passed_candidates"])
        if passed.exists():
            return str(passed)
        return paths["candidates"]

    def _paths(self) -> dict[str, str]:
        return {
            "config": str(self._loader_kwargs.get("config_path", "config.yaml")),
            "candidates": str(self._loader_kwargs.get("candidates_path", "candidates.json")),
            "probe_summary": str(self._loader_kwargs.get("probe_summary_path", "state_data/probe_summary.json")),
            "passed_candidates": str(self._loader_kwargs.get("passed_candidates_path", "state_data/passed_candidates.json")),
            "selected_candidate": str(self._loader_kwargs.get("selected_candidate_path", "state_data/selected_candidate.json")),
            "pool_plan": str(self._loader_kwargs.get("pool_plan_path", "state_data/sidecar_pool_plan.json")),
        }

    def _selected_config_field(self):
        fields = self.state.config_form_state.fields
        if not fields:
            return None
        key = self.selection.selected_config_field_key
        for field in fields:
            if field.key == key:
                return field
        return fields[0]

    def _selected_candidate_row(self) -> dict[str, object] | None:
        index = self.selection.selected_candidate_index
        rows = self.state.selection_state.rows
        if index is None or index < 0 or index >= len(rows):
            return None
        row = rows[index]
        if not isinstance(row, dict):
            return None
        return row

    def _selected_config_value(self, field_key: str) -> object:
        for field in self.state.config_form_state.fields:
            if field.key == field_key:
                return field.current_value
        raise ValueError(f"Unknown config field: {field_key}")

    def _latest_snapshot_id(self) -> str | None:
        snapshots = self.list_snapshots()
        if not snapshots:
            return None
        return snapshots[0].snapshot_id

    def _undo_journal_path(self) -> str:
        return str(resolve_user_data_paths(self._paths()["config"]).undo_journal)

    def _pending_from_action_key(self, action_key: str) -> PendingAction:
        if action_key == "choose_selected_candidate":
            return PendingAction(
                key=action_key,
                title="Choose Selected Candidate",
                requires_confirmation=True,
                risk_note="Writes selected_candidate.json and snapshots current local artifacts first.",
            )
        if action_key == "rollback_snapshot":
            return PendingAction(
                key=action_key,
                title="Rollback Snapshot",
                requires_confirmation=True,
                risk_note="Restores local artifacts only and does not undo network or systemd side effects.",
            )
        spec = self._operation_spec(action_key)
        return PendingAction(
            key=spec.key,
            title=spec.title,
            requires_confirmation=spec.requires_confirmation,
            risk_note=spec.risk_note,
        )

    @staticmethod
    def _build_default_selection(state: ControlPlaneState) -> WorkbenchSelection:
        return WorkbenchSelection(
            active_tab=state.tabs[0] if state.tabs else "Overview",
            selected_candidate_index=0 if state.selection_state.rows else None,
            selected_config_field_key=state.config_form_state.fields[0].key if state.config_form_state.fields else None,
            selected_snapshot_id=state.artifact_state.latest_snapshot_id,
            selected_action_key=None,
        )

    @staticmethod
    def _normalize_selection(
        state: ControlPlaneState,
        selection: WorkbenchSelection,
        *,
        snapshot_root: str,
    ) -> WorkbenchSelection:
        normalized = WorkbenchSelection(
            active_tab=selection.active_tab if selection.active_tab in state.tabs else (state.tabs[0] if state.tabs else "Overview"),
            selected_candidate_index=selection.selected_candidate_index,
            selected_config_field_key=selection.selected_config_field_key,
            selected_snapshot_id=selection.selected_snapshot_id,
            selected_action_key=selection.selected_action_key,
        )
        if not state.selection_state.rows:
            normalized.selected_candidate_index = None
        elif normalized.selected_candidate_index is None:
            normalized.selected_candidate_index = 0
        else:
            normalized.selected_candidate_index = max(0, min(len(state.selection_state.rows) - 1, normalized.selected_candidate_index))
        field_keys = [field.key for field in state.config_form_state.fields]
        if not field_keys:
            normalized.selected_config_field_key = None
        elif normalized.selected_config_field_key not in field_keys:
            normalized.selected_config_field_key = field_keys[0]
        snapshot_ids = [snapshot.snapshot_id for snapshot in list_artifact_snapshots(snapshot_root)]
        if snapshot_ids and normalized.selected_snapshot_id not in snapshot_ids:
            normalized.selected_snapshot_id = snapshot_ids[0]
        if not snapshot_ids:
            normalized.selected_snapshot_id = None
        return normalized


def _coerce_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _summarize_history(title: str | None, exit_code: int | None, succeeded: bool | None) -> str | None:
    if not title:
        return None
    if succeeded is True:
        return f"{title} completed successfully."
    if succeeded is False:
        return f"{title} failed with exit code {exit_code}."
    return title
