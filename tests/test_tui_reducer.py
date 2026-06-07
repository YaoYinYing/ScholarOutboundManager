from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess

from scholar_outbound_manager.tui.effects import CreateSnapshot
from scholar_outbound_manager.tui.effects import LoadArtifacts
from scholar_outbound_manager.tui.effects import RunFetch
from scholar_outbound_manager.tui.effects import RunProbe
from scholar_outbound_manager.tui.effects import SaveRouteDraft
from scholar_outbound_manager.tui.events import ModalCancel
from scholar_outbound_manager.tui.events import ModalConfirm
from scholar_outbound_manager.tui.events import Navigate
from scholar_outbound_manager.tui.events import RefreshRequested
from scholar_outbound_manager.tui.events import RouteCandidateChosen
from scholar_outbound_manager.tui.events import TestingFetchRequested as _TestingFetchRequested
from scholar_outbound_manager.tui.events import TestingProbeRequested as _TestingProbeRequested
from scholar_outbound_manager.tui.reducer import reduce_app_state
from scholar_outbound_manager.tui.route_model import RouteCandidateOption
from scholar_outbound_manager.tui.route_model import RouteEntryDraft
from scholar_outbound_manager.tui.state import AppState as _AppState
from scholar_outbound_manager.tui.state import KeyHint as _KeyHint
from scholar_outbound_manager.tui.state import ModalState
from scholar_outbound_manager.tui.state import NavState as _NavState
from scholar_outbound_manager.tui.state import RouteStoreState as _RouteStoreState
from scholar_outbound_manager.tui.state import StatusBarState as _StatusBarState
from scholar_outbound_manager.tui.state import TestingArtifactsState as _TestingArtifactsState
from scholar_outbound_manager.tui.state import TestingStoreState as _TestingStoreState
from scholar_outbound_manager.tui.testing_jobs import idle_testing_job_state
from scholar_outbound_manager.tui.testing_model import TestingSummary as _TestingSummary


def test_navigate_changes_active_page(tmp_path: Path) -> None:
    state = _state(tmp_path)
    new_state, effects = reduce_app_state(state, Navigate(page="route"))

    assert new_state.nav.active_page == "route"
    assert effects == ()


def test_refresh_requested_emits_load_artifacts(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _, effects = reduce_app_state(state, RefreshRequested())

    assert effects == (LoadArtifacts(reason="user_refresh"),)


def test_modal_confirm_emits_run_action(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state = replace(state, modal=ModalState(kind="confirm", title="Confirm", body_lines=("x",), action_key="service_restart"))
    new_state, effects = reduce_app_state(state, ModalConfirm())

    assert new_state.modal is None
    assert effects[0].action_key == "service_restart"


def test_modal_cancel_clears_modal(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state = replace(state, modal=ModalState(kind="help", title="Help", body_lines=("x",), action_key=None))
    new_state, effects = reduce_app_state(state, ModalCancel())

    assert new_state.modal is None
    assert effects == ()


def test_reducer_is_pure_for_navigation(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path)

    def unexpected_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called by the reducer")

    def unexpected_read_text(*args, **kwargs):
        raise AssertionError("Path.read_text should not be called by the reducer")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    monkeypatch.setattr(Path, "read_text", unexpected_read_text)

    new_state, effects = reduce_app_state(state, Navigate(page="testing"))

    assert new_state.nav.active_page == "testing"
    assert effects == ()


def test_testing_fetch_requested_sets_job_and_effects(tmp_path: Path) -> None:
    state = _state(tmp_path)
    new_state, effects = reduce_app_state(state, _TestingFetchRequested())

    assert new_state.testing.job.status == "fetching"
    assert CreateSnapshot(reason="testing_fetch") in effects
    assert RunFetch() in effects


def test_testing_probe_requested_sets_job_and_effects(tmp_path: Path) -> None:
    state = _state(tmp_path)
    new_state, effects = reduce_app_state(state, _TestingProbeRequested())

    assert new_state.testing.job.status == "probing"
    assert CreateSnapshot(reason="testing_probe") in effects
    assert RunProbe() in effects


def test_route_candidate_chosen_updates_state_and_emits_save(tmp_path: Path) -> None:
    state = _state(tmp_path)
    new_state, effects = reduce_app_state(
        state,
        RouteCandidateChosen(route_id="route-1", candidate_id="candidate-001"),
    )

    assert new_state.route.entries[0].candidate_id == "candidate-001"
    assert effects == (SaveRouteDraft(entries=tuple(new_state.route.entries)),)


def _state(tmp_path: Path) -> _AppState:
    from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths

    config_path = tmp_path / "config.yaml"
    config_path.write_text("user_data_dir: state_data\n", encoding="utf-8")
    paths = resolve_user_data_paths(config_path)
    return _AppState(
        nav=_NavState(active_page="home"),
        settings={},
        testing=_TestingStoreState(
            artifacts=_TestingArtifactsState(True, False, False, True, (), {}),
            rows=(),
            selected_index=0,
            job=idle_testing_job_state(),
            summary=_TestingSummary(True, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, "ready", "not_tested"),
            stale_warning=None,
            recent_events=(),
        ),
        route=_RouteStoreState(
            entries=(
                RouteEntryDraft("route-1", "Scholar", True, None, None, None, None, "127.0.0.1", 19080, "unknown", "draft", None),
            ),
            selected_index=0,
            candidate_options=(
                RouteCandidateOption("candidate-001", "US relay", "US", "vless", "full_access", 200, 200),
            ),
            validation_errors=("Scholar is missing a passed candidate.",),
            apply_available=False,
            stale_warning=None,
            port_checks={},
        ),
        logs={},
        modal=None,
        status_bar=_StatusBarState(message=None, level=None, keys=(_KeyHint("q", "Quit"),)),
        user_data_paths=paths,
        config_path=config_path,
    )
