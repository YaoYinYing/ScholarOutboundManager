"""Route page store state builders and updates."""

from __future__ import annotations

from dataclasses import replace

from scholar_outbound_manager.tui.path_resolver import UserDataPaths
from scholar_outbound_manager.tui.port_check import PortCheckResult
from scholar_outbound_manager.tui.route_model import RouteCandidateOption
from scholar_outbound_manager.tui.route_model import build_route_workbench_state
from scholar_outbound_manager.tui.route_model import update_route_entry_candidate
from scholar_outbound_manager.tui.state import RouteStoreState


def build_route_store_state(
    *,
    config_path: str,
    user_data_paths: UserDataPaths,
    selected_index: int = 0,
    port_results: dict[str, PortCheckResult] | None = None,
) -> RouteStoreState:
    state = build_route_workbench_state(
        config_path=config_path,
        user_data_paths=user_data_paths,
        selected_index=selected_index,
        port_results=port_results,
    )
    return RouteStoreState(
        entries=tuple(state.entries),
        selected_index=state.selected_index,
        candidate_options=tuple(state.passed_candidates),
        validation_errors=tuple(state.validation_errors),
        apply_available=state.can_apply,
        stale_warning=state.stale_warning,
        port_checks={} if port_results is None else dict(port_results),
    )


def choose_route_candidate(
    state: RouteStoreState,
    *,
    route_id: str,
    candidate_id: str,
) -> RouteStoreState:
    entries = list(state.entries)
    entry_index = next((index for index, entry in enumerate(entries) if entry.route_id == route_id), -1)
    if entry_index < 0:
        return state
    workbench_like = type("RouteWorkbenchLike", (), {
        "entries": list(entries),
        "selected_index": state.selected_index,
        "passed_candidates": list(state.candidate_options),
        "can_apply": state.apply_available,
        "validation_errors": list(state.validation_errors),
        "production_boundary": "",
        "candidate_selector_enabled": bool(state.candidate_options),
        "candidate_selector_message": state.stale_warning,
        "stale_warning": state.stale_warning,
        "current_port_result": None,
    })()
    updated = update_route_entry_candidate(workbench_like, entry_index=entry_index, candidate_id=candidate_id)
    return replace(
        state,
        entries=tuple(updated.entries),
        validation_errors=tuple(updated.validation_errors),
        apply_available=updated.can_apply,
    )
