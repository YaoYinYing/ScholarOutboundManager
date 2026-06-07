"""Explicit intents and backend events for the store-driven TUI runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from scholar_outbound_manager.tui.port_check import PortCheckResult
from scholar_outbound_manager.tui.state import AppState
from scholar_outbound_manager.tui.testing_events import TestingEvent


PageName = Literal["home", "settings", "testing", "route", "logs"]
ArtifactKind = Literal[
    "candidates_changed",
    "probe_summary_changed",
    "passed_candidates_changed",
    "selected_routes_changed",
    "config_changed",
]


@dataclass(frozen=True, slots=True)
class Navigate:
    page: PageName


@dataclass(frozen=True, slots=True)
class RefreshRequested:
    pass


@dataclass(frozen=True, slots=True)
class TestingFetchRequested:
    pass


@dataclass(frozen=True, slots=True)
class TestingProbeRequested:
    pass


@dataclass(frozen=True, slots=True)
class TestingStopRequested:
    pass


@dataclass(frozen=True, slots=True)
class TestingMoveCursor:
    delta: int


@dataclass(frozen=True, slots=True)
class TestingInspectSelected:
    pass


@dataclass(frozen=True, slots=True)
class RouteAddRequested:
    pass


@dataclass(frozen=True, slots=True)
class RouteDeleteRequested:
    index: int


@dataclass(frozen=True, slots=True)
class RouteSelectRow:
    index: int


@dataclass(frozen=True, slots=True)
class RouteCandidateChosen:
    route_id: str
    candidate_id: str


@dataclass(frozen=True, slots=True)
class RouteHostChanged:
    route_id: str
    host: str


@dataclass(frozen=True, slots=True)
class RoutePortChanged:
    route_id: str
    port: int


@dataclass(frozen=True, slots=True)
class RouteEnabledChanged:
    route_id: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class RouteTestPortRequested:
    route_id: str


@dataclass(frozen=True, slots=True)
class RouteApplyRequested:
    pass


@dataclass(frozen=True, slots=True)
class RouteStartRequested:
    pass


@dataclass(frozen=True, slots=True)
class RouteStopRequested:
    pass


@dataclass(frozen=True, slots=True)
class RouteRestartRequested:
    pass


@dataclass(frozen=True, slots=True)
class RouteValidateRequested:
    pass


@dataclass(frozen=True, slots=True)
class RouteInspectSelected:
    pass


@dataclass(frozen=True, slots=True)
class ModalConfirm:
    pass


@dataclass(frozen=True, slots=True)
class ModalCancel:
    pass


@dataclass(frozen=True, slots=True)
class HelpRequested:
    pass


@dataclass(frozen=True, slots=True)
class LogsSnapshotRequested:
    pass


@dataclass(frozen=True, slots=True)
class LogsRollbackRequested:
    snapshot_id: str | None = None


@dataclass(frozen=True, slots=True)
class FetchStarted:
    job_id: str


@dataclass(frozen=True, slots=True)
class FetchCompleted:
    job_id: str
    message: str


@dataclass(frozen=True, slots=True)
class FetchFailed:
    job_id: str
    error: str


@dataclass(frozen=True, slots=True)
class ProbeStarted:
    job_id: str
    total: int
    parallel_workers: int | None = None
    progress_mode: Literal["none", "phase_only", "live_candidate_stream"] = "phase_only"


@dataclass(frozen=True, slots=True)
class ProbeEventReceived:
    job_id: str
    event: TestingEvent


@dataclass(frozen=True, slots=True)
class ProbeProcessCompleted:
    job_id: str
    exit_code: int


@dataclass(frozen=True, slots=True)
class ProbeFailed:
    job_id: str
    error: str
    exit_code: int | None = None


@dataclass(frozen=True, slots=True)
class ArtifactLoaded:
    state: AppState


@dataclass(frozen=True, slots=True)
class ArtifactLoadFailed:
    message: str


@dataclass(frozen=True, slots=True)
class JobCancelled:
    job_id: str
    kind: str


@dataclass(frozen=True, slots=True)
class PortCheckCompleted:
    route_id: str
    result: PortCheckResult


@dataclass(frozen=True, slots=True)
class ActionCompleted:
    action_key: str
    message: str


@dataclass(frozen=True, slots=True)
class ActionFailed:
    action_key: str
    error: str


@dataclass(frozen=True, slots=True)
class EffectFailed:
    effect_name: str
    message: str
    recoverable: bool = True


@dataclass(frozen=True, slots=True)
class AppStateReloaded:
    state: AppState


@dataclass(frozen=True, slots=True)
class ArtifactRefresh:
    kind: ArtifactKind


UserIntent = (
    Navigate
    | RefreshRequested
    | TestingFetchRequested
    | TestingProbeRequested
    | TestingStopRequested
    | TestingMoveCursor
    | TestingInspectSelected
    | RouteAddRequested
    | RouteDeleteRequested
    | RouteSelectRow
    | RouteCandidateChosen
    | RouteHostChanged
    | RoutePortChanged
    | RouteEnabledChanged
    | RouteTestPortRequested
    | RouteApplyRequested
    | RouteStartRequested
    | RouteStopRequested
    | RouteRestartRequested
    | RouteValidateRequested
    | RouteInspectSelected
    | ModalConfirm
    | ModalCancel
    | HelpRequested
    | LogsSnapshotRequested
    | LogsRollbackRequested
)

BackendEvent = (
    FetchStarted
    | FetchCompleted
    | FetchFailed
    | ProbeStarted
    | ProbeEventReceived
    | ProbeProcessCompleted
    | ProbeFailed
    | ArtifactLoaded
    | ArtifactLoadFailed
    | JobCancelled
    | PortCheckCompleted
    | ActionCompleted
    | ActionFailed
    | EffectFailed
    | AppStateReloaded
)

AppEvent = UserIntent | BackendEvent | ArtifactRefresh


__all__ = [
    "ActionCompleted",
    "ActionFailed",
    "AppStateReloaded",
    "AppEvent",
    "EffectFailed",
    "ArtifactRefresh",
    "FetchCompleted",
    "FetchFailed",
    "FetchStarted",
    "HelpRequested",
    "JobCancelled",
    "LogsRollbackRequested",
    "LogsSnapshotRequested",
    "ModalCancel",
    "ModalConfirm",
    "Navigate",
    "PortCheckCompleted",
    "ProbeCompleted",
    "ProbeEventReceived",
    "ProbeFailed",
    "ProbeStarted",
    "RefreshRequested",
    "RouteAddRequested",
    "RouteApplyRequested",
    "RouteCandidateChosen",
    "RouteDeleteRequested",
    "RouteEnabledChanged",
    "RouteHostChanged",
    "RouteInspectSelected",
    "RoutePortChanged",
    "RouteRestartRequested",
    "RouteSelectRow",
    "RouteStartRequested",
    "RouteStopRequested",
    "RouteTestPortRequested",
    "RouteValidateRequested",
    "TestingFetchRequested",
    "TestingInspectSelected",
    "TestingMoveCursor",
    "TestingProbeRequested",
    "TestingStopRequested",
]
