"""Artifact lineage and consistency helpers."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ArtifactLineage:
    """Describe one artifact's lineage metadata."""

    artifact_type: str
    run_id: str
    created_at: str
    source_candidates_hash: str | None = None
    source_probe_summary_hash: str | None = None
    source_subscription_hash: str | None = None
    tool_version: str | None = None
    schema_version: int = 1


def compute_artifact_hash(path_or_payload: str | Path | dict[str, object] | list[object]) -> str:
    """Compute one stable canonical SHA-256 hash for a JSON artifact."""
    payload: Any
    if isinstance(path_or_payload, (str, Path)):
        raw_text = Path(path_or_payload).read_text(encoding="utf-8")
        payload = json.loads(raw_text)
    else:
        payload = path_or_payload
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def generate_run_id(prefix: str = "run") -> str:
    """Generate one non-secret UTC-tagged run identifier."""
    normalized_prefix = re.sub(r"[^a-z0-9_-]+", "-", prefix.lower()).strip("-") or "run"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{normalized_prefix}-{timestamp}-{secrets.token_hex(3)}"


def artifact_lineage_to_dict(lineage: ArtifactLineage) -> dict[str, object]:
    """Convert lineage metadata to a plain dictionary."""
    return asdict(lineage)


def extract_artifact_lineage(payload: dict[str, object]) -> ArtifactLineage | None:
    """Extract one best-effort lineage record from an artifact payload."""
    artifact_type = _coerce_optional_str(payload.get("artifact_type"))
    run_id = _coerce_optional_str(payload.get("run_id"))
    created_at = _coerce_optional_str(payload.get("created_at"))
    if artifact_type is None or run_id is None or created_at is None:
        return None
    return ArtifactLineage(
        schema_version=_coerce_optional_int(payload.get("schema_version")) or 1,
        artifact_type=artifact_type,
        run_id=run_id,
        created_at=created_at,
        source_candidates_hash=_coerce_optional_str(payload.get("source_candidates_hash")),
        source_probe_summary_hash=_coerce_optional_str(payload.get("source_probe_summary_hash")),
        source_subscription_hash=_coerce_optional_str(payload.get("source_subscription_hash")),
        tool_version=_coerce_optional_str(payload.get("tool_version")),
    )


