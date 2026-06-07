"""Pure reducer for the store-driven TUI runtime."""

from __future__ import annotations

from dataclasses import replace

from scholar_outbound_manager.tui.effects import CreateSnapshot
from scholar_outbound_manager.tui.effects import Effect
from scholar_outbound_manager.tui.effects import LoadArtifacts
from scholar_outbound_manager.tui.effects import RunAction
from scholar_outbound_manager.tui.effects import RunPortCheck
from scholar_outbound_manager.tui.effects import RunProbe
from scholar_outbound_manager.tui.effects import SaveRouteDraft
from scholar_outbound_manager.tui.events import ActionCompleted
from scholar_outbound_manager.tui.events import ActionFailed
from scholar_outbound_manager.tui.events import AppEvent
from scholar_outbound_manager.tui.events import ArtifactRefresh
from scholar_outbound_manager.tui.events import HelpRequested
from scholar_outbound_manager.tui.events import ModalCancel
from scholar_outbound_manager.tui.events import ModalConfirm
from scholar_outbound_manager.tui.events import Navigate
from scholar_outbound_manager.tui.events import ProbeCompleted
from scholar_outbound_manager.tui.events import ProbeEventReceived
from scholar_outbound_manager.tui.events import ProbeFailed
from scholar_outbound_manager.tui.events import ProbeStarted
from scholar_outbound_manager.tui.events import RefreshRequested
from scholar_outbound_manager.tui.events import RouteCandidateChosen
from scholar_outbound_manager.tui.events import RouteInspectSelected
from scholar_outbound_manager.tui.events import RouteSelectRow
from scholar_outbound_manager.tui.events import RouteTestPortRequested
from scholar_outbound_manager.tui.events import TestingFetchRequested
from scholar_outbound_manager.tui.events import TestingInspectSelected
from scholar_outbound_manager.tui.events import TestingMoveCursor
from scholar_outbound_manager.tui.events import TestingProbeRequested
from scholar_outbound_manager.tui.events import TestingStopRequested
from scholar_outbound_manager.tui.effects import RunFetch
from scholar_outbound_manager.tui.route_store import choose_route_candidate
from scholar_outbound_manager.tui.state import AppState
from scholar_outbound_manager.tui.state import ModalState
from scholar_outbound_manager.tui.state import NavState
from scholar_outbound_manager.tui.state import StatusBarState
from scholar_outbound_manager.tui.testing_jobs import update_testing_job_state
from scholar_outbound_manager.tui.testing_store import apply_testing_event


