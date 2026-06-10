"""Home screen — operational summary with status cards."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button
from textual.widgets import Static

from scholar_outbound_manager.tui.view_models import build_home_view_model


class HomeScreen(Screen[None]):
    """Operational summary with subscription, testing, route, and sidecar cards."""

    CSS = """
    HomeScreen {
        align: center top;
    }
    #home-container {
        width: 100%;
        height: auto;
        padding: 1 2;
    }
    #home-title {
        text-style: bold;
        padding-bottom: 1;
    }
    #home-meta {
        padding-bottom: 1;
        color: $text-muted;
    }
    #home-cards {
        height: auto;
    }
    .home-card {
        width: 1fr;
        height: auto;
        border: solid $primary;
        padding: 1;
        margin: 1;
    }
    .card-title {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    .card-row {
        padding-left: 1;
    }
    #home-next {
        padding-top: 2;
        text-style: bold;
    }
    """

    def __init__(self, services) -> None:
        super().__init__()
        self._services = services
        self.state = services.snapshot()

    def compose(self) -> ComposeResult:
        yield Static("Scholar Outbound Manager", id="home-title")
        yield Static("", id="home-meta")
        with Horizontal(id="home-cards"):
            for i in range(4):
                with Vertical(classes="home-card"):
                    yield Static("", classes="card-title", id=f"card-{i}-title")
                    yield Static("", classes="card-body", id=f"card-{i}-body")
        yield Static("", id="home-next")
        with Horizontal(id="home-actions"):
            yield Button("Settings", id="btn-settings")
            yield Button("Testing", id="btn-testing")
            yield Button("Route", id="btn-route")
            yield Button("Logs", id="btn-logs")
            yield Button("Refresh", id="btn-refresh")

    def on_mount(self) -> None:
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "btn-settings":
            self.app.push_screen(SettingsScreen(self._services))
        elif bid == "btn-testing":
            self.app.push_screen(TestingScreen(self._services))
        elif bid == "btn-route":
            self.app.push_screen(RouteScreen(self._services))
        elif bid == "btn-logs":
            self.app.push_screen(LogsScreen(self._services))
        elif bid == "btn-refresh":
            self.state = self._services.snapshot()
            self._refresh()

    def _refresh(self) -> None:
        vm = build_home_view_model(self.state)
        self.query_one("#home-meta", Static).update(
            f"Config: {vm.config_path}    User data: {vm.user_data_dir}"
        )
        for i, card in enumerate(vm.cards):
            self.query_one(f"#card-{i}-title", Static).update(card.title)
            self.query_one(f"#card-{i}-body", Static).update(
                "\n".join(f"  {label}: {value}" for label, value in card.rows)
            )
        self.query_one("#home-next", Static).update(f"Next: {vm.next_action}")


# Lazy import to avoid circular dependency
from scholar_outbound_manager.tui.screens.settings import SettingsScreen
from scholar_outbound_manager.tui.screens.testing import TestingScreen
from scholar_outbound_manager.tui.screens.route import RouteScreen
from scholar_outbound_manager.tui.screens.logs import LogsScreen
