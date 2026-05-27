"""Tests for optional TUI imports and helpers."""

from __future__ import annotations

from scholar_outbound_manager.tui import view_model


def test_core_tui_view_model_import_does_not_require_textual() -> None:
    """Import the TUI view model without Textual installed."""
    assert hasattr(view_model, "build_candidate_table_rows")
