"""Sensitive candidate artifact construction helpers."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager import __version__
from scholar_outbound_manager.fetcher import FetchErrorRecord
from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.state.artifact_lineage import ArtifactLineage
from scholar_outbound_manager.state.artifact_lineage import artifact_lineage_to_dict
from scholar_outbound_manager.state.artifact_lineage import generate_run_id


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
    run_id: str | None = None,
    created_at: str | None = None,
    source_subscription_hash: str | None = None,
) -> dict[str, object]:
    """Build one sensitive candidate artifact payload."""
    lineage = artifact_lineage_to_dict(
        ArtifactLineage(
            artifact_type="candidates",
            run_id=run_id or generate_run_id("fetch"),
            created_at=created_at or _utc_now_iso8601(),
            source_subscription_hash=source_subscription_hash,
            tool_version=__version__,
        )
    )
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
        **lineage,
    }


def write_candidate_artifact(path: str | Path, payload: dict[str, object]) -> None:
    """Write one sensitive candidate artifact as JSON."""
    atomic_write_json(path, payload)


def _utc_now_iso8601() -> str:
    """Return one UTC timestamp with a Z suffix."""
    from datetime import datetime
    from datetime import timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
