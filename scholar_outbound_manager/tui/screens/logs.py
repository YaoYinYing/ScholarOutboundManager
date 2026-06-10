"""Logs screen — action history, snapshots, and troubleshooting."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button
from textual.widgets import DataTable
from textual.widgets import RichLog
from textual.widgets import Static

from scholar_outbound_manager.tui.view_models import build_logs_view_model


class LogsScreen(Screen[None]):
    """Action history, artifact snapshots, rollback, and troubleshooting."""

    CSS = """
    LogsScreen {
        align: center top;
    }
    #logs-container {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    #logs-title {
        text-style: bold;
        padding-bottom: 1;
    }
    #logs-toolbar {
        height: 3;
        padding-bottom: 1;
    }
    .logs-section-label {
        text-style: bold;
        color: $accent;
        padding-top: 1;
        padding-bottom: 1;
    }
    #logs-action-table {
        height: 10;
        width: 100%;
    }
    #logs-snapshot-table {
        height: 10;
        width: 100%;
    }
    #logs-warning {
        height: auto;
        padding-top: 1;
        color: $warning;
    }
    #logs-message {
        padding-top: 1;
        color: $success;
    }
    """

    def __init__(self, services) -> None:
        super().__init__()
        self._services = services
        self.state = services.snapshot()

    def compose(self) -> ComposeResult:
        with Vertical(id="logs-container"):
            yield Static("Logs", id="logs-title")
            with Horizontal(id="logs-toolbar"):
                yield Button("Artifact Check", id="btn-check")
                yield Button("Create Snapshot", id="btn-snapshot")
                yield Button("Rollback", id="btn-rollback")
                yield Button("Refresh", id="btn-refresh")
                yield Button("Back", id="btn-back")
            yield Static("Action History", classes="logs-section-label")
            yield DataTable(id="logs-action-table")
            yield Static("Snapshots", classes="logs-section-label")
            yield DataTable(id="logs-snapshot-table")
            yield RichLog(id="logs-rich-log", wrap=True, markup=False)
            yield Static("", id="logs-message")

    def on_mount(self) -> None:
        action_table = self.query_one("#logs-action-table", DataTable)
        action_table.add_columns("Action", "Status", "Summary")
        snapshot_table = self.query_one("#logs-snapshot-table", DataTable)
        snapshot_table.add_columns("Snapshot ID", "Reason")
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "btn-check":
            self._artifact_check()
        elif bid == "btn-snapshot":
            self._create_snapshot()
        elif bid == "btn-rollback":
            self._rollback()
        elif bid == "btn-refresh":
            self.state = self._services.snapshot()
            self._refresh()
        elif bid == "btn-back":
            self.dismiss()

    def _artifact_check(self) -> None:
        try:
            result = self._services.check_artifact_consistency()
            self.query_one("#logs-rich-log", RichLog).write(str(result))
        except Exception as exc:
            self.query_one("#logs-message", Static).update(f"Check failed: {exc}")

    def _create_snapshot(self) -> None:
        try:
            snap = self._services.create_snapshot("manual_tui_snapshot")
            self.state = self._services.snapshot()
            self._refresh()
            self.query_one("#logs-message", Static).update(f"Created snapshot {snap.snapshot_id}.")
        except Exception as exc:
            self.query_one("#logs-message", Static).update(f"Snapshot failed: {exc}")

    def _rollback(self) -> None:
        try:
            result = self._services.rollback_snapshot()
            self.state = self._services.snapshot()
            self._refresh()
            self.query_one("#logs-message", Static).update(result.message)
        except Exception as exc:
            self.query_one("#logs-message", Static).update(f"Rollback failed: {exc}")

    def _refresh(self) -> None:
        vm = build_logs_view_model(self.state)

        action_table = self.query_one("#logs-action-table", DataTable)
        action_table.clear()
        for row in vm.action_rows:
            action_table.add_row(*row)

        snapshot_table = self.query_one("#logs-snapshot-table", DataTable)
        snapshot_table.clear()
        for row in vm.snapshot_rows:
            snapshot_table.add_row(*row)

        rich_log = self.query_one("#logs-rich-log", RichLog)
        rich_log.clear()
        for line in vm.rollback_warning:
            rich_log.write(line)

        if vm.last_action_summary:
            self.query_one("#logs-message", Static).update(f"Latest: {vm.last_action_summary}")
