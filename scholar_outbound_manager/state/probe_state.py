"""Persistence helpers for batch probe state artifacts."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import ProbeResult
from scholar_outbound_manager.probe.batch_probe import BatchProbeRecord
from scholar_outbound_manager.probe.batch_probe import BatchProbeSummary
from scholar_outbound_manager.probe.batch_probe import select_passed_candidates
from scholar_outbound_manager.probe.candidate_probe import CandidateProbeSummary
from scholar_outbound_manager.state.atomic_write import atomic_write_json


def serialize_probe_result(result: ProbeResult) -> dict[str, object]:
    """Serialize one ProbeResult into a JSON-ready mapping."""
    result_mapping = result.to_dict()
    return {
        "candidate_id": result_mapping["candidate_id"],
        "home_status": result_mapping["home_status"],
        "query_status": result_mapping["query_status"],
        "blocked": result_mapping["blocked"],
        "timeout": result_mapping["timeout"],
        "error": result_mapping["error"],
        "failure_markers": list(result_mapping["failure_markers"]),
        "latency_ms": result_mapping["latency_ms"],
        "checked_at": result_mapping["checked_at"],
    }


def serialize_candidate_probe_summary(summary: CandidateProbeSummary) -> dict[str, object]:
    """Serialize one candidate probe summary without embedding candidate secrets."""
    return {
        "candidate_id": summary.candidate_id,
        "runtime_config_path": summary.runtime_config_path,
        "local_socks_host": summary.local_socks_host,
        "local_socks_port": summary.local_socks_port,
        "xray_started": summary.xray_started,
        "xray_test_passed": summary.xray_test_passed,
        "startup_ready": summary.startup_ready,
        "result": serialize_probe_result(summary.result),
    }


def serialize_batch_probe_record(record: BatchProbeRecord) -> dict[str, object]:
    """Serialize one batch probe record with redacted human-readable text fields."""
    return {
        "index": record.index,
        "candidate_id": record.candidate_id,
        "candidate_name": _redact_free_text(record.candidate_name),
        "attempted": record.attempted,
        "passed": record.passed,
        "skipped": record.skipped,
        "skip_reason": None if record.skip_reason is None else _redact_free_text(record.skip_reason),
        "summary": None if record.summary is None else serialize_candidate_probe_summary(record.summary),
    }


def serialize_batch_probe_summary(summary: BatchProbeSummary) -> dict[str, object]:
    """Serialize one batch probe summary into a redacted review-safe payload."""
    return {
        "schema_version": 1,
        "total_count": summary.total_count,
        "attempted_count": summary.attempted_count,
        "skipped_count": summary.skipped_count,
        "passed_count": summary.passed_count,
        "failed_count": summary.failed_count,
        "passed_indices": list(summary.passed_indices),
        "passed_candidate_ids": list(summary.passed_candidate_ids),
        "records": [serialize_batch_probe_record(record) for record in summary.records],
    }


def write_batch_probe_summary(path: str | Path, summary: BatchProbeSummary) -> None:
    """Write a redacted batch probe summary artifact atomically."""
    atomic_write_json(path, serialize_batch_probe_summary(summary))


def build_passed_candidates_payload(
    candidates: list[CandidateProxy],
    summary: BatchProbeSummary,
) -> dict[str, object]:
    """Build a sensitive local payload containing only passed candidates."""
    passed_candidates = select_passed_candidates(candidates, summary)
    records_by_index = {record.index: record for record in summary.records}
    candidate_entries = []
    for candidate, passed_index in zip(passed_candidates, summary.passed_indices):
        record = records_by_index.get(passed_index)
        candidate_entries.append(
            {
                "candidate": candidate.to_dict(),
                "probe": (
                    None
                    if record is None or record.summary is None
                    else serialize_probe_result(record.summary.result)
                ),
            }
        )
    return {
        "schema_version": 1,
        "sensitive": True,
        "description": "This file contains selected proxy credentials and must not be committed.",
        "passed_candidate_ids": list(summary.passed_candidate_ids),
        "candidates": candidate_entries,
    }


def write_passed_candidates(
    path: str | Path,
    candidates: list[CandidateProxy],
    summary: BatchProbeSummary,
) -> None:
    """Write the sensitive passed-candidate payload atomically."""
    atomic_write_json(path, build_passed_candidates_payload(candidates, summary))


def write_probe_artifacts(
    summary_path: str | Path,
    passed_candidates_path: str | Path,
    candidates: list[CandidateProxy],
    summary: BatchProbeSummary,
) -> dict[str, object]:
    """Write both the redacted summary and sensitive passed-candidate artifacts."""
    write_batch_probe_summary(summary_path, summary)
    write_passed_candidates(passed_candidates_path, candidates, summary)
    return {
        "summary_path": str(Path(summary_path)),
        "passed_candidates_path": str(Path(passed_candidates_path)),
        "passed_count": summary.passed_count,
        "attempted_count": summary.attempted_count,
        "skipped_count": summary.skipped_count,
        "failed_count": summary.failed_count,
    }


def _redact_free_text(value: str) -> str:
    """Redact free text conservatively for review-safe summary output."""
    if len(value) <= 8:
        return "<REDACTED>"
    return f"{value[:4]}<REDACTED>{value[-4:]}"
