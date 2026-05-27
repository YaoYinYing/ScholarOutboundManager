"""Optional Textual TUI entry point and helpers."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from scholar_outbound_manager.selection import build_candidate_catalog
from scholar_outbound_manager.selection import build_selected_candidate_artifact
from scholar_outbound_manager.selection import load_candidate_payload
from scholar_outbound_manager.selection import select_candidate_by_index
from scholar_outbound_manager.selection import write_selected_candidate_artifact
from scholar_outbound_manager.selection_policy import SelectionPolicyOptions
from scholar_outbound_manager.selection_policy import select_candidate_with_policy
from scholar_outbound_manager.tui.view_model import build_candidate_table_rows


def build_parser() -> argparse.ArgumentParser:
    """Build the TUI-specific parser."""
    parser = argparse.ArgumentParser(prog="scholar-outbound-manager-tui")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--output", default="state_data/selected_candidate.json")
    parser.add_argument("--strategy", default="auto", choices=("auto", "manual", "geo_nearest", "geo-nearest", "region_hint", "region-hint", "first"))
    parser.add_argument("--geo-cache", default="state_data/geo/candidate_geo_cache.json")
    parser.add_argument("--host-geo", default="state_data/geo/host_geo.json")
    parser.add_argument("--preferred-region-hint")
    parser.add_argument("--prefer-geo", dest="prefer_geo", action="store_true", default=True)
    parser.add_argument("--no-prefer-geo", dest="prefer_geo", action="store_false")
    return parser


def load_dashboard_state(
    *,
    candidates_path: str | Path,
    output_path: str | Path,
    strategy: str = "auto",
    geo_cache_path: str = "state_data/geo/candidate_geo_cache.json",
    host_geo_path: str = "state_data/geo/host_geo.json",
    prefer_geo: bool = True,
    preferred_region_hint: str | None = None,
) -> dict[str, object]:
    """Load the redacted dashboard state without importing Textual."""
    payload = load_candidate_payload(candidates_path)
    entries = build_candidate_catalog(payload)
    rows = build_candidate_table_rows(entries)
    _, _, decision = select_candidate_with_policy(
        payload,
        SelectionPolicyOptions(
            strategy=strategy,
            geo_cache_path=geo_cache_path,
            host_geo_path=host_geo_path,
            prefer_geo=prefer_geo,
            preferred_region_hint=preferred_region_hint,
            prefer_region_hint=preferred_region_hint is not None,
            fallback_to_first=True,
        ),
    )
    return {
        "candidates_path": str(candidates_path),
        "output_path": str(output_path),
        "rows": rows,
        "selected_index": decision.selected_index,
        "selected_candidate_id": decision.selected_candidate_id,
        "selection_method": decision.method,
        "selection_reason": decision.reason,
    }


def save_selection_from_index(
    *,
    candidates_path: str | Path,
    selected_index: int,
    output_path: str | Path,
) -> dict[str, object]:
    """Save one selected-candidate artifact from the currently highlighted row."""
    payload = load_candidate_payload(candidates_path)
    record = select_candidate_by_index(payload, selected_index)
    artifact = build_selected_candidate_artifact(record, selection_method="index")
    write_selected_candidate_artifact(output_path, artifact)
    return artifact


def main(argv: Sequence[str] | None = None) -> int:
    """Run the optional Textual TUI entry point."""
    args = build_parser().parse_args(argv)
    try:
        from textual.app import App
        from textual.app import ComposeResult
        from textual.binding import Binding
        from textual.containers import Horizontal
        from textual.widgets import DataTable
        from textual.widgets import Footer
        from textual.widgets import Header
        from textual.widgets import Static
    except ModuleNotFoundError as exc:
        if exc.name != "textual":
            raise
        print('Textual TUI is not installed. Install with:\npip install "ScholarOutboundManager[tui]"')
        return 1

    dashboard = load_dashboard_state(
        candidates_path=args.candidates,
        output_path=args.output,
        strategy=args.strategy,
        geo_cache_path=args.geo_cache,
        host_geo_path=args.host_geo,
        prefer_geo=args.prefer_geo,
        preferred_region_hint=args.preferred_region_hint,
    )

    class ScholarOutboundManagerTui(App[None]):
        """Minimal read-mostly Textual UI for redacted candidate selection."""

        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("r", "reload", "Reload"),
            Binding("s", "save_selection", "Save Selection"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self.dashboard = dict(dashboard)

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal():
                yield DataTable(id="candidate-table")
                yield Static("", id="status-panel")
            yield Footer()

        def on_mount(self) -> None:
            self._load_table()
            self._render_status("Loaded redacted candidate catalog.")

        def action_reload(self) -> None:
            self.dashboard = load_dashboard_state(
                candidates_path=args.candidates,
                output_path=args.output,
                strategy=args.strategy,
                geo_cache_path=args.geo_cache,
                host_geo_path=args.host_geo,
                prefer_geo=args.prefer_geo,
                preferred_region_hint=args.preferred_region_hint,
            )
            self._load_table()
            self._render_status("Reloaded catalog.")

        def action_save_selection(self) -> None:
            table = self.query_one("#candidate-table", DataTable)
            cursor_row = table.cursor_row if table.cursor_row is not None else int(self.dashboard["selected_index"])
            artifact = save_selection_from_index(
                candidates_path=args.candidates,
                selected_index=int(cursor_row),
                output_path=args.output,
            )
            self._render_status(
                "Saved selection "
                f"{artifact['selected_candidate_id']} to {args.output}."
            )

        def _load_table(self) -> None:
            table = self.query_one("#candidate-table", DataTable)
            table.clear(columns=True)
            table.add_columns("index", "label", "region", "candidate_id", "protocol", "passed", "stage", "home", "query", "markers")
            for row in self.dashboard["rows"]:
                table.add_row(
                    str(row["index"]),
                    str(row["label"]),
                    "" if row["region"] is None else str(row["region"]),
                    str(row["candidate_id"]),
                    str(row["protocol"]),
                    "" if row["passed"] is None else ("yes" if row["passed"] else "no"),
                    "" if row["stage"] is None else str(row["stage"]),
                    "" if row["home_status"] is None else str(row["home_status"]),
                    "" if row["query_status"] is None else str(row["query_status"]),
                    str(row["failure_marker_count"]),
                )
            table.cursor_type = "row"
            if self.dashboard["rows"]:
                table.move_cursor(row=int(self.dashboard["selected_index"]), column=0)

        def _render_status(self, prefix: str) -> None:
            panel = self.query_one("#status-panel", Static)
            panel.update(
                "\n".join(
                    [
                        prefix,
                        f"Selected: {self.dashboard['selected_candidate_id']}",
                        f"Method: {self.dashboard['selection_method']}",
                        f"Reason: {self.dashboard['selection_reason']}",
                        "Keys: q quit, r reload, s save selection",
                    ]
                )
            )

    ScholarOutboundManagerTui().run()
    return 0
