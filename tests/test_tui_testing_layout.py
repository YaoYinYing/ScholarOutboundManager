"""Tests for the Testing view model logic (no Textual required)."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.tui.services import SessionState
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.view_models import build_testing_view_model


def test_testing_view_model_builds_table_when_no_candidates() -> None:
    state = SessionState(
        config_path=Path("config.yaml"),
        user_data_paths=resolve_user_data_paths("config.yaml"),
    )
    vm = build_testing_view_model(state)

    assert vm.table is not None
    assert vm.table.columns == ["", "#", "Region", "Label", "Protocol", "Latency", "Home", "Query", "Stage", "Markers"]
    assert vm.can_fetch is False
    assert vm.can_probe is False
    assert vm.phase == "idle"


def test_testing_view_model_can_fetch_when_subscription_configured() -> None:
    state = SessionState(
        config_path=Path("config.yaml"),
        user_data_paths=resolve_user_data_paths("config.yaml"),
        subscription_url_configured=True,
    )
    vm = build_testing_view_model(state)
    assert vm.can_fetch is True


def test_testing_view_model_can_probe_when_candidates_exist() -> None:
    state = SessionState(
        config_path=Path("config.yaml"),
        user_data_paths=resolve_user_data_paths("config.yaml"),
        testing_candidate_count=10,
        testing_supported_count=8,
    )
    vm = build_testing_view_model(state)
    assert vm.can_probe is True
    assert vm.candidate_count == 10