def reduce_app_state(state: AppState, event: AppEvent) -> tuple[AppState, tuple[Effect, ...]]:
    """Reduce one event into a new AppState and follow-up effects."""
    if isinstance(event, Navigate):
        return replace(state, nav=NavState(active_page=event.page), status_bar=_context_status(state, message=None)), ()
    if isinstance(event, RefreshRequested):
        return state, (LoadArtifacts(reason="user_refresh"),)
    if isinstance(event, HelpRequested):
        return replace(
            state,
            modal=ModalState(kind="help", title="Help", body_lines=tuple(hint.label for hint in state.status_bar.keys), action_key=None),
        ), ()
    if isinstance(event, ModalCancel):
        return replace(state, modal=None), ()
    if isinstance(event, ModalConfirm):
        if state.modal is None or state.modal.action_key is None:
            return replace(state, modal=None), ()
        return replace(state, modal=None), (RunAction(action_key=state.modal.action_key),)
    if isinstance(event, TestingFetchRequested):
        job = update_testing_job_state(
            state.testing.job,
            status="fetching",
            current=0,
            total=max(state.testing.summary.candidate_count, 1),
            passed=0,
            failed=0,
            skipped=0,
            message="Fetch started.",
            can_cancel=True,
        )
        return (
            replace(
                state,
                testing=replace(state.testing, job=job),
                status_bar=_context_status(state, message="Fetch started.", level="info"),
            ),
            (CreateSnapshot(reason="testing_fetch"), RunFetch()),
        )
    if isinstance(event, TestingProbeRequested):
        job = update_testing_job_state(
            state.testing.job,
            status="probing",
            current=0,
            total=max(state.testing.summary.supported_count, len(state.testing.rows), 1),
            passed=0,
            failed=0,
            skipped=0,
            message="Probe started.",
            can_cancel=True,
        )
        return (
            replace(
                state,
                testing=replace(state.testing, job=job),
                status_bar=_context_status(state, message="Probe started.", level="info"),
            ),
            (CreateSnapshot(reason="testing_probe"), RunProbe()),
        )
    if isinstance(event, ProbeStarted):
        job = update_testing_job_state(state.testing.job, status="probing", total=event.total, message="Probe started.", can_cancel=True)
        return replace(state, testing=replace(state.testing, job=job)), ()
    if isinstance(event, ProbeEventReceived):
        testing = apply_testing_event(state.testing, event.event)
        return replace(state, testing=testing), ()
    if isinstance(event, ProbeCompleted):
        job = update_testing_job_state(state.testing.job, status="completed", message=event.message, can_cancel=False)
        return replace(state, testing=replace(state.testing, job=job), status_bar=_context_status(state, message=event.message, level="success")), (LoadArtifacts(reason="probe_completed"),)
    if isinstance(event, ProbeFailed):
        job = update_testing_job_state(state.testing.job, status="failed", message=event.error, can_cancel=False)
        return replace(state, testing=replace(state.testing, job=job), status_bar=_context_status(state, message=event.error, level="error")), ()
    if isinstance(event, TestingStopRequested):
        job = update_testing_job_state(state.testing.job, status="cancelling", message="Cancelling Testing job...", can_cancel=False)
        return replace(state, testing=replace(state.testing, job=job), status_bar=_context_status(state, message=job.message, level="warning")), ()
    if isinstance(event, TestingMoveCursor):
        next_index = 0
        if state.testing.rows:
            next_index = max(0, min(len(state.testing.rows) - 1, state.testing.selected_index + event.delta))
        return replace(state, testing=replace(state.testing, selected_index=next_index)), ()
    if isinstance(event, TestingInspectSelected):
        return replace(
            state,
            modal=ModalState(kind="detail", title="Testing detail", body_lines=tuple(state.testing.recent_events) or ("No detail available.",), action_key=None),
        ), ()
    if isinstance(event, RouteSelectRow):
        next_index = max(0, min(len(state.route.entries) - 1, event.index)) if state.route.entries else 0
        return replace(state, route=replace(state.route, selected_index=next_index)), ()
    if isinstance(event, RouteCandidateChosen):
        updated_route = choose_route_candidate(state.route, route_id=event.route_id, candidate_id=event.candidate_id)
        label = next((option.label for option in updated_route.candidate_options if option.candidate_id == event.candidate_id), event.candidate_id)
        route_name = next((entry.name for entry in updated_route.entries if entry.route_id == event.route_id), "Route")
        return (
            replace(
                state,
                route=updated_route,
                status_bar=_context_status(state, message=f"{route_name} candidate set to {label}.", level="success"),
            ),
            (SaveRouteDraft(),),
        )
    if isinstance(event, RouteTestPortRequested):
        return state, (RunPortCheck(route_id=event.route_id),)
    if isinstance(event, RouteInspectSelected):
        entry = state.route.entries[state.route.selected_index] if state.route.entries else None
        lines = ("No route selected.",) if entry is None else (
            f"Name: {entry.name}",
            f"Candidate: {entry.candidate_label or '(not selected)'}",
            f"Host: {entry.listen_host}",
            f"Port: {entry.listen_port}",
        )
        return replace(state, modal=ModalState(kind="detail", title="Route detail", body_lines=lines, action_key=None)), ()
    if isinstance(event, ArtifactRefresh):
        return replace(state, status_bar=_context_status(state, message=None)), ()
    if isinstance(event, ActionCompleted):
        return replace(state, status_bar=_context_status(state, message=event.message, level="success")), ()
    if isinstance(event, ActionFailed):
        return replace(state, status_bar=_context_status(state, message=event.error, level="error")), ()
    return state, ()


def _context_status(state: AppState, *, message: str | None, level: str | None = None) -> StatusBarState:
    return StatusBarState(message=message, level=level, keys=state.status_bar.keys)
