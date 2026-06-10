"""Testing screen — fetch subscriptions and probe candidate nodes."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button
from textual.widgets import DataTable
from textual.widgets import ProgressBar
from textual.widgets import RichLog
from textual.widgets import Static

from scholar_outbound_manager.tui.view_models import build_testing_view_model


class TestingScreen(Screen[None]):
    """Node testing workbench with fetch, probe, and candidate inspection."""

    CSS = """
    TestingScreen {
        align: center top;
    }
    #testing-container {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    #testing-banner {
        padding-bottom: 1;
        color: $text-muted;
        height: auto;
    }
    #testing-toolbar {
        height: 3;
        padding-bottom: 1;
    }
    #testing-summary {
        height: auto;
        padding-bottom: 1;
        color: $text-muted;
    }
    #testing-table {
        height: 1fr;
        width: 100%;
    }
    #testing-inspector {
        height: auto;
        padding-top: 1;
        border: solid $primary;
    }
    #testing-log {
        height: 8;
    }
    """

    def __init__(self, services) -> None:
        super().__init__()
        self._services = services
        self.state = services.snapshot()

    def compose(self) -> ComposeResult:
        with Vertical(id="testing-container"):
            yield Static(
                "Fetch/Test are live network operations. They write local artifacts under user_data_dir. "
                "They do not modify production Xray/XrayR/x-ui.",
                id="testing-banner",
            )
            with Horizontal(id="testing-toolbar"):
                yield Button("Fetch Subscription", id="btn-fetch")
                yield Button("Test Nodes", id="btn-probe")
                yield Button("Retest Failed", id="btn-retest", disabled=True)
                yield Button("Stop", id="btn-stop", disabled=True)
                yield Button("Back", id="btn-back")
            yield ProgressBar(total=100, id="testing-progress")
            yield Static("", id="testing-summary")
            yield DataTable(id="testing-table")
            with Vertical(id="testing-inspector"):
                yield Static("Selected candidate", id="inspector-title")
                yield Static("", id="inspector-body")
            yield RichLog(id="testing-log", wrap=True, markup=False)

    def on_mount(self) -> None:
        table = self.query_one("#testing-table", DataTable)
        table.add_columns("", "#", "Region", "Label", "Protocol", "Latency", "Home", "Query", "Stage", "Markers")
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "btn-fetch":
            self._fetch()
        elif bid == "btn-probe":
            self._probe()
        elif bid == "btn-back":
            self.dismiss()

    def _fetch(self) -> None:
        try:
            result = self._services.fetch_subscription()
            self.state = self._services.snapshot()
            self._refresh()
            self.query_one("#testing-log", RichLog).write(
                f"[green]OK[/green] {result.summary}" if result.succeeded else f"[red]FAIL[/red] {result.summary}"
            )
        except Exception as exc:
            self.query_one("#testing-log", RichLog).write(f"[red]Error: {exc}[/red]")

    def _probe(self) -> None:
        try:
            result = self._services.probe_candidates()
            self.state = self._services.snapshot()
            self._refresh()
            self.query_one("#testing-log", RichLog).write(
                f"[green]OK[/green] {result.summary}" if result.succeeded else f"[red]FAIL[/red] {result.summary}"
            )
        except Exception as exc:
            self.query_one("#testing-log", RichLog).write(f"[red]Error: {exc}[/red]")

    def _refresh(self) -> None:
        vm = build_testing_view_model(self.state)
        self.query_one("#testing-summary", Static).update(
            f"Total: {vm.candidate_count} | Supported: {vm.supported_count} | "
            f"Tested: {vm.attempted_count} | Passed: {vm.passed_count} | Failed: {vm.failed_count} | "
            f"Query blocked: {vm.query_blocked_count} | Experimental disabled: {vm.experimental_disabled_count}"
        )
        self.query_one("#testing-progress", ProgressBar).update(
            total=max(vm.progress_total, 1), progress=vm.progress_current
        )

        table = self.query_one("#testing-table", DataTable)
        table.clear()
        for row in vm.table.rows:
            table.add_row(
                row.status_icon, str(row.index), row.region, row.label,
                row.protocol, row.latency, row.home, row.query, row.stage, row.markers,
            )

        self.query_one("#btn-fetch", Button).disabled = not vm.can_fetch
        self.query_one("#btn-probe", Button).disabled = not vm.can_probe

        inspector_lines = [f"  {k}: {v}" for k, v in vm.inspector.items()]
        self.query_one("#inspector-body", Static).update("\n".join(inspector_lines) if inspector_lines else "  No candidate selected.")
