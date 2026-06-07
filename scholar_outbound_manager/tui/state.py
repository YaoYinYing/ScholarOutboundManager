"""Session-state helpers for the optional workflow TUI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Literal

from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_SESSION_PATH
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_UNDO_JOURNAL_PATH
from scholar_outbound_manager.tui.path_resolver import UserDataPaths
from scholar_outbound_manager.tui.port_check import PortCheckResult
from scholar_outbound_manager.tui.route_model import RouteCandidateOption
from scholar_outbound_manager.tui.route_model import RouteEntryDraft
from scholar_outbound_manager.tui.testing_jobs import TestingJobState
from scholar_outbound_manager.tui.testing_model import CandidateTestRow
from scholar_outbound_manager.tui.testing_runtime import TestingRuntimeState
from scholar_outbound_manager.tui.testing_runtime import TestingSummary


@dataclass(slots=True)
class TuiSessionState:
    """Represent one persisted TUI session state."""

    schema_version: int
    updated_at: str
    workspace: str
    last_step: str | None
    paths: dict[str, str]
    last_results: dict[str, dict[str, object]]


@dataclass(frozen=True, slots=True)
class KeyHint:
    key: str
    label: str


@dataclass(frozen=True, slots=True)
class NavState:
    active_page: Literal["home", "settings", "testing", "route", "logs"]


@dataclass(frozen=True, slots=True)
class StatusBarState:
    message: str | None
    level: Literal["info", "warning", "error", "success"] | None
    keys: tuple[KeyHint, ...]


@dataclass(frozen=True, slots=True)
class ModalState:
    kind: Literal["detail", "confirm", "error", "help"]
    title: str
    body_lines: tuple[str, ...]
    action_key: str | None
    redacted: bool = True


@dataclass(frozen=True, slots=True)
class TestingArtifactsState:
    candidates_exists: bool
    probe_summary_exists: bool
    passed_candidates_exists: bool
    lineage_consistent: bool
    warnings: tuple[str, ...]
    source_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class TestingStoreState:
    artifacts: TestingArtifactsState
    rows: tuple[CandidateTestRow, ...]
    selected_index: int
    job: TestingJobState
    runtime: TestingRuntimeState
    summary: TestingSummary
    stale_warning: str | None
    recent_events: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RouteStoreState:
    entries: tuple[RouteEntryDraft, ...]
    selected_index: int
    candidate_options: tuple[RouteCandidateOption, ...]
    validation_errors: tuple[str, ...]
    apply_available: bool
    stale_warning: str | None
    port_checks: dict[str, PortCheckResult]


@dataclass(frozen=True, slots=True)
class AppState:
    nav: NavState
    settings: dict[str, object]
    testing: TestingStoreState
    route: RouteStoreState
    logs: dict[str, object]
    modal: ModalState | None
    status_bar: StatusBarState
    user_data_paths: UserDataPaths
    config_path: Path


def build_session_state(
    *,
    updated_at: str,
    workspace: str | None = None,
    last_step: str | None = None,
    paths: dict[str, str] | None = None,
    last_results: dict[str, dict[str, object]] | None = None,
) -> TuiSessionState:
    """Build one sanitized TUI session state."""
    return TuiSessionState(
        schema_version=1,
        updated_at=updated_at,
        workspace=workspace or os.getcwd(),
        last_step=last_step,
        paths={} if paths is None else {str(key): str(value) for key, value in paths.items()},
        last_results=_sanitize_mapping({} if last_results is None else last_results),
    )


def session_state_to_dict(state: TuiSessionState) -> dict[str, object]:
    """Serialize one session state for persistence."""
    return {
        "schema_version": state.schema_version,
        "updated_at": state.updated_at,
        "workspace": state.workspace,
        "last_step": state.last_step,
        "paths": dict(state.paths),
        "last_results": _sanitize_mapping(state.last_results),
    }


def write_session_state(path: str | Path, state: TuiSessionState) -> None:
    """Write one sanitized session-state payload."""
    atomic_write_json(path, session_state_to_dict(state))


def load_session_state(path: str | Path) -> TuiSessionState:
    """Load one persisted TUI session state."""
    import json

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("TUI session state must be a JSON object.")
    return build_session_state(
        updated_at=str(payload.get("updated_at") or ""),
        workspace=str(payload.get("workspace") or os.getcwd()),
        last_step=None if payload.get("last_step") is None else str(payload.get("last_step")),
        paths=_string_mapping(payload.get("paths")),
        last_results=_dict_of_dicts(payload.get("last_results")),
    )


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _dict_of_dicts(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, object]] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            normalized[str(key)] = {str(child_key): child_value for child_key, child_value in item.items()}
    return _sanitize_mapping(normalized)


def _sanitize_mapping(value: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            sanitized[str(key)] = _sanitize_mapping({str(child_key): child_value for child_key, child_value in item.items()})
            continue
        if isinstance(item, list):
            sanitized[str(key)] = [_sanitize_scalar(entry) for entry in item]
            continue
        sanitized[str(key)] = _sanitize_scalar(item)
    return sanitized


def _sanitize_scalar(value: Any) -> Any:
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, str):
        lowered = value.lower()
        banned_needles = (
            "vless://",
            "vmess://",
            "trojan://",
            "ss://",
            "hysteria2://",
            "public_key",
            "password",
            "token",
            "auth",
            "obfs-password",
            "server_name",
            "raw_uri",
        )
        if any(needle in lowered for needle in banned_needles):
            return "<REDACTED>"
        return value
    return str(value)
