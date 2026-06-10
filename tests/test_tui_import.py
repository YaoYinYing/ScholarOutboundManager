"""Tests for optional TUI imports and helpers."""

from __future__ import annotations

import sys

import scholar_outbound_manager
from scholar_outbound_manager.tui import view_model


def test_core_tui_view_model_import_does_not_require_textual() -> None:
    """Import the TUI view model (redaction helpers) without Textual installed."""
    assert hasattr(view_model, "redact_text")
    assert hasattr(view_model, "truncate_display_value")


def test_importing_core_package_does_not_import_textual() -> None:
    """Keep Textual out of the core package import path."""
    assert hasattr(scholar_outbound_manager, "__version__")
    assert "textual" not in sys.modules


def test_services_import_does_not_require_textual() -> None:
    """Import TUI services without Textual installed."""
    from scholar_outbound_manager.tui.services import SessionServices
    from scholar_outbound_manager.tui.services import SessionState
    assert SessionState is not None
    assert SessionServices is not None
