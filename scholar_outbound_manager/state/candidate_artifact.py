"""Sensitive candidate artifact construction helpers."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.fetcher import FetchErrorRecord
from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.state.atomic_write import atomic_write_json


def build_candidate_artifact(
    candidates: list[CandidateProxy],
    *,
    source_count: int,
    fetched_count: int,
    disabled_count: int,
    failed_count: int,
    total_bytes: int,
    parsed_count: int,
    unsupported_count: int,
    fetch_errors: list[FetchErrorRecord] | None = None,
) -> dict[str, object]:
    """Build one sensitive candidate artifact payload."""
    return {
        "schema_version": 1,
        "sensitive": True,
        "description": "This file contains proxy candidates and must not be committed.",
        "source_count": source_count,
        "fetched_count": fetched_count,
        "disabled_count": disabled_count,
        "failed_count": failed_count,
        "total_bytes": total_bytes,
        "parsed_count": parsed_count,
        "unsupported_count": unsupported_count,
        "fetch_errors": [
            {
                "source_name": error.source_name,
                "category": error.category,
                "message": error.message,
                "http_status": error.http_status,
            }
            for error in (fetch_errors or [])
        ],
        "candidates": [candidate.to_dict() for candidate in candidates],
    }


def write_candidate_artifact(path: str | Path, payload: dict[str, object]) -> None:
    """Write one sensitive candidate artifact as JSON."""
    atomic_write_json(path, payload)
