"""Tests for Textual-safe TUI tab identifier helpers."""

from __future__ import annotations

from scholar_outbound_manager.tui import app as tui_app
from scholar_outbound_manager.tui.workflow import MAIN_TABS


def test_textual_safe_id_for_dashboard() -> None:
    """Keep simple names readable after sanitization."""
    assert tui_app._textual_safe_id("Dashboard") == "dashboard"


def test_textual_safe_id_for_fetch_probe() -> None:
    """Replace spaces and punctuation with hyphens."""
    assert tui_app._textual_safe_id("Fetch & Probe") == "fetch-probe"


def test_textual_safe_id_for_restart_validate() -> None:
    """Collapse invalid punctuation runs into one hyphen."""
    assert tui_app._textual_safe_id("Restart & Validate") == "restart-validate"


def test_textual_safe_id_for_leading_number() -> None:
    """Prefix ids that would otherwise begin with a digit."""
    assert tui_app._textual_safe_id("123 Test") == "tab-123-test"


def test_textual_safe_id_for_blank_value() -> None:
    """Fallback to one safe default id when the title is empty."""
    assert tui_app._textual_safe_id("   ") == "tab"


def test_build_tab_specs_make_duplicate_ids_unique() -> None:
    """Disambiguate repeated or slug-colliding tab titles by occurrence."""
    specs, initial_id = tui_app._build_tab_specs(["Fetch & Probe", "Fetch-Probe", "Fetch & Probe"])

    assert initial_id == "fetch-probe"
    assert [spec["id"] for spec in specs] == ["fetch-probe", "fetch-probe-2", "fetch-probe-3"]


def test_workflow_tabs_all_produce_textual_safe_ids() -> None:
    """Ensure current workflow tabs never emit raw invalid ids."""
    specs, initial_id = tui_app._build_tab_specs(list(MAIN_TABS))

    assert initial_id == "dashboard"
    assert all(spec["id"] for spec in specs)
    assert all(spec["id"].replace("-", "").replace("_", "").isalnum() for spec in specs)
    assert specs[2]["title"] == "Fetch & Probe"
    assert specs[2]["id"] == "fetch-probe"


def test_build_tab_specs_do_not_use_raw_tab_label_as_id() -> None:
    """Keep human-readable titles while separating internal ids."""
    specs, _ = tui_app._build_tab_specs(["Dashboard", "Fetch & Probe"])

    assert specs[0] == {"title": "Dashboard", "id": "dashboard"}
    assert specs[1] == {"title": "Fetch & Probe", "id": "fetch-probe"}
