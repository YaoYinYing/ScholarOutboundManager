"""Canonical Testing artifact loading for the TUI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scholar_outbound_manager.selection import build_candidate_catalog
from scholar_outbound_manager.selection import extract_candidate_selection_records
from scholar_outbound_manager.selection import infer_probe_passed
from scholar_outbound_manager.selection import load_candidate_payload
from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.tui.path_resolver import UserDataPaths


@dataclass(slots=True, frozen=True)
class TestingArtifacts:
    candidates_exists: bool
    probe_summary_exists: bool
    passed_candidates_exists: bool
    lineage_consistent: bool
    candidates: list
    probe_results_by_candidate_id: dict[str, dict[str, object]]
    passed_ids: set[str]
    warnings: list[str]
    source_hashes: dict[str, str]
    attempted_count: int
    passed_count: int
    failed_count: int
    skipped_count: int
    parallel_workers: int | None
    keep_all_passed: bool | None


def load_testing_artifacts(user_data_paths: UserDataPaths) -> TestingArtifacts:
    """Load canonical Testing artifacts from one user_data_dir lineage."""
    candidates_payload = _read_json_mapping(user_data_paths.candidates)
    probe_payload = _read_json_mapping(user_data_paths.probe_summary)
    passed_payload = _read_json_mapping(user_data_paths.passed_candidates)

    candidates_exists = bool(candidates_payload)
    probe_summary_exists = bool(probe_payload)
    passed_candidates_exists = bool(passed_payload)
    candidates = build_candidate_catalog(candidates_payload) if candidates_payload else []

    candidate_ids = {entry.candidate_id for entry in candidates}
    probe_results = _load_probe_results_by_candidate_id(probe_payload, candidate_ids=candidate_ids)
    passed_ids = _load_passed_ids(passed_payload, candidate_ids=candidate_ids)

    warnings: list[str] = []
    candidate_hash = compute_artifact_hash(candidates_payload) if candidates_payload else ""
    probe_hash = str(probe_payload.get("source_candidates_hash") or "") if probe_payload else ""
    passed_hash = str(passed_payload.get("source_candidates_hash") or "") if passed_payload else ""
    lineage_consistent = True
    if candidate_hash:
        if probe_hash and probe_hash != candidate_hash:
            lineage_consistent = False
        if passed_hash and passed_hash != candidate_hash:
            lineage_consistent = False
    if not lineage_consistent:
        warnings.append(
            "Artifact lineage mismatch.\n"
            "The current probe summary does not match the current candidates artifact.\n"
            "Run Test Nodes to rebuild probe_summary and passed_candidates."
        )
    return TestingArtifacts(
        candidates_exists=candidates_exists,
        probe_summary_exists=probe_summary_exists,
        passed_candidates_exists=passed_candidates_exists,
        lineage_consistent=lineage_consistent,
        candidates=candidates,
        probe_results_by_candidate_id=probe_results,
        passed_ids=passed_ids,
        warnings=warnings,
        source_hashes={
            "candidates": candidate_hash,
            "probe_summary": probe_hash,
            "passed_candidates": passed_hash,
        },
        attempted_count=_coerce_optional_int(probe_payload.get("attempted_count")) or 0,
        passed_count=_coerce_optional_int(probe_payload.get("passed_count")) or len(passed_ids),
        failed_count=_coerce_optional_int(probe_payload.get("failed_count")) or 0,
        skipped_count=_coerce_optional_int(probe_payload.get("skipped_count")) or 0,
        parallel_workers=_coerce_optional_int(probe_payload.get("parallel_workers")),
        keep_all_passed=_coerce_optional_bool(probe_payload.get("keep_all_passed")),
    )


def _load_probe_results_by_candidate_id(
    payload: dict[str, object],
    *,
    candidate_ids: set[str],
) -> dict[str, dict[str, object]]:
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        return {}
    records: dict[str, dict[str, object]] = {}
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        candidate_id = raw_record.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            continue
        summary = raw_record.get("summary")
        result_payload = {}
        if isinstance(summary, dict) and isinstance(summary.get("result"), dict):
            result_payload = {str(key): value for key, value in summary["result"].items()}
        if candidate_id not in candidate_ids:
            normalized_id = result_payload.get("candidate_id")
            if isinstance(normalized_id, str) and normalized_id in candidate_ids:
                candidate_id = normalized_id
        records[candidate_id] = {
            "attempted": bool(raw_record.get("attempted")),
            "passed": bool(raw_record.get("passed")),
            "skipped": bool(raw_record.get("skipped")),
            "skip_reason": raw_record.get("skip_reason"),
            "probe_payload": result_payload,
        }
    return records


def _load_passed_ids(payload: dict[str, object], *, candidate_ids: set[str]) -> set[str]:
    raw_ids = payload.get("passed_candidate_ids")
    if isinstance(raw_ids, list):
        return {str(candidate_id) for candidate_id in raw_ids if isinstance(candidate_id, str) and candidate_id}
    try:
        records = extract_candidate_selection_records(payload) if payload else []
    except ValueError:
        return set()
    passed_ids: set[str] = set()
    for record in records:
        if record.candidate_id in candidate_ids and infer_probe_passed(record.probe_payload):
            passed_ids.add(record.candidate_id)
    return passed_ids


def _read_json_mapping(path: str | Path) -> dict[str, object]:
    try:
        raw_text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return {}
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}
    return {str(key): value for key, value in payload.items()} if isinstance(payload, dict) else {}


def _coerce_optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, int) else None


def _coerce_optional_bool(value: object) -> bool | None:
    return bool(value) if isinstance(value, bool) else None
