"""Lightweight TUI app structure tests."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.tui import app as tui_app


def test_tui_app_build_parser_config_default() -> None:
    parser = tui_app.build_parser()
    args = parser.parse_args([])
    assert args.config == "config.yaml"


def test_tui_app_build_parser_custom_config() -> None:
    parser = tui_app.build_parser()
    args = parser.parse_args(["custom.yaml"])
    assert args.config == "custom.yaml"


def test_app_source_has_no_legacy_debug_tabs() -> None:
    source = Path(tui_app.__file__).read_text(encoding="utf-8")

    # Old debug-tab renderer is gone
    assert "render_tab_text" not in source
    # Old 9-tab structure is gone
    assert "Dashboard" not in source
    # New screen-based architecture
    assert "WizardScreen" in source
    assert "HomeScreen" in source
