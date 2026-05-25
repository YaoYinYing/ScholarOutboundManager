"""Review-safe inspection helpers for generated Scholar artifacts."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProbeSummaryInspection:
    """Summarize one redacted batch probe summary artifact."""

    path: str
    schema_version: int | None
    total_count: int
    attempted_count: int
    skipped_count: int
    passed_count: int
    failed_count: int
    top_failure_markers: list[tuple[str, int]]
    passed_candidate_ids: list[str]


@dataclass(frozen=True)
class GeneratedManifestInspection:
    """Summarize one generated manifest artifact."""

    path: str
    schema_version: int | None
    generated_at: str | None
    selected_count: int
    rejected_count: int
    selected_tags: list[str]
    rejected_reasons: list[str]


@dataclass(frozen=True)
class SensitiveCandidatesInspection:
    """Summarize one sensitive passed-candidate artifact without exposing candidates."""

    path: str
    schema_version: int | None
    sensitive: bool
    candidate_count: int
    passed_candidate_ids: list[str]
    description: str | None


def load_json_file(path: str | Path) -> dict[str, object]:
    """Load one JSON file and require a mapping at the top level."""
    json_path = Path(path)
    try:
        with json_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {json_path}: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"JSON file {json_path} must contain an object at the top level.")
    return payload


def inspect_probe_summary(path: str | Path) -> ProbeSummaryInspection:
    """Inspect one redacted batch probe summary artifact."""
    payload = load_json_file(path)
    records = _require_list(payload.get("records"), "records", path)
    marker_counter: Counter[str] = Counter()
    for record in records:
        if not isinstance(record, dict):
            continue
        summary = record.get("summary")
        if not isinstance(summary, dict):
            continue
        result = summary.get("result")
        if not isinstance(result, dict):
            continue
        for marker in _coerce_string_list(result.get("failure_markers")):
            marker_counter[marker] += 1

    top_failure_markers = sorted(marker_counter.items(), key=lambda item: (-item[1], item[0]))
    return ProbeSummaryInspection(
        path=str(Path(path)),
        schema_version=_coerce_optional_int(payload.get("schema_version")),
        total_count=_coerce_int(payload.get("total_count"), "total_count", path),
        attempted_count=_coerce_int(payload.get("attempted_count"), "attempted_count", path),
        skipped_count=_coerce_int(payload.get("skipped_count"), "skipped_count", path),
        passed_count=_coerce_int(payload.get("passed_count"), "passed_count", path),
        failed_count=_coerce_int(payload.get("failed_count"), "failed_count", path),
        top_failure_markers=top_failure_markers,
        passed_candidate_ids=_coerce_string_list(payload.get("passed_candidate_ids")),
    )


def inspect_generated_manifest(path: str | Path) -> GeneratedManifestInspection:
    """Inspect one generated manifest artifact."""
    payload = load_json_file(path)
    selected = _require_list(payload.get("selected"), "selected", path)
    rejected = _require_list(payload.get("rejected"), "rejected", path)
    selected_tags = [
        entry["tag"]
        for entry in selected
        if isinstance(entry, dict) and isinstance(entry.get("tag"), str)
    ]
    rejected_reasons = [
        entry["reason"]
        for entry in rejected
        if isinstance(entry, dict) and isinstance(entry.get("reason"), str)
    ][:20]
    return GeneratedManifestInspection(
        path=str(Path(path)),
        schema_version=_coerce_optional_int(payload.get("schema_version")),
        generated_at=payload.get("generated_at") if isinstance(payload.get("generated_at"), str) else None,
        selected_count=len(selected),
        rejected_count=len(rejected),
        selected_tags=selected_tags,
        rejected_reasons=rejected_reasons,
    )


def inspect_sensitive_candidates(path: str | Path) -> SensitiveCandidatesInspection:
    """Inspect one sensitive passed-candidate artifact without exposing candidate data."""
    payload = load_json_file(path)
    candidates = _require_list(payload.get("candidates"), "candidates", path)
    return SensitiveCandidatesInspection(
        path=str(Path(path)),
        schema_version=_coerce_optional_int(payload.get("schema_version")),
        sensitive=bool(payload.get("sensitive")),
        candidate_count=len(candidates),
        passed_candidate_ids=_coerce_string_list(payload.get("passed_candidate_ids")),
        description=payload.get("description") if isinstance(payload.get("description"), str) else None,
    )


def format_probe_summary_inspection(inspection: ProbeSummaryInspection) -> str:
    """Format one probe summary inspection for CLI output."""
    lines = [
        "Probe summary:",
        f"path: {inspection.path}",
        f"schema_version: {inspection.schema_version}",
        f"total_count: {inspection.total_count}",
        f"attempted_count: {inspection.attempted_count}",
        f"skipped_count: {inspection.skipped_count}",
        f"passed_count: {inspection.passed_count}",
        f"failed_count: {inspection.failed_count}",
        "top_failure_markers:",
    ]
    lines.extend(_format_key_value_list(inspection.top_failure_markers))
    lines.append("passed_candidate_ids:")
    lines.extend(_format_string_list(inspection.passed_candidate_ids))
    return "\n".join(lines)


def format_generated_manifest_inspection(inspection: GeneratedManifestInspection) -> str:
    """Format one generated manifest inspection for CLI output."""
    lines = [
        "Generated manifest:",
        f"path: {inspection.path}",
        f"schema_version: {inspection.schema_version}",
        f"generated_at: {inspection.generated_at}",
        f"selected_count: {inspection.selected_count}",
        f"rejected_count: {inspection.rejected_count}",
        "selected_tags:",
    ]
    lines.extend(_format_string_list(inspection.selected_tags))
    lines.append("rejected_reasons:")
    lines.extend(_format_string_list(inspection.rejected_reasons))
    return "\n".join(lines)


def format_sensitive_candidates_inspection(inspection: SensitiveCandidatesInspection) -> str:
    """Format one sensitive candidate inspection for CLI output."""
    lines = [
        "Sensitive passed candidates:",
        f"path: {inspection.path}",
        f"schema_version: {inspection.schema_version}",
        f"sensitive: {str(inspection.sensitive).lower()}",
        f"candidate_count: {inspection.candidate_count}",
        "passed_candidate_ids:",
    ]
    lines.extend(_format_string_list(inspection.passed_candidate_ids))
    lines.append(f"description: {inspection.description}")
    lines.append("Warning: sensitive candidate credentials are not displayed.")
    return "\n".join(lines)


def _require_list(value: object, field_name: str, path: str | Path) -> list[object]:
    """Require that one JSON field is a list."""
    if not isinstance(value, list):
        raise ValueError(f"{Path(path)} must contain a list field named {field_name}.")
    return value


def _coerce_int(value: object, field_name: str, path: str | Path) -> int:
    """Require that one JSON field is an integer."""
    if not isinstance(value, int):
        raise ValueError(f"{Path(path)} must contain an integer field named {field_name}.")
    return value


def _coerce_optional_int(value: object) -> int | None:
    """Return one optional integer field when present."""
    return value if isinstance(value, int) else None


def _coerce_string_list(value: object) -> list[str]:
    """Collect string items from one list-like field while preserving order."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _format_key_value_list(items: list[tuple[str, int]]) -> list[str]:
    """Format one string-to-count list for CLI output."""
    if not items:
        return ["  - none"]
    return [f"  - {name}: {count}" for name, count in items]


def _format_string_list(items: list[str]) -> list[str]:
    """Format one string list for CLI output."""
    if not items:
        return ["  - none"]
    return [f"  - {item}" for item in items]
