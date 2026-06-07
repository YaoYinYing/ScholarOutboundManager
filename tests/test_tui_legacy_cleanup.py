from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from scholar_outbound_manager.tui import app as tui_app
from scholar_outbound_manager.tui.state import AppState


def test_app_state_has_no_workflow_state_field() -> None:
    assert "workflow_state" not in {field.name for field in fields(AppState)}


def test_live_render_path_does_not_read_workflow_state() -> None:
    source = Path(tui_app.__file__).read_text(encoding="utf-8")
    render_block = source[source.index("def render_state"):source.index("def _safe_refresh_ui")]

    assert "workflow_state" not in render_block
    assert "render_tab_text(" not in render_block


def test_live_render_uses_no_persistent_inspector_and_no_old_debug_tabs() -> None:
    source = Path(tui_app.__file__).read_text(encoding="utf-8")

    assert 'yield Static("Inspector"' not in source
    assert "Overview" not in source[source.index("class ScholarOutboundWorkflowApp"):source.index("render_state")]

