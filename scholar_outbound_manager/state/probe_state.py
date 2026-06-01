"""Persistence helpers for batch probe state artifacts."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager import __version__
from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import ProbeResult
from scholar_outbound_manager.probe.batch_probe import BatchProbeRecord
from scholar_outbound_manager.probe.batch_probe import BatchProbeSummary
from scholar_outbound_manager.probe.batch_probe import select_passed_candidates
from scholar_outbound_manager.probe.candidate_probe import CandidateProbeSummary
from scholar_outbound_manager.selection import infer_region_hint
from scholar_outbound_manager.selection import redact_candidate_label
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.state.artifact_lineage import ArtifactLineage
from scholar_outbound_manager.state.artifact_lineage import artifact_lineage_to_dict
from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.state.artifact_lineage import generate_run_id


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
        "attempt_count": summary.attempt_count,
        "transport_retry_count_used": summary.transport_retry_count_used,
        "warmup_attempt_count": summary.warmup_attempt_count,
        "final_attempt_index": summary.final_attempt_index,
        "result": serialize_probe_result(summary.result),
    }


def serialize_batch_probe_record(record: BatchProbeRecord) -> dict[str, object]:
    """Serialize one batch probe record with redacted human-readable text fields."""
    candidate_label = record.candidate_label or redact_candidate_label(record.candidate_name)
    region_hint = record.region_hint if record.region_hint is not None else infer_region_hint(candidate_label)
    return {
        "index": record.index,
        "candidate_id": record.candidate_id,
        "candidate_name": _redact_free_text(record.candidate_name),
        "candidate_label": candidate_label,
        "region_hint": region_hint,
        "candidate_protocol": record.candidate_protocol,
        "attempted": record.attempted,
        "passed": record.passed,
        "skipped": record.skipped,
        "skip_reason": None if record.skip_reason is None else _redact_free_text(record.skip_reason),
        "summary": None if record.summary is None else serialize_candidate_probe_summary(record.summary),
    }


def serialize_batch_probe_summary(
    summary: BatchProbeSummary,
    *,
    run_id: str | None = None,
    created_at: str | None = None,
    source_candidates_hash: str | None = None,
    source_candidates_run_id: str | None = None,
) -> dict[str, object]:
    """Serialize one batch probe summary into a redacted review-safe payload."""
    return {
        "schema_version": 1,
        "artifact_type": "probe_summary",
        "run_id": run_id or generate_run_id("probe"),
        "created_at": created_at or _utc_now_iso8601(),
        "source_candidates_hash": source_candidates_hash,
        "source_candidates_run_id": source_candidates_run_id,
        "tool_version": __version__,
        "parallel_workers": summary.parallel_workers,
        "keep_all_passed": summary.keep_all_passed,
        "stop_after_max_passed": summary.stop_after_max_passed,
        "total_count": summary.total_count,
        "attempted_count": summary.attempted_count,
        "skipped_count": summary.skipped_count,
        "passed_count": summary.passed_count,
        "failed_count": summary.failed_count,
        "retained_passed_count": summary.retained_passed_count,
        "truncated": summary.truncated,
        "passed_indices": list(summary.passed_indices),
        "passed_candidate_ids": list(summary.passed_candidate_ids),
        "records": [serialize_batch_probe_record(record) for record in summary.records],
    }


def write_batch_probe_summary(
    path: str | Path,
    summary: BatchProbeSummary,
    *,
    run_id: str | None = None,
    created_at: str | None = None,
    source_candidates_hash: str | None = None,
    source_candidates_run_id: str | None = None,
) -> None:
    """Write a redacted batch probe summary artifact atomically."""
    atomic_write_json(
        path,
        serialize_batch_probe_summary(
            summary,
            run_id=run_id,
            created_at=created_at,
            source_candidates_hash=source_candidates_hash,
            source_candidates_run_id=source_candidates_run_id,
        ),
    )


def build_passed_candidates_payload(
    candidates: list[CandidateProxy],
    summary: BatchProbeSummary,
    *,
    run_id: str | None = None,
    created_at: str | None = None,
    source_candidates_hash: str | None = None,
    source_candidates_run_id: str | None = None,
    source_probe_summary_hash: str | None = None,
    source_probe_summary_run_id: str | None = None,
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
        "artifact_type": "passed_candidates",
        "run_id": run_id or generate_run_id("probe"),
        "created_at": created_at or _utc_now_iso8601(),
        "source_candidates_hash": source_candidates_hash,
        "source_candidates_run_id": source_candidates_run_id,
        "source_probe_summary_hash": source_probe_summary_hash,
        "source_probe_summary_run_id": source_probe_summary_run_id,
        "tool_version": __version__,
        "sensitive": True,
        "description": "This file contains selected proxy credentials and must not be committed.",
        "passed_count": summary.passed_count,
        "retained_passed_count": summary.retained_passed_count,
        "truncated": summary.truncated,
        "passed_candidate_ids": list(summary.passed_candidate_ids),
        "candidates": candidate_entries,
    }


def write_passed_candidates(
    path: str | Path,
    candidates: list[CandidateProxy],
    summary: BatchProbeSummary,
    *,
    run_id: str | None = None,
    created_at: str | None = None,
    source_candidates_hash: str | None = None,
    source_candidates_run_id: str | None = None,
    source_probe_summary_hash: str | None = None,
    source_probe_summary_run_id: str | None = None,
) -> None:
    """Write the sensitive passed-candidate payload atomically."""
    atomic_write_json(
        path,
        build_passed_candidates_payload(
            candidates,
            summary,
            run_id=run_id,
            created_at=created_at,
            source_candidates_hash=source_candidates_hash,
            source_candidates_run_id=source_candidates_run_id,
            source_probe_summary_hash=source_probe_summary_hash,
            source_probe_summary_run_id=source_probe_summary_run_id,
        ),
    )


def write_probe_artifacts(
    summary_path: str | Path,
    passed_candidates_path: str | Path,
    candidates: list[CandidateProxy],
    summary: BatchProbeSummary,
    *,
    source_candidates_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    """Write both the redacted summary and sensitive passed-candidate artifacts."""
    run_id = generate_run_id("probe")
    created_at = _utc_now_iso8601()
    source_candidates_hash = None if source_candidates_payload is None else compute_artifact_hash(source_candidates_payload)
    source_candidates_run_id = None
    if isinstance(source_candidates_payload, dict):
        source_candidates_run_id = _coerce_optional_str(source_candidates_payload.get("run_id"))
    probe_summary_payload = serialize_batch_probe_summary(
        summary,
        run_id=run_id,
        created_at=created_at,
        source_candidates_hash=source_candidates_hash,
        source_candidates_run_id=source_candidates_run_id,
    )
    write_batch_probe_summary(
        summary_path,
        summary,
        run_id=run_id,
        created_at=created_at,
        source_candidates_hash=source_candidates_hash,
        source_candidates_run_id=source_candidates_run_id,
    )
    write_passed_candidates(
        passed_candidates_path,
        candidates,
        summary,
        run_id=run_id,
        created_at=created_at,
        source_candidates_hash=source_candidates_hash,
        source_candidates_run_id=source_candidates_run_id,
        source_probe_summary_hash=compute_artifact_hash(probe_summary_payload),
        source_probe_summary_run_id=run_id,
    )
    return {
        "summary_path": str(Path(summary_path)),
        "passed_candidates_path": str(Path(passed_candidates_path)),
        "passed_count": summary.passed_count,
        "retained_passed_count": summary.retained_passed_count,
        "truncated": summary.truncated,
        "attempted_count": summary.attempted_count,
        "skipped_count": summary.skipped_count,
        "failed_count": summary.failed_count,
    }


def _redact_free_text(value: str) -> str:
    """Redact free text conservatively for review-safe summary output."""
    if len(value) <= 8:
        return "<REDACTED>"
    return f"{value[:4]}<REDACTED>{value[-4:]}"


def _utc_now_iso8601() -> str:
    """Return one UTC timestamp with a Z suffix."""
    from datetime import datetime
    from datetime import timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_optional_str(value: object) -> str | None:
    """Coerce one optional string value."""
    if isinstance(value, str) and value:
        return value
    return None
