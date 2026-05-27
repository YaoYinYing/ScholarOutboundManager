"""Textual-independent view-model helpers for the optional TUI."""

from __future__ import annotations

from scholar_outbound_manager.selection import CandidateCatalogEntry


def build_candidate_table_rows(entries: list[CandidateCatalogEntry]) -> list[dict[str, object]]:
    """Build secret-safe table rows for TUI rendering."""
    return [
        {
            "index": entry.index,
            "candidate_id": entry.candidate_id,
            "protocol": entry.protocol,
            "passed": entry.passed,
            "stage": entry.scholar_stage,
            "home_status": entry.home_status,
            "query_status": entry.query_status,
            "failure_marker_count": entry.failure_marker_count,
            "tags": list(entry.tags),
        }
        for entry in entries
    ]
