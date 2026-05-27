"""Tests for TUI view-model helpers."""

from __future__ import annotations

from scholar_outbound_manager.selection import CandidateCatalogEntry
from scholar_outbound_manager.tui.view_model import build_candidate_table_rows


def test_build_candidate_table_rows_hides_secrets() -> None:
    """Render only redacted row fields for TUI use."""
    rows = build_candidate_table_rows(
        [
            CandidateCatalogEntry(
                index=0,
                candidate_id="candidate-001",
                protocol="vless",
                source_name="fixture",
                supported=True,
                scholar_stage="full_access",
                passed=True,
                home_status=200,
                query_status=200,
                checked_at="2026-05-27T00:00:00Z",
                failure_marker_count=0,
                failure_markers=[],
                latency_ms=10,
                tags=["scholar"],
            )
        ]
    )

    rendered = str(rows[0])
    assert rows[0]["candidate_id"] == "candidate-001"
    assert "address" not in rendered
    assert "raw_uri" not in rendered
    assert "public_key" not in rendered
