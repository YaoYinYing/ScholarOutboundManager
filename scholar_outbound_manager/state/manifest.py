"""Manifest generation and persistence helpers."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Final

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import GeneratedNode
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.util.redact import redact_mapping

DEFAULT_REVIEW_SENSITIVE_FIELDS: Final[set[str]] = {
    "address",
    "server_name",
    "raw_name",
    "host",
    "fingerprint",
}


def build_manifest(
    selected_nodes: list[GeneratedNode],
    rejected_candidates: list[CandidateProxy],
    generated_at: str | None = None,
    review_sensitive_fields: set[str] | None = None,
) -> dict[str, object]:
    """Build a redacted manifest for generated Scholar outbound artifacts."""
    manifest_generated_at = generated_at or _utc_now_iso8601()
    sensitive_fields = DEFAULT_REVIEW_SENSITIVE_FIELDS if review_sensitive_fields is None else review_sensitive_fields
    return {
        "schema_version": 1,
        "generated_at": manifest_generated_at,
        "selected": [_serialize_selected_node(node, sensitive_fields) for node in selected_nodes],
        "rejected": [_serialize_rejected_candidate(candidate, sensitive_fields) for candidate in rejected_candidates],
    }


def write_manifest(path: str | Path, manifest: dict[str, object]) -> None:
    """Write one manifest atomically as JSON."""
    atomic_write_json(path, manifest)


def _serialize_selected_node(node: GeneratedNode, review_sensitive_fields: set[str]) -> dict[str, object]:
    """Serialize one selected node for manifest output."""
    return {
        "tag": node.tag,
        "candidate": _redact_candidate(node.candidate, review_sensitive_fields),
        "probe": None if node.probe is None else redact_mapping(node.probe.to_dict()),
    }


def _serialize_rejected_candidate(
    candidate: CandidateProxy,
    review_sensitive_fields: set[str],
) -> dict[str, object]:
    """Serialize one rejected candidate for manifest output."""
    return {
        "candidate": _redact_candidate(candidate, review_sensitive_fields),
        "reason": candidate.unsupported_reason or "Candidate was not selected.",
    }


def _redact_candidate(candidate: CandidateProxy, review_sensitive_fields: set[str]) -> dict[str, object]:
    """Redact one candidate mapping for manifest output."""
    candidate_mapping = redact_mapping(candidate.to_dict())
    candidate_mapping.pop("raw_uri", None)
    for field_name in review_sensitive_fields:
        if field_name in candidate_mapping and candidate_mapping[field_name] is not None:
            candidate_mapping[field_name] = "<REDACTED>"
    return candidate_mapping


def _utc_now_iso8601() -> str:
    """Return the current UTC timestamp in ISO 8601 format with a Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
