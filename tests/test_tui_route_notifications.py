from __future__ import annotations

from scholar_outbound_manager.tui import app as tui_app


def test_programmatic_route_select_change_is_ignored() -> None:
    assert tui_app._should_ignore_route_select_change(
        route_form_syncing=True,
        event_value="candidate-001",
        current_candidate_id=None,
    ) is True


def test_blank_route_select_change_is_ignored() -> None:
    assert tui_app._should_ignore_route_select_change(
        route_form_syncing=False,
        event_value=None,
        current_candidate_id=None,
    ) is True
    assert tui_app._should_ignore_route_select_change(
        route_form_syncing=False,
        event_value="",
        current_candidate_id=None,
    ) is True


def test_same_route_candidate_select_change_is_idempotent() -> None:
    assert tui_app._should_ignore_route_select_change(
        route_form_syncing=False,
        event_value="candidate-001",
        current_candidate_id="candidate-001",
    ) is True


def test_new_route_candidate_select_change_is_handled() -> None:
    assert tui_app._should_ignore_route_select_change(
        route_form_syncing=False,
        event_value="candidate-002",
        current_candidate_id="candidate-001",
    ) is False
