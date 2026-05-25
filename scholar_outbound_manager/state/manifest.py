"""Manifest generation and persistence helpers."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import GeneratedNode
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.util.redact import redact_mapping


def build_manifest(
    selected_nodes: list[GeneratedNode],
    rejected_candidates: list[CandidateProxy],
    generated_at: str | None = None,
) -> dict[str, object]:
    """Build a redacted manifest for generated Scholar outbound artifacts."""
    manifest_generated_at = generated_at or _utc_now_iso8601()
    return {
        "schema_version": 1,
        "generated_at": manifest_generated_at,
        "selected": [_serialize_selected_node(node) for node in selected_nodes],
        "rejected": [_serialize_rejected_candidate(candidate) for candidate in rejected_candidates],
    }


def write_manifest(path: str | Path, manifest: dict[str, object]) -> None:
    """Write one manifest atomically as JSON."""
    atomic_write_json(path, manifest)


def _serialize_selected_node(node: GeneratedNode) -> dict[str, object]:
    """Serialize one selected node for manifest output."""
    return {
        "tag": node.tag,
        "candidate": _redact_candidate(node.candidate),
        "probe": None if node.probe is None else redact_mapping(node.probe.to_dict()),
    }


def _serialize_rejected_candidate(candidate: CandidateProxy) -> dict[str, object]:
    """Serialize one rejected candidate for manifest output."""
    return {
        "candidate": _redact_candidate(candidate),
        "reason": candidate.unsupported_reason or "Candidate was not selected.",
    }


def _redact_candidate(candidate: CandidateProxy) -> dict[str, object]:
    """Redact one candidate mapping for manifest output."""
    candidate_mapping = redact_mapping(candidate.to_dict())
    candidate_mapping.pop("raw_uri", None)
    return candidate_mapping


def _utc_now_iso8601() -> str:
    """Return the current UTC timestamp in ISO 8601 format with a Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
