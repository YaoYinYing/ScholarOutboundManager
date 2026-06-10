"""Settings screen — structured config editor."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button
from textual.widgets import Input
from textual.widgets import Static
from textual.widgets import Switch


class SettingsScreen(Screen[None]):
    """Config editor with allowlisted fields, save/undo/diff, and test-fetch."""

    CSS = """
    SettingsScreen {
        align: center top;
    }
    #settings-container {
        width: 100%;
        padding: 1 2;
    }
    #settings-title {
        text-style: bold;
        padding-bottom: 1;
    }
    .settings-section {
        padding-top: 1;
        padding-bottom: 1;
    }
    .section-header {
        text-style: bold;
        color: $accent;
    }
    .field-row {
        padding-left: 2;
        height: 3;
    }
    .field-label {
        width: 20;
        padding-top: 1;
    }
    .field-input {
        width: 40;
    }
    #settings-diff {
        padding-top: 1;
        color: $text-muted;
        height: auto;
    }
    #settings-message {
        color: $success;
        padding-top: 1;
    }
    """

    def __init__(self, services) -> None:
        super().__init__()
        self._services = services
        self.state = services.snapshot()

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-container"):
            yield Static("Settings", id="settings-title")

            yield Static("Config", classes="section-header")
            with Horizontal(classes="field-row"):
                yield Static("Config path:", classes="field-label")
                yield Input(str(self.state.config_path), id="fld-config-path", disabled=True, classes="field-input")

            yield Static("Subscription", classes="section-header")
            with Horizontal(classes="field-row"):
                yield Static("URL:", classes="field-label")
                yield Input(self.state.subscription_url_masked, id="fld-subscription-url", password=True, classes="field-input")
            with Horizontal(classes="field-row"):
                yield Static("User-Agent:", classes="field-label")
                yield Input(self.state.subscription_user_agent, id="fld-user-agent", classes="field-input")

            yield Static("Runtime", classes="section-header")
            with Horizontal(classes="field-row"):
                yield Static("Xray binary:", classes="field-label")
                yield Input(self.state.xray_binary_path, id="fld-xray-path", classes="field-input")
            with Horizontal(classes="field-row"):
                yield Static("User data dir:", classes="field-label")
                yield Input(str(self.state.user_data_paths.root), id="fld-user-data-dir", classes="field-input")

            yield Static("Safety", classes="section-header")
            with Horizontal(classes="field-row"):
                yield Static("Fail closed:", classes="field-label")
                yield Switch(value=self.state.fail_closed, id="sw-fail-closed")
            with Horizontal(classes="field-row"):
                yield Static("Hysteria2 (experimental):", classes="field-label")
                yield Switch(value=self.state.experimental_hysteria2, id="sw-hysteria2")
            with Horizontal(classes="field-row"):
                yield Static("Service name:", classes="field-label")
                yield Input(self.state.service_name, id="fld-service-name", classes="field-input")
            with Horizontal(classes="field-row"):
                yield Static("Probe concurrency:", classes="field-label")
                yield Input(str(self.state.probe_concurrency), id="fld-concurrency", classes="field-input")

            with Horizontal(id="settings-actions"):
                yield Button("Save", id="btn-save")
                yield Button("Undo", id="btn-undo")
                yield Button("Show Diff", id="btn-diff")
                yield Button("Test Fetch", id="btn-test-fetch")
                yield Button("Back", id="btn-back")

            yield Static("", id="settings-diff")
            yield Static("", id="settings-message")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "btn-save":
            self._save()
        elif bid == "btn-undo":
            self._undo()
        elif bid == "btn-diff":
            self._show_diff()
        elif bid == "btn-test-fetch":
            self._test_fetch()
        elif bid == "btn-back":
            self.dismiss()

    def _save(self) -> None:
        try:
            # Collect field values
            fields = {
                "user_data_dir": self.query_one("#fld-user-data-dir", Input).value,
                "subscription.user_agent": self.query_one("#fld-user-agent", Input).value,
                "probe.concurrency": self.query_one("#fld-concurrency", Input).value,
                "xray.binary_path": self.query_one("#fld-xray-path", Input).value,
            }
            for key, value in fields.items():
                self._services.update_config_field(key, value)
            self.state = self._services.snapshot()
            self.query_one("#settings-message", Static).update("Saved.")
        except Exception as exc:
            self.query_one("#settings-message", Static).update(f"Save failed: {exc}")

    def _undo(self) -> None:
        try:
            self._services.undo_config()
            self.state = self._services.snapshot()
            self.query_one("#settings-message", Static).update("Undo complete.")
        except Exception as exc:
            self.query_one("#settings-message", Static).update(f"Undo failed: {exc}")

    def _show_diff(self) -> None:
        diff = self.state.config_redacted_diff
        self.query_one("#settings-diff", Static).update(diff or "No pending redacted diff.")

    def _test_fetch(self) -> None:
        try:
            result = self._services.fetch_subscription()
            self.state = self._services.snapshot()
            msg = f"Fetch: {result.summary}" if result.succeeded else f"Fetch failed: {result.summary}"
            self.query_one("#settings-message", Static).update(msg)
        except Exception as exc:
            self.query_one("#settings-message", Static).update(f"Fetch error: {exc}")
