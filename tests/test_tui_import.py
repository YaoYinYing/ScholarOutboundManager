"""Tests for optional TUI imports and helpers."""

from __future__ import annotations

import sys

import scholar_outbound_manager
from scholar_outbound_manager.tui import view_model


def test_core_tui_view_model_import_does_not_require_textual() -> None:
    """Import the TUI view model without Textual installed."""
    assert hasattr(view_model, "build_candidate_table_rows")


def test_importing_core_package_does_not_import_textual() -> None:
    """Keep Textual out of the core package import path."""
    assert hasattr(scholar_outbound_manager, "__version__")
    assert "textual" not in sys.modules
