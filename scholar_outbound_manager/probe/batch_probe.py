"""Sequential batch probe orchestration helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Callable

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import ProbeResult
from scholar_outbound_manager.models import XrayConfig
from scholar_outbound_manager.probe.candidate_probe import CandidateProbeOptions
from scholar_outbound_manager.probe.candidate_probe import CandidateProbeSummary
from scholar_outbound_manager.probe.candidate_probe import probe_candidate


@dataclass(slots=True)
class BatchProbeOptions:
    """Define options for one sequential batch probe workflow."""

    candidate_options: CandidateProbeOptions = field(default_factory=CandidateProbeOptions)
    max_candidates: int | None = None
    max_passed: int | None = None
    stop_after_max_passed: bool = True
    include_unsupported: bool = False


@dataclass(slots=True)
class BatchProbeRecord:
    """Record one candidate outcome inside a batch probe run."""

    index: int
    candidate_id: str
    candidate_name: str
    attempted: bool
    passed: bool
    skipped: bool
    skip_reason: str | None
    summary: CandidateProbeSummary | None


@dataclass(slots=True)
class BatchProbeSummary:
    """Summarize one sequential batch probe run."""

    total_count: int
    attempted_count: int
    skipped_count: int
    passed_count: int
    failed_count: int
    records: list[BatchProbeRecord]
    passed_indices: list[int]
    passed_candidate_ids: list[str]


ProbeCandidateCallable = Callable[[CandidateProxy, XrayConfig, str, CandidateProbeOptions], CandidateProbeSummary]


def build_candidate_id(candidate: CandidateProxy, index: int) -> str:
    """Build one short, stable, irreversible candidate identifier."""
    payload = "|".join(
        [
            candidate.source_name,
            candidate.raw_name,
            candidate.protocol,
            candidate.address,
            str(candidate.port),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"candidate-{index + 1:03d}-{digest}"


def is_probe_passed(result: ProbeResult) -> bool:
    """Return whether one probe result satisfies the conservative passed predicate."""
    allowed_statuses = {200, 301, 302, 303, 307, 308}
    failing_stage_markers = {
        "stage_home_blocked",
        "stage_query_blocked",
        "stage_transport_failed",
        "stage_timeout",
        "stage_server_error",
    }
    if result.blocked or result.timeout or result.error is not None:
        return False
    if result.home_status not in allowed_statuses:
        return False
    if result.query_status is None:
        return False
    if result.query_status not in allowed_statuses:
        return False
    if any(marker in failing_stage_markers for marker in result.failure_markers):
        return False
    if result.failure_markers:
        return False
    return True


def probe_candidates_sequential(
    candidates: list[CandidateProxy],
    xray_config: XrayConfig,
    options: BatchProbeOptions | None = None,
    probe_candidate_func: ProbeCandidateCallable = probe_candidate,
) -> BatchProbeSummary:
    """Probe candidates sequentially and summarize the ordered outcomes."""
    batch_options = options or BatchProbeOptions()
    _validate_batch_options(batch_options)

    records: list[BatchProbeRecord] = []
    passed_indices: list[int] = []
    passed_candidate_ids: list[str] = []

    for index, candidate in enumerate(candidates):
        if batch_options.max_candidates is not None and len(records) >= batch_options.max_candidates:
            break
        if (
            batch_options.max_passed is not None
            and batch_options.stop_after_max_passed
            and len(passed_indices) >= batch_options.max_passed
        ):
            break

        candidate_id = build_candidate_id(candidate, index)
        candidate_name = candidate.raw_name or f"candidate-{index + 1:03d}"

        if not candidate.supported and not batch_options.include_unsupported:
            records.append(
                BatchProbeRecord(
                    index=index,
                    candidate_id=candidate_id,
                    candidate_name=candidate_name,
                    attempted=False,
                    passed=False,
                    skipped=True,
                    skip_reason=candidate.unsupported_reason or "Candidate is marked unsupported.",
                    summary=None,
                )
            )
            continue

        try:
            summary = probe_candidate_func(
                candidate,
                xray_config,
                candidate_id,
                batch_options.candidate_options,
            )
        except Exception as exc:  # noqa: BLE001
            summary = _build_exception_probe_summary(
                candidate_id=candidate_id,
                xray_config=xray_config,
                runtime_config_name=batch_options.candidate_options.runtime_config_name,
                error=f"batch probe exception: {exc}",
            )

        passed = is_probe_passed(summary.result)
        if batch_options.max_passed is not None and len(passed_indices) >= batch_options.max_passed:
            passed = False
        if passed:
            passed_indices.append(index)
            passed_candidate_ids.append(candidate_id)

        records.append(
            BatchProbeRecord(
                index=index,
                candidate_id=candidate_id,
                candidate_name=candidate_name,
                attempted=True,
                passed=passed,
                skipped=False,
                skip_reason=None,
                summary=summary,
            )
        )

    attempted_count = sum(1 for record in records if record.attempted)
    skipped_count = sum(1 for record in records if record.skipped)
    passed_count = sum(1 for record in records if record.passed)
    failed_count = sum(1 for record in records if record.attempted and not record.passed)
    return BatchProbeSummary(
        total_count=len(candidates),
        attempted_count=attempted_count,
        skipped_count=skipped_count,
        passed_count=passed_count,
        failed_count=failed_count,
        records=records,
        passed_indices=passed_indices,
        passed_candidate_ids=passed_candidate_ids,
    )


def select_passed_candidates(
    candidates: list[CandidateProxy],
    summary: BatchProbeSummary,
) -> list[CandidateProxy]:
    """Select passed candidates from the original candidate list using passed indices."""
    selected: list[CandidateProxy] = []
    for index in summary.passed_indices:
        if index < 0 or index >= len(candidates):
            raise ValueError(f"Passed candidate index {index} is out of range.")
        selected.append(candidates[index])
    return selected


def _validate_batch_options(options: BatchProbeOptions) -> None:
    """Validate batch probe options."""
    if options.max_candidates is not None and options.max_candidates <= 0:
        raise ValueError("max_candidates must be greater than 0 when provided.")
    if options.max_passed is not None and options.max_passed <= 0:
        raise ValueError("max_passed must be greater than 0 when provided.")


def _build_exception_probe_summary(
    *,
    candidate_id: str,
    xray_config: XrayConfig,
    runtime_config_name: str,
    error: str,
) -> CandidateProbeSummary:
    """Build one synthetic candidate probe summary for batch-level exceptions."""
    return CandidateProbeSummary(
        candidate_id=candidate_id,
        runtime_config_path=str(Path(xray_config.runtime_dir) / runtime_config_name),
        local_socks_host=xray_config.local_socks_host,
        local_socks_port=xray_config.local_socks_port,
        xray_started=False,
        xray_test_passed=None,
        startup_ready=False,
        result=ProbeResult(
            candidate_id=candidate_id,
            home_status=None,
            query_status=None,
            blocked=False,
            timeout=False,
            error=error,
            failure_markers=["batch_probe_exception"],
            latency_ms=None,
            checked_at=_utc_now_iso8601(),
        ),
    )


def _utc_now_iso8601() -> str:
    """Return the current UTC timestamp in ISO 8601 format with a Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
