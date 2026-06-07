from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.tui import app as tui_app


def test_testing_layout_uses_main_workspace_widgets() -> None:
    source = Path(tui_app.__file__).read_text(encoding="utf-8")

    assert '#testing-runtime-header' in source
    assert 'yield DataTable(id="testing-table")' in source
    assert 'yield RichLog(id="testing-log"' in source
    assert '#testing-table { height: 1fr; width: 1fr; }' in source
    assert 'yield Static("Inspector"' not in source


def test_testing_summary_labels_are_explicit() -> None:
    lines = tui_app._render_testing_summary_lines(
        {
            "summary": {
                "total_candidates": 47,
                "testable_candidates": 30,
                "visible_rows": 47,
                "attempted": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "pending": 30,
                "running": 0,
                "stale": 0,
                "experimental_disabled": 17,
                "table_scope": "all_candidates",
            }
        }
    )

    rendered = "\n".join(lines)
    assert "Total 47" in rendered
    assert "Testable 30" in rendered
    assert "Visible 47" in rendered
    assert "Experimental disabled 17" in rendered
