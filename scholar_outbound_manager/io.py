"""Input and output helpers for offline candidate files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.state.atomic_write import atomic_write_json


def load_candidates(path: str | Path) -> list[CandidateProxy]:
    """Load parsed candidate proxies from a local JSON file."""
    candidate_path = Path(path)
    try:
        raw_text = candidate_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ValueError(f"Could not read candidate file: {candidate_path}") from exc

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse candidate JSON: {candidate_path}") from exc

    candidate_items = _extract_candidate_items(raw_data, candidate_path)
    return [
        _build_candidate(candidate_item, index, candidate_path)
        for index, candidate_item in enumerate(candidate_items)
    ]


def dump_candidates(path: str | Path, candidates: list[CandidateProxy]) -> None:
    """Write candidate proxies to a JSON file for offline reuse."""
    atomic_write_json(
        path,
        {
            "candidates": [candidate.to_dict() for candidate in candidates],
        },
    )


def _extract_candidate_items(raw_data: object, candidate_path: Path) -> list[object]:
    """Extract the candidate list from one supported top-level JSON shape."""
    if isinstance(raw_data, list):
        return raw_data
    if isinstance(raw_data, dict) and isinstance(raw_data.get("candidates"), list):
        return raw_data["candidates"]
    raise ValueError(
        f"Candidate file must be a list or an object with a 'candidates' list: {candidate_path}"
    )


def _build_candidate(candidate_item: object, index: int, candidate_path: Path) -> CandidateProxy:
    """Construct one candidate proxy and attach index-aware errors."""
    if not isinstance(candidate_item, dict):
        raise ValueError(f"Candidate at index {index} in {candidate_path} must be a JSON object.")
    try:
        return CandidateProxy(**_string_key_mapping(candidate_item))
    except TypeError as exc:
        raise ValueError(
            f"Invalid candidate at index {index} in {candidate_path}: {exc}"
        ) from exc


def _string_key_mapping(candidate_item: dict[Any, Any]) -> dict[str, object]:
    """Normalize one candidate mapping to string keys."""
    return {str(key): value for key, value in candidate_item.items()}
