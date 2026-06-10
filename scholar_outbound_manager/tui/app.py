"""TUI entry point for ScholarOutboundManager.

scholar-outbound-manager tui [config.yaml]

If config doesn't exist, the first-run wizard creates a template.
Otherwise, the Home screen opens with the 5-tab workflow.

Module-level imports avoid Textual so tests can import helpers without
a Textual installation.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """Build the TUI-specific argument parser."""
    parser = argparse.ArgumentParser(prog="scholar-outbound-manager-tui")
    parser.add_argument("config", nargs="?", default="config.yaml")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Textual TUI entry point."""
    args = build_parser().parse_args(argv)

    # Lazy-import Textual so the module is importable without it installed
    try:
        from textual.app import App as _TextualApp
        from textual.app import ComposeResult
        from textual.widgets import Header
    except ModuleNotFoundError:
        print('Textual TUI is not installed. Install with:\npip install "ScholarOutboundManager[tui]"')
        return 1

    from scholar_outbound_manager.tui.services import SessionServices

    config_path = Path(args.config)
    services = SessionServices(config_path)

    # Lazy screen imports
    from scholar_outbound_manager.tui.screens.wizard import WizardScreen
    from scholar_outbound_manager.tui.screens.home import HomeScreen
    from scholar_outbound_manager.tui.screens.settings import SettingsScreen
    from scholar_outbound_manager.tui.screens.testing import TestingScreen
    from scholar_outbound_manager.tui.screens.route import RouteScreen
    from scholar_outbound_manager.tui.screens.logs import LogsScreen

    class ScholarTui(_TextualApp[None]):
        """Config-centered TUI with Home, Settings, Testing, Route, and Logs screens."""

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("1", "nav_home", "Home"),
            ("2", "nav_settings", "Settings"),
            ("3", "nav_testing", "Testing"),
            ("4", "nav_route", "Route"),
            ("5", "nav_logs", "Logs"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self.services = services

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)

        def on_mount(self) -> None:
            if not config_path.exists():
                self.push_screen(WizardScreen(self.services))
            else:
                self.push_screen(HomeScreen(self.services))

        def action_nav_home(self) -> None:
            self._switch_to(HomeScreen)

        def action_nav_settings(self) -> None:
            self._switch_to(SettingsScreen)

        def action_nav_testing(self) -> None:
            self._switch_to(TestingScreen)

        def action_nav_route(self) -> None:
            self._switch_to(RouteScreen)

        def action_nav_logs(self) -> None:
            self._switch_to(LogsScreen)

        def _switch_to(self, screen_cls) -> None:
            while len(self.screen_stack) > 1:
                self.pop_screen()
            self.switch_screen(screen_cls(self.services))

    ScholarTui().run()
    return 0
