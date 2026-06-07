from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.state import AppState as _AppState
from scholar_outbound_manager.tui.state import KeyHint as _KeyHint
from scholar_outbound_manager.tui.state import NavState as _NavState
from scholar_outbound_manager.tui.state import RouteStoreState as _RouteStoreState
from scholar_outbound_manager.tui.state import StatusBarState as _StatusBarState
from scholar_outbound_manager.tui.state import TestingArtifactsState as _TestingArtifactsState
from scholar_outbound_manager.tui.state import TestingStoreState as _TestingStoreState
from scholar_outbound_manager.tui.testing_jobs import idle_testing_job_state
from scholar_outbound_manager.tui.testing_model import TestingSummary as _TestingSummary


def test_app_state_holds_single_runtime_shape(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("user_data_dir: state_data\n", encoding="utf-8")
    paths = resolve_user_data_paths(config_path)
    state = _AppState(
        nav=_NavState(active_page="home"),
        settings={},
        testing=_TestingStoreState(
            artifacts=_TestingArtifactsState(False, False, False, True, (), {}),
            rows=(),
            selected_index=0,
            job=idle_testing_job_state(),
            summary=_TestingSummary(True, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "missing", "not_tested"),
            stale_warning=None,
            recent_events=(),
        ),
        route=_RouteStoreState((), 0, (), (), False, None, {}),
        logs={},
        modal=None,
        status_bar=_StatusBarState(message=None, level=None, keys=(_KeyHint("q", "Quit"),)),
        user_data_paths=paths,
        config_path=config_path,
    )

    assert state.nav.active_page == "home"
    assert state.user_data_paths.root == paths.root
