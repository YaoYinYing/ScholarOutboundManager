"""Screen and layout descriptors for the optional TUI."""

from __future__ import annotations

from scholar_outbound_manager.tui.workflow import MAIN_TABS


def build_ascii_tab_strip() -> str:
    """Build one copy-friendly tab label strip for docs and simple UI output."""
    return " | ".join(MAIN_TABS)

