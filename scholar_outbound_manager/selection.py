"""Helpers for secret-safe candidate selection and catalog rendering."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.state.atomic_write import atomic_write_json


@dataclass(slots=True)
class CandidateCatalogEntry:
    """Represent one redacted candidate catalog row."""

    index: int
    candidate_id: str
    protocol: str
    source_name: str | None
    supported: bool
    scholar_stage: str | None
    passed: bool | None
    home_status: int | None
    query_status: int | None
    checked_at: str | None
    failure_marker_count: int
    failure_markers: list[str]
    latency_ms: int | None
    tags: list[str]


@dataclass(slots=True)
class CandidateSelectionRecord:
    """Represent one resolved candidate record with optional probe evidence."""

    index: int
    candidate_id: str
    candidate: CandidateProxy
    candidate_payload: dict[str, object]
    probe_payload: dict[str, object] | None


def load_candidate_payload(path: str | Path) -> dict[str, object]:
    """Load one raw candidate payload from disk."""
    payload_path = Path(path)
    try:
        raw_text = payload_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ValueError(f"Could not read candidate payload: {payload_path}") from exc

    try:
        raw_payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse candidate payload JSON: {payload_path}") from exc
    if not isinstance(raw_payload, dict):
        raise ValueError(f"Candidate payload must be a JSON object: {payload_path}")
    return _string_key_mapping(raw_payload)


def extract_candidate_selection_records(payload: dict[str, object]) -> list[CandidateSelectionRecord]:
    """Extract resolved candidate records from a candidate artifact payload."""
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError("Candidate payload must contain a 'candidates' list.")

    records: list[CandidateSelectionRecord] = []
    for index, raw_record in enumerate(raw_candidates):
        if not isinstance(raw_record, dict):
            raise ValueError(f"Candidate at index {index} must be a JSON object.")

        normalized_record = _string_key_mapping(raw_record)
        candidate_payload = normalized_record
        probe_payload: dict[str, object] | None = None
        if "candidate" in normalized_record:
            nested_candidate = normalized_record.get("candidate")
            if not isinstance(nested_candidate, dict):
                raise ValueError(f"Candidate at index {index} must contain a candidate object.")
            candidate_payload = _string_key_mapping(nested_candidate)
            probe_object = normalized_record.get("probe")
            if probe_object is not None:
                if not isinstance(probe_object, dict):
                    raise ValueError(f"Probe result at index {index} must be a JSON object.")
                probe_payload = _string_key_mapping(probe_object)

        try:
            candidate = CandidateProxy(**candidate_payload)
        except TypeError as exc:
            raise ValueError(f"Invalid candidate at index {index}: {exc}") from exc

        records.append(
            CandidateSelectionRecord(
                index=index,
                candidate_id=_resolve_candidate_id(normalized_record, probe_payload, candidate_payload, index),
                candidate=candidate,
                candidate_payload=candidate.to_dict(),
                probe_payload=probe_payload,
            )
        )
    return records


def build_candidate_catalog(payload: dict[str, object]) -> list[CandidateCatalogEntry]:
    """Build one secret-safe candidate catalog from a candidate payload."""
    entries: list[CandidateCatalogEntry] = []
    for record in extract_candidate_selection_records(payload):
        probe = record.probe_payload or {}
        failure_markers = _extract_failure_markers(probe)
        passed = _coerce_optional_bool(probe.get("passed"))
        if passed is None:
            passed = _infer_passed(probe)
        scholar_stage = _infer_scholar_stage(probe, passed, failure_markers)
        entries.append(
            CandidateCatalogEntry(
                index=record.index,
                candidate_id=record.candidate_id,
                protocol=record.candidate.protocol,
                source_name=record.candidate.source_name or None,
                supported=record.candidate.supported,
                scholar_stage=scholar_stage,
                passed=passed,
                home_status=_coerce_optional_int(probe.get("home_status")),
                query_status=_coerce_optional_int(probe.get("query_status")),
                checked_at=_coerce_optional_str(probe.get("checked_at")),
                failure_marker_count=len(failure_markers),
                failure_markers=failure_markers,
                latency_ms=_coerce_optional_int(probe.get("latency_ms")),
                tags=_extract_tags(record.candidate_payload),
            )
        )
    return entries


def catalog_to_dicts(entries: list[CandidateCatalogEntry]) -> list[dict[str, object]]:
    """Convert catalog entries to plain dictionaries."""
    return [asdict(entry) for entry in entries]


def format_candidate_catalog_table(entries: list[CandidateCatalogEntry]) -> str:
    """Render one secret-safe candidate catalog table."""
    headers = ["index", "candidate_id", "protocol", "passed", "stage", "home", "query", "markers"]
    rows = [
        [
            str(entry.index),
            entry.candidate_id,
            entry.protocol,
            _render_optional_bool(entry.passed),
            entry.scholar_stage or "",
            _render_optional_int(entry.home_status),
            _render_optional_int(entry.query_status),
            str(entry.failure_marker_count),
        ]
        for entry in entries
    ]
    widths = [
        max(len(header), *(len(row[column]) for row in rows)) if rows else len(header)
        for column, header in enumerate(headers)
    ]
    rendered_rows = [
        "  ".join(value.ljust(widths[column]) for column, value in enumerate(row))
        for row in rows
    ]
    header_row = "  ".join(header.ljust(widths[column]) for column, header in enumerate(headers))
    if not rendered_rows:
        return header_row
    return "\n".join([header_row, *rendered_rows])


def select_candidate_by_id(payload: dict[str, object], candidate_id: str) -> CandidateSelectionRecord:
    """Select one candidate record by candidate ID."""
    if not candidate_id:
        raise ValueError("candidate_id must not be empty.")
    for record in extract_candidate_selection_records(payload):
        if record.candidate_id == candidate_id:
            return record
    raise ValueError(f"candidate_id '{candidate_id}' was not found.")


def select_candidate_by_index(
    payload_or_candidates: dict[str, object] | list[CandidateProxy],
    index: int,
) -> CandidateSelectionRecord | CandidateProxy:
    """Select one candidate record by index, preserving legacy list behavior."""
    if isinstance(payload_or_candidates, list):
        return _select_candidate_proxy_by_index(payload_or_candidates, index)
    if index < 0:
        raise ValueError("candidate index must be greater than or equal to 0.")
    records = extract_candidate_selection_records(payload_or_candidates)
    if index >= len(records):
        raise ValueError(f"candidate index {index} is out of range.")
    return records[index]


def build_selected_candidate_artifact(
    record: CandidateSelectionRecord,
    *,
    selection_method: str,
) -> dict[str, object]:
    """Build one sensitive selected-candidate artifact."""
    if selection_method not in {"candidate_id", "index"}:
        raise ValueError("selection_method must be 'candidate_id' or 'index'.")
    return {
        "schema_version": 1,
        "sensitive": True,
        "description": "This file contains one selected proxy candidate and must not be committed.",
        "selected_at": _utc_now_iso8601(),
        "selection_method": selection_method,
        "selected_candidate_id": record.candidate_id,
        "selected_index": record.index,
        "candidate": record.candidate_payload,
        "probe": record.probe_payload,
    }


def write_selected_candidate_artifact(path: str | Path, payload: dict[str, object]) -> None:
    """Write one sensitive selected-candidate artifact."""
    atomic_write_json(path, payload)


def load_selected_candidate_artifact(path: str | Path) -> CandidateSelectionRecord:
    """Load one selected-candidate artifact and materialize its record."""
    payload = load_candidate_payload(path)
    candidate_payload = payload.get("candidate")
    if not isinstance(candidate_payload, dict):
        raise ValueError("selected candidate artifact must contain a candidate object.")
    probe_payload = payload.get("probe")
    if probe_payload is not None and not isinstance(probe_payload, dict):
        raise ValueError("selected candidate artifact probe must be a JSON object.")

    try:
        candidate = CandidateProxy(**_string_key_mapping(candidate_payload))
    except TypeError as exc:
        raise ValueError(f"Invalid selected candidate artifact: {exc}") from exc

    candidate_id = _coerce_optional_str(payload.get("selected_candidate_id")) or _resolve_candidate_id(
        _string_key_mapping(candidate_payload),
        _string_key_mapping(probe_payload) if isinstance(probe_payload, dict) else None,
        _string_key_mapping(candidate_payload),
        _coerce_optional_int(payload.get("selected_index")) or 0,
    )
    return CandidateSelectionRecord(
        index=_coerce_optional_int(payload.get("selected_index")) or 0,
        candidate_id=candidate_id,
        candidate=candidate,
        candidate_payload=candidate.to_dict(),
        probe_payload=_string_key_mapping(probe_payload) if isinstance(probe_payload, dict) else None,
    )


def _select_candidate_proxy_by_index(candidates: list[CandidateProxy], index: int) -> CandidateProxy:
    """Select one candidate proxy by zero-based index with legacy validation."""
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


def _resolve_candidate_id(
    record_payload: dict[str, object],
    probe_payload: dict[str, object] | None,
    candidate_payload: dict[str, object],
    index: int,
) -> str:
    """Resolve one candidate ID from explicit fields or a stable fallback hash."""
    explicit_candidate_id = _coerce_optional_str(record_payload.get("candidate_id"))
    if explicit_candidate_id:
        return explicit_candidate_id
    if probe_payload is not None:
        explicit_candidate_id = _coerce_optional_str(probe_payload.get("candidate_id"))
        if explicit_candidate_id:
            return explicit_candidate_id
    extra = candidate_payload.get("extra")
    if isinstance(extra, dict):
        explicit_candidate_id = _coerce_optional_str(extra.get("candidate_id"))
        if explicit_candidate_id:
            return explicit_candidate_id
    return _build_fallback_candidate_id(candidate_payload, index)


def _build_fallback_candidate_id(candidate_payload: dict[str, object], index: int) -> str:
    """Build one stable fallback candidate ID without exposing hash material."""
    digest_payload = {
        "index": index,
        "source_name": candidate_payload.get("source_name"),
        "raw_name": candidate_payload.get("raw_name"),
        "protocol": candidate_payload.get("protocol"),
        "address": candidate_payload.get("address"),
        "port": candidate_payload.get("port"),
        "user_id": candidate_payload.get("user_id"),
        "password": candidate_payload.get("password"),
        "server_name": candidate_payload.get("server_name"),
        "public_key": candidate_payload.get("public_key"),
        "host": candidate_payload.get("host"),
        "path": candidate_payload.get("path"),
        "raw_uri": candidate_payload.get("raw_uri"),
    }
    material = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _extract_failure_markers(probe_payload: dict[str, object]) -> list[str]:
    """Extract one sanitized failure marker list from probe payload."""
    raw_markers = probe_payload.get("failure_markers")
    if not isinstance(raw_markers, list):
        return []
    markers: list[str] = []
    for marker in raw_markers:
        if isinstance(marker, str) and marker:
            markers.append(marker)
    return markers


def _extract_tags(candidate_payload: dict[str, object]) -> list[str]:
    """Extract one best-effort tag list without leaking free-form secrets."""
    raw_tags = candidate_payload.get("tags")
    if isinstance(raw_tags, list):
        return [tag for tag in raw_tags if isinstance(tag, str) and tag]
    extra = candidate_payload.get("extra")
    if isinstance(extra, dict):
        nested_tags = extra.get("tags")
        if isinstance(nested_tags, list):
            return [tag for tag in nested_tags if isinstance(tag, str) and tag]
    return []


def _infer_passed(probe_payload: dict[str, object]) -> bool | None:
    """Infer the passed flag from probe fields when not explicitly present."""
    if not probe_payload:
        return None
    failure_markers = _extract_failure_markers(probe_payload)
    home_status = _coerce_optional_int(probe_payload.get("home_status"))
    query_status = _coerce_optional_int(probe_payload.get("query_status"))
    allowed_statuses = {200, 301, 302, 303, 307, 308}
    if failure_markers:
        return False
    if home_status in allowed_statuses and query_status in allowed_statuses:
        return True
    if home_status is not None or query_status is not None:
        return False
    return None


def _infer_scholar_stage(
    probe_payload: dict[str, object],
    passed: bool | None,
    failure_markers: list[str],
) -> str | None:
    """Infer one Scholar stage from probe payload and failure markers."""
    if not probe_payload:
        return None
    stage_markers = {
        "stage_home_blocked": "home_blocked",
        "stage_query_blocked": "query_blocked",
        "stage_timeout": "timeout",
        "stage_transport_failed": "transport_failed",
        "stage_server_error": "server_error",
    }
    for marker, stage in stage_markers.items():
        if marker in failure_markers:
            return stage
    if passed:
        return "full_access"
    home_status = _coerce_optional_int(probe_payload.get("home_status"))
    query_status = _coerce_optional_int(probe_payload.get("query_status"))
    if home_status == 403:
        return "home_blocked"
    if query_status == 403:
        return "query_blocked"
    if any(status is not None and status >= 500 for status in (home_status, query_status)):
        return "server_error"
    if probe_payload.get("timeout") is True:
        return "timeout"
    if _coerce_optional_str(probe_payload.get("error")):
        return "transport_failed"
    return None


def _render_optional_bool(value: bool | None) -> str:
    """Render one optional bool for table output."""
    if value is None:
        return ""
    return "yes" if value else "no"


def _render_optional_int(value: int | None) -> str:
    """Render one optional integer for table output."""
    return "" if value is None else str(value)


def _coerce_optional_bool(value: object) -> bool | None:
    """Coerce one optional bool value."""
    return value if isinstance(value, bool) else None


def _coerce_optional_int(value: object) -> int | None:
    """Coerce one optional integer value."""
    return value if isinstance(value, int) else None


def _coerce_optional_str(value: object) -> str | None:
    """Coerce one optional string value."""
    if isinstance(value, str) and value:
        return value
    return None


def _string_key_mapping(mapping: object) -> dict[str, object]:
    """Normalize one mapping to string keys."""
    if not isinstance(mapping, dict):
        return {}
    return {str(key): value for key, value in mapping.items()}


def _utc_now_iso8601() -> str:
    """Return one UTC timestamp with a Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
