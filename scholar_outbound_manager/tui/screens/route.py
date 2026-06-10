"""Route screen — sidecar route editor and service controls."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button
from textual.widgets import DataTable
from textual.widgets import Input
from textual.widgets import Select
from textual.widgets import Static
from textual.widgets import Switch

from scholar_outbound_manager.tui.view_models import build_route_view_model


class RouteScreen(Screen[None]):
    """Route editor for the managed sidecar — routes, candidates, ports, and service."""

    CSS = """
    RouteScreen {
        align: center top;
    }
    #route-container {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    #route-toolbar {
        height: 3;
        padding-bottom: 1;
    }
    #route-table {
        height: 1fr;
        width: 100%;
    }
    #route-editor {
        height: auto;
        padding-top: 1;
        border: solid $primary;
        padding: 1;
    }
    .route-field-row {
        padding-left: 2;
        height: 3;
    }
    .route-field-label {
        width: 18;
        padding-top: 1;
    }
    .route-field-input {
        width: 30;
    }
    #route-message {
        padding-top: 1;
        color: $success;
    }
    #route-boundary {
        padding-top: 1;
        color: $text-muted;
    }
    """

    def __init__(self, services) -> None:
        super().__init__()
        self._services = services
        self.state = services.snapshot()
        self._syncing = False

    def compose(self) -> ComposeResult:
        with Vertical(id="route-container"):
            with Horizontal(id="route-toolbar"):
                yield Button("Add Route", id="btn-add")
                yield Button("Delete Route", id="btn-delete")
                yield Button("Choose Node", id="btn-choose")
                yield Button("Test Port", id="btn-test-port")
                yield Button("Apply", id="btn-apply")
                yield Button("Validate", id="btn-validate")
                yield Button("Back", id="btn-back")
            yield DataTable(id="route-table")
            with Vertical(id="route-editor"):
                yield Static("Route Editor", id="editor-title")
                with Horizontal(classes="route-field-row"):
                    yield Static("Name:", classes="route-field-label")
                    yield Input("", id="fld-route-name", classes="route-field-input")
                with Horizontal(classes="route-field-row"):
                    yield Static("Candidate:", classes="route-field-label")
                    yield Select([], prompt="Choose passed node", id="fld-route-candidate")
                with Horizontal(classes="route-field-row"):
                    yield Static("Listen host:", classes="route-field-label")
                    yield Input("127.0.0.1", id="fld-route-host", classes="route-field-input")
                with Horizontal(classes="route-field-row"):
                    yield Static("Listen port:", classes="route-field-label")
                    yield Input("19080", id="fld-route-port", classes="route-field-input")
                with Horizontal(classes="route-field-row"):
                    yield Static("Enabled:", classes="route-field-label")
                    yield Switch(value=True, id="sw-route-enabled")
            yield Static("", id="route-message")
            yield Static(
                "Only ScholarOutboundManager sidecar is managed. Production Xray/XrayR/x-ui is never modified.",
                id="route-boundary",
            )

    def on_mount(self) -> None:
        table = self.query_one("#route-table", DataTable)
        table.add_columns("On", "Name", "Candidate", "Region", "Protocol", "Host", "Port", "Port", "Validation")
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "btn-add":
            self._add()
        elif bid == "btn-delete":
            self._delete()
        elif bid == "btn-choose":
            self._choose_candidate()
        elif bid == "btn-test-port":
            self._test_port()
        elif bid == "btn-apply":
            self._apply()
        elif bid == "btn-validate":
            self._validate()
        elif bid == "btn-back":
            self.dismiss()

    def _add(self) -> None:
        msg = self._services.add_route_entry()
        self.state = self._services.snapshot()
        self._refresh()
        self.query_one("#route-message", Static).update(msg)

    def _delete(self) -> None:
        msg = self._services.delete_route_entry(self.state.route_selected_index)
        self.state = self._services.snapshot()
        self._refresh()
        self.query_one("#route-message", Static).update(msg)

    def _choose_candidate(self) -> None:
        select = self.query_one("#fld-route-candidate", Select)
        value = select.value
        if not isinstance(value, str) or not value:
            self.query_one("#route-message", Static).update("Choose a passed candidate first.")
            return
        entries = self.state.route_entries
        if entries and 0 <= self.state.route_selected_index < len(entries):
            route_id = entries[self.state.route_selected_index].route_id
            msg = self._services.choose_route_candidate(route_id, value)
            self.state = self._services.snapshot()
            self._refresh()
            self.query_one("#route-message", Static).update(msg)

    def _test_port(self) -> None:
        entries = self.state.route_entries
        if entries and 0 <= self.state.route_selected_index < len(entries):
            route_id = entries[self.state.route_selected_index].route_id
            try:
                result = self._services.test_route_port(route_id)
                self.state = self._services.snapshot()
                self._refresh()
                self.query_one("#route-message", Static).update(result.message)
            except Exception as exc:
                self.query_one("#route-message", Static).update(f"Port check failed: {exc}")

    def _apply(self) -> None:
        try:
            result = self._services.apply_routes()
            self.state = self._services.snapshot()
            self._refresh()
            self.query_one("#route-message", Static).update(
                f"Applied: {result.summary}" if result.succeeded else f"Apply failed: {result.summary}"
            )
        except Exception as exc:
            self.query_one("#route-message", Static).update(f"Apply failed: {exc}")

    def _validate(self) -> None:
        try:
            result = self._services.validate_sidecar()
            self.state = self._services.snapshot()
            self._refresh()
            self.query_one("#route-message", Static).update(
                f"Validation: {result.summary}" if result.succeeded else f"Validation failed: {result.summary}"
            )
        except Exception as exc:
            self.query_one("#route-message", Static).update(f"Validate failed: {exc}")

    def _refresh(self) -> None:
        vm = build_route_view_model(self.state)
        table = self.query_one("#route-table", DataTable)
        table.clear()
        for row in vm.table.rows:
            table.add_row(
                row.enabled, row.name, row.candidate, row.region,
                row.protocol, row.host, row.port, row.port_status, row.validation,
            )

        self._syncing = True
        try:
            entry = vm.selected_entry
            self.query_one("#fld-route-name", Input).value = str(entry.get("name", "Scholar"))
            self.query_one("#fld-route-host", Input).value = str(entry.get("listen_host", "127.0.0.1"))
            self.query_one("#fld-route-port", Input).value = str(entry.get("listen_port", "19080"))
            self.query_one("#sw-route-enabled", Switch).value = bool(entry.get("enabled", True))

            select = self.query_one("#fld-route-candidate", Select)
            select.set_options(vm.candidate_options)
            if entry.get("candidate_id"):
                select.value = entry["candidate_id"]
            else:
                select.clear()
            select.disabled = not vm.candidate_selector_enabled
        finally:
            self._syncing = False

        self.query_one("#btn-apply", Button).disabled = not vm.apply_available