def load_artifact_payload(path: str | Path) -> dict[str, object]:
    """Load one JSON artifact payload as a mapping."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Artifact payload must be a JSON object: {path}")
    return {str(key): value for key, value in payload.items()}


def check_artifact_consistency(
    *,
    candidates_path: str | Path | None = None,
    probe_summary_path: str | Path | None = None,
    passed_candidates_path: str | Path | None = None,
) -> dict[str, object]:
    """Check lineage consistency across candidates, probe summary, and passed-candidate artifacts."""
    candidates_payload = load_artifact_payload(candidates_path) if candidates_path else None
    probe_payload = load_artifact_payload(probe_summary_path) if probe_summary_path else None
    passed_payload = load_artifact_payload(passed_candidates_path) if passed_candidates_path else None

    candidates_hash = compute_artifact_hash(candidates_payload) if candidates_payload is not None else None
    probe_summary_hash = compute_artifact_hash(probe_payload) if probe_payload is not None else None
    passed_candidates_hash = compute_artifact_hash(passed_payload) if passed_payload is not None else None

    probe_candidates_match = _hash_match(
        _payload_value(probe_payload, "source_candidates_hash"),
        candidates_hash,
    )
    passed_candidates_source_match = _hash_match(
        _payload_value(passed_payload, "source_candidates_hash"),
        candidates_hash,
    )
    passed_probe_match = _hash_match(
        _payload_value(passed_payload, "source_probe_summary_hash"),
        probe_summary_hash,
    )

    warnings: list[str] = []
    warnings.extend(_lineage_warnings(candidates_payload))
    warnings.extend(_lineage_warnings(probe_payload))
    warnings.extend(_lineage_warnings(passed_payload))

    if probe_candidates_match is False:
        warnings.append("probe_summary source_candidates_hash does not match candidates artifact.")
    if passed_candidates_source_match is False:
        warnings.append("passed_candidates source_candidates_hash does not match candidates artifact.")
    if passed_probe_match is False:
        warnings.append("passed_candidates source_probe_summary_hash does not match probe_summary artifact.")

    run_id_consistent = True
    if candidates_payload is not None and probe_payload is not None:
        run_id_consistent &= _run_id_match(probe_payload, "source_candidates_run_id", candidates_payload.get("run_id"), warnings, "probe_summary")
    if candidates_payload is not None and passed_payload is not None:
        run_id_consistent &= _run_id_match(passed_payload, "source_candidates_run_id", candidates_payload.get("run_id"), warnings, "passed_candidates")
    if probe_payload is not None and passed_payload is not None:
        run_id_consistent &= _run_id_match(passed_payload, "source_probe_summary_run_id", probe_payload.get("run_id"), warnings, "passed_candidates")

    comparisons = [probe_candidates_match, passed_candidates_source_match, passed_probe_match]
    known_comparisons = [value for value in comparisons if value is not None]
    if any(value is False for value in known_comparisons) or not run_id_consistent:
        overall_consistent: bool | None = False
    elif known_comparisons and all(value is True for value in known_comparisons):
        overall_consistent = True
    else:
        overall_consistent = None

    return {
        "candidates_present": candidates_payload is not None,
        "probe_summary_present": probe_payload is not None,
        "passed_candidates_present": passed_payload is not None,
        "candidates_hash": candidates_hash,
        "probe_summary_hash": probe_summary_hash,
        "passed_candidates_hash": passed_candidates_hash,
        "probe_summary_source_candidates_match": probe_candidates_match,
        "passed_candidates_source_candidates_match": passed_candidates_source_match,
        "passed_candidates_source_probe_summary_match": passed_probe_match,
        "overall_consistent": overall_consistent,
        "warnings": warnings,
    }


def summarize_lineage_warning(payload: dict[str, object] | None) -> str | None:
    """Return one generic warning string when lineage metadata is missing."""
    warnings = _lineage_warnings(payload)
    if not warnings:
        return None
    return "Warning: artifact lineage is missing or inconsistent; rerun fetch + probe if selection appears stale."


def build_probe_explanation(
    payload: dict[str, object],
    *,
    label_regex: str | None = None,
    candidate_id: str | None = None,
    protocol: str | None = None,
    error_category: str | None = None,
    marker: str | None = None,
) -> dict[str, object]:
    """Build one redacted probe explanation payload from a probe summary artifact."""
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("probe summary artifact must contain a records list.")
    pattern = re.compile(label_regex) if label_regex else None
    records: list[dict[str, object]] = []
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        record_candidate_id = _coerce_optional_str(raw_record.get("candidate_id")) or ""
        record_name = _coerce_optional_str(raw_record.get("candidate_name")) or ""
        record_protocol = _coerce_optional_str(raw_record.get("candidate_protocol"))
        if candidate_id and record_candidate_id != candidate_id:
            continue
        if pattern and not pattern.search(record_name):
            continue
        summary = raw_record.get("summary")
        result = summary.get("result") if isinstance(summary, dict) else None
        failure_markers = _safe_failure_markers(result)
        record_error_category = _probe_error_category(result, failure_markers)
        if protocol and record_protocol != protocol:
            continue
        if error_category and record_error_category != error_category:
            continue
        if marker and marker not in failure_markers:
            continue
        records.append(
            {
                "index": _coerce_optional_int(raw_record.get("index")),
                "candidate_id": record_candidate_id,
                "protocol": record_protocol,
                "label": record_name or None,
                "region_hint": _infer_region_hint(record_name),
                "attempted": bool(raw_record.get("attempted")),
                "skipped": bool(raw_record.get("skipped")),
                "passed": bool(raw_record.get("passed")),
                "skip_reason": _coerce_optional_str(raw_record.get("skip_reason")),
                "home_status": _coerce_optional_int(result.get("home_status")) if isinstance(result, dict) else None,
                "query_status": _coerce_optional_int(result.get("query_status")) if isinstance(result, dict) else None,
                "failure_markers": failure_markers,
                "error_category": record_error_category,
            }
        )
    return {
        "record_count": len(records),
        "records": records,
        "warnings": _lineage_warnings(payload),
    }


def _hash_match(source_hash: str | None, actual_hash: str | None) -> bool | None:
    """Compare one stored source hash to the current artifact hash."""
    if actual_hash is None:
        return None
    if source_hash is None:
        return None
    return source_hash == actual_hash


def _run_id_match(
    payload: dict[str, object],
    field_name: str,
    expected_run_id: object,
    warnings: list[str],
    artifact_name: str,
) -> bool:
    """Compare one source run-id field to the expected run ID."""
    observed = _coerce_optional_str(payload.get(field_name))
    expected = _coerce_optional_str(expected_run_id)
    if observed is None or expected is None:
        warnings.append(f"{artifact_name} is missing {field_name} lineage metadata.")
        return True
    if observed != expected:
        warnings.append(f"{artifact_name} {field_name} does not match the provided source artifact run_id.")
        return False
    return True


def _lineage_warnings(payload: dict[str, object] | None) -> list[str]:
    """Return artifact-local lineage warnings."""
    if payload is None:
        return []
    warnings: list[str] = []
    artifact_type = _coerce_optional_str(payload.get("artifact_type"))
    if artifact_type is None:
        warnings.append("artifact_type is missing.")
        return warnings
    if _coerce_optional_str(payload.get("run_id")) is None:
        warnings.append(f"{artifact_type} artifact is missing run_id.")
    if _coerce_optional_str(payload.get("created_at")) is None:
        warnings.append(f"{artifact_type} artifact is missing created_at.")
    if artifact_type == "probe_summary" and _coerce_optional_str(payload.get("source_candidates_hash")) is None:
        warnings.append("probe_summary artifact is missing source_candidates_hash.")
    if artifact_type == "passed_candidates":
        if _coerce_optional_str(payload.get("source_candidates_hash")) is None:
            warnings.append("passed_candidates artifact is missing source_candidates_hash.")
        if _coerce_optional_str(payload.get("source_probe_summary_hash")) is None:
            warnings.append("passed_candidates artifact is missing source_probe_summary_hash.")
    if artifact_type == "selected_candidate" and _coerce_optional_str(payload.get("source_passed_candidates_hash")) is None:
        warnings.append("selected_candidate artifact is missing source_passed_candidates_hash.")
    return warnings


def _safe_failure_markers(result: object) -> list[str]:
    """Extract one safe failure-marker list."""
    if not isinstance(result, dict):
        return []
    raw_markers = result.get("failure_markers")
    if not isinstance(raw_markers, list):
        return []
    return [marker for marker in raw_markers if isinstance(marker, str) and marker]


def _probe_error_category(result: object, failure_markers: list[str]) -> str | None:
    """Classify one review-safe probe error category from result text and markers."""
    if not isinstance(result, dict):
        return None
    error_text = (_coerce_optional_str(result.get("error")) or "").lower()
    if "tls/ssl connection has been closed (eof)" in error_text:
        return "ssl_eof"
    if "ssl" in error_text and "eof" in error_text:
        return "ssl_eof"
    if "timeout" in failure_markers:
        return "timeout"
    if "transport_error" in failure_markers or "stage_transport_failed" in failure_markers:
        return "transport_error"
    return None


def _infer_region_hint(label: str | None) -> str | None:
    """Infer one coarse region hint from a redacted label."""
    if not label:
        return None
    upper_label = label.upper()
    if "LOS ANGELES" in upper_label or re.search(r"\bLA\b", upper_label):
        return "US-LA"
    if any(token in label for token in ("United States", "美国")) or re.search(r"\bUSA?\b", upper_label):
        return "US"
    if any(token in label for token in ("Japan", "Tokyo", "日本", "东京")) or re.search(r"\bJP\b", upper_label):
        return "JP"
    if any(token in label for token in ("Taiwan", "台湾")) or re.search(r"\bTW\b", upper_label):
        return "TW"
    if any(token in label for token in ("Hong Kong", "香港")) or re.search(r"\bHK\b", upper_label):
        return "HK"
    if any(token in label for token in ("Singapore", "新加坡")) or re.search(r"\bSG\b", upper_label):
        return "SG"
    if any(token in label for token in ("Korea", "韩国", "首尔")) or re.search(r"\bKR\b", upper_label):
        return "KR"
    return None


def _payload_value(payload: dict[str, object] | None, field_name: str) -> str | None:
    """Return one optional string field from a maybe-payload."""
    if payload is None:
        return None
    return _coerce_optional_str(payload.get(field_name))


def _coerce_optional_str(value: object) -> str | None:
    """Coerce one optional string."""
    if isinstance(value, str) and value:
        return value
    return None


def _coerce_optional_int(value: object) -> int | None:
    """Coerce one optional integer."""
    if isinstance(value, int):
        return value
    return None
