"""Helpers for selecting one candidate for runtime preparation."""

from __future__ import annotations

from scholar_outbound_manager.models import CandidateProxy


def select_candidate_by_index(
    candidates: list[CandidateProxy],
    index: int,
) -> CandidateProxy:
    """Select one candidate by its zero-based index with Phase 4b validation."""
    if not candidates:
        raise ValueError("No candidates are available for selection.")
    if index < 0:
        raise ValueError("candidate index must be greater than or equal to 0.")
    if index >= len(candidates):
        raise ValueError(f"candidate index {index} is out of range.")

    candidate = candidates[index]
    if not candidate.supported:
        reason = candidate.unsupported_reason or "Candidate is marked unsupported."
        raise ValueError(reason)
    if candidate.protocol != "vless":
        raise ValueError(f"Phase 4b run only supports vless candidates, got {candidate.protocol}.")
    return candidate
