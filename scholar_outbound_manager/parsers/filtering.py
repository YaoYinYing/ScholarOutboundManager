"""Filtering and ordering helpers for parsed candidates."""

from __future__ import annotations

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import FilterConfig


def filter_candidates(candidates: list[CandidateProxy], config: FilterConfig) -> list[CandidateProxy]:
    """Filter and sort candidates using name-based keyword rules."""
    include_keywords = [item.lower() for item in config.include_keywords]
    exclude_keywords = [item.lower() for item in config.exclude_keywords]
    deprioritize_keywords = [item.lower() for item in config.deprioritize_keywords]

    filtered: list[CandidateProxy] = []
    for candidate in candidates:
        name = candidate.raw_name.lower()
        if include_keywords and not any(keyword in name for keyword in include_keywords):
            continue
        if any(keyword in name for keyword in exclude_keywords):
            continue
        filtered.append(candidate)

    return sorted(
        filtered,
        key=lambda candidate: (
            _has_deprioritize_keyword(candidate.raw_name, deprioritize_keywords),
            candidate.raw_name.lower(),
        ),
    )


def _has_deprioritize_keyword(name: str, keywords: list[str]) -> bool:
    """Return whether a name matches any deprioritization keyword."""
    normalized = name.lower()
    return any(keyword in normalized for keyword in keywords)
