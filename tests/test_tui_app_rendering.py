from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.tui import app as tui_app


def test_contextual_key_hints_differ_by_page() -> None:
    home = {(hint.key, hint.label) for hint in tui_app._key_hints_for_page("home")}
    route = {(hint.key, hint.label) for hint in tui_app._key_hints_for_page("route")}

    assert home != route
    assert ("1", "Home") in home
    assert ("A", "Apply") in route


def test_app_source_keeps_detail_panel_but_no_persistent_inspector() -> None:
    source = Path(tui_app.__file__).read_text(encoding="utf-8")

    assert '#detail-panel' in source
    assert 'yield Static("Inspector"' not in source

