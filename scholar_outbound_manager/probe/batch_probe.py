"""Batch probe orchestration helpers."""

from __future__ import annotations

import concurrent.futures
import hashlib
import re
from dataclasses import replace
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
    """Define options for one batch probe workflow."""

    candidate_options: CandidateProbeOptions = field(default_factory=CandidateProbeOptions)
    max_workers: int = 1
    max_candidates: int | None = None
    max_passed: int | None = None
    stop_after_max_passed: bool = True
    keep_all_passed: bool = False
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
    """Summarize one batch probe run."""

    total_count: int
    attempted_count: int
    skipped_count: int
    passed_count: int
    failed_count: int
    parallel_workers: int = 1
    keep_all_passed: bool = False
    stop_after_max_passed: bool = True
    retained_passed_count: int = 0
    truncated: bool = False
    records: list[BatchProbeRecord] = field(default_factory=list)
    passed_indices: list[int] = field(default_factory=list)
    passed_candidate_ids: list[str] = field(default_factory=list)


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
    """Probe candidates and summarize the ordered outcomes."""
    batch_options = options or BatchProbeOptions()
    _validate_batch_options(batch_options)
    effective_options = _effective_batch_options(batch_options)

    if (
        effective_options.max_workers > 1
        and not (
            effective_options.max_passed is not None
            and effective_options.stop_after_max_passed
            and not effective_options.keep_all_passed
        )
    ):
        return _probe_candidates_parallel(
            candidates,
            xray_config,
            effective_options,
            probe_candidate_func,
        )
    return _probe_candidates_sequential(
        candidates,
        xray_config,
        effective_options,
        probe_candidate_func,
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
    if options.max_workers <= 0:
        raise ValueError("max_workers must be greater than 0.")
    if options.max_candidates is not None and options.max_candidates <= 0:
        raise ValueError("max_candidates must be greater than 0 when provided.")
    if options.max_passed is not None and options.max_passed <= 0:
        raise ValueError("max_passed must be greater than 0 when provided.")


def _effective_batch_options(options: BatchProbeOptions) -> BatchProbeOptions:
    """Normalize batch options for keep-all-passed semantics."""
    if not options.keep_all_passed:
        return options
    return BatchProbeOptions(
        candidate_options=options.candidate_options,
        max_workers=options.max_workers,
        max_candidates=options.max_candidates,
        max_passed=None,
        stop_after_max_passed=False,
        keep_all_passed=True,
        include_unsupported=options.include_unsupported,
    )


def _probe_candidates_sequential(
    candidates: list[CandidateProxy],
    xray_config: XrayConfig,
    options: BatchProbeOptions,
    probe_candidate_func: ProbeCandidateCallable,
) -> BatchProbeSummary:
    """Probe candidates sequentially and preserve the historical smoke semantics."""
    records: list[BatchProbeRecord] = []
    actual_passed_indices: list[int] = []
    actual_passed_candidate_ids: list[str] = []

    for index, candidate in _iter_candidate_scope(candidates, options.max_candidates):
        if (
            options.max_passed is not None
            and options.stop_after_max_passed
            and len(actual_passed_indices) >= options.max_passed
        ):
            break

        candidate_id = build_candidate_id(candidate, index)
        candidate_name = candidate.raw_name or f"candidate-{index + 1:03d}"

        if not candidate.supported and not options.include_unsupported:
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

        summary = _probe_one_candidate(
            candidate=candidate,
            index=index,
            xray_config=xray_config,
            candidate_id=candidate_id,
            base_candidate_options=options.candidate_options,
            probe_candidate_func=probe_candidate_func,
        )
        passed = is_probe_passed(summary.result)
        if passed:
            actual_passed_indices.append(index)
            actual_passed_candidate_ids.append(candidate_id)

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

    return _finalize_batch_summary(
        records=records,
        total_count=len(candidates),
        options=options,
        actual_passed_indices=actual_passed_indices,
        actual_passed_candidate_ids=actual_passed_candidate_ids,
    )


def _probe_candidates_parallel(
    candidates: list[CandidateProxy],
    xray_config: XrayConfig,
    options: BatchProbeOptions,
    probe_candidate_func: ProbeCandidateCallable,
) -> BatchProbeSummary:
    """Probe candidates concurrently while keeping record order stable."""
    ordered_records: list[BatchProbeRecord] = []
    futures: dict[concurrent.futures.Future[CandidateProbeSummary], tuple[int, CandidateProxy, str, str]] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=options.max_workers) as executor:
        for index, candidate in _iter_candidate_scope(candidates, options.max_candidates):
            candidate_id = build_candidate_id(candidate, index)
            candidate_name = candidate.raw_name or f"candidate-{index + 1:03d}"
            if not candidate.supported and not options.include_unsupported:
                ordered_records.append(
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

            future = executor.submit(
                _probe_one_candidate,
                candidate,
                index,
                xray_config,
                candidate_id,
                options.candidate_options,
                probe_candidate_func,
            )
            futures[future] = (index, candidate, candidate_id, candidate_name)

        attempted_records: dict[int, BatchProbeRecord] = {}
        for future in concurrent.futures.as_completed(futures):
            index, candidate, candidate_id, candidate_name = futures[future]
            try:
                summary = future.result()
            except Exception as exc:  # pragma: no cover - defensive future boundary
                summary = _build_exception_probe_summary(
                    candidate_id=candidate_id,
                    xray_config=xray_config,
                    runtime_config_name=_build_runtime_config_name(
                        options.candidate_options.runtime_config_name,
                        index,
                        candidate_id,
                    ),
                    error=f"batch probe exception: {exc}",
                )
            attempted_records[index] = BatchProbeRecord(
                index=index,
                candidate_id=candidate_id,
                candidate_name=candidate_name,
                attempted=True,
                passed=is_probe_passed(summary.result),
                skipped=False,
                skip_reason=None,
                summary=summary,
            )

    ordered_records.extend(
        attempted_records[index]
        for index in sorted(attempted_records)
    )
    ordered_records.sort(key=lambda record: record.index)
    actual_passed_indices = [record.index for record in ordered_records if record.passed]
    actual_passed_candidate_ids = [record.candidate_id for record in ordered_records if record.passed]
    return _finalize_batch_summary(
        records=ordered_records,
        total_count=len(candidates),
        options=options,
        actual_passed_indices=actual_passed_indices,
        actual_passed_candidate_ids=actual_passed_candidate_ids,
    )


def _iter_candidate_scope(
    candidates: list[CandidateProxy],
    max_candidates: int | None,
):
    """Iterate over the scoped candidate set with stable indices."""
    scoped = candidates if max_candidates is None else candidates[:max_candidates]
    return enumerate(scoped)


def _probe_one_candidate(
    candidate: CandidateProxy,
    index: int,
    xray_config: XrayConfig,
    candidate_id: str,
    base_candidate_options: CandidateProbeOptions,
    probe_candidate_func: ProbeCandidateCallable,
) -> CandidateProbeSummary:
    """Probe one candidate with a unique runtime config name."""
    candidate_options = replace(
        base_candidate_options,
        runtime_config_name=_build_runtime_config_name(
            base_candidate_options.runtime_config_name,
            index,
            candidate_id,
        ),
    )
    try:
        return probe_candidate_func(
            candidate,
            xray_config,
            candidate_id,
            candidate_options,
        )
    except Exception as exc:  # noqa: BLE001
        return _build_exception_probe_summary(
            candidate_id=candidate_id,
            xray_config=xray_config,
            runtime_config_name=candidate_options.runtime_config_name,
            error=f"batch probe exception: {exc}",
        )


def _build_runtime_config_name(base_name: str, index: int, candidate_id: str) -> str:
    """Build one unique, sanitized runtime config name for a candidate probe."""
    base_path = Path(base_name)
    stem = base_path.stem
    suffix = base_path.suffix or ".json"
    safe_candidate_id = re.sub(r"[^0-9A-Za-z._-]+", "_", candidate_id).strip("_")
    return f"{stem}_{index:03d}_{safe_candidate_id}{suffix}"


def _finalize_batch_summary(
    *,
    records: list[BatchProbeRecord],
    total_count: int,
    options: BatchProbeOptions,
    actual_passed_indices: list[int],
    actual_passed_candidate_ids: list[str],
) -> BatchProbeSummary:
    """Build the final batch summary with actual and retained pass counts."""
    actual_passed_index_set = set(actual_passed_indices)
    if options.keep_all_passed or options.max_passed is None:
        retained_passed_indices = list(actual_passed_indices)
        retained_passed_candidate_ids = list(actual_passed_candidate_ids)
        truncated = False
    else:
        retained_passed_indices = list(actual_passed_indices[: options.max_passed])
        retained_passed_candidate_ids = list(actual_passed_candidate_ids[: options.max_passed])
        truncated = len(retained_passed_indices) < len(actual_passed_indices)

    attempted_count = sum(1 for record in records if record.attempted)
    skipped_count = sum(1 for record in records if record.skipped)
    failed_count = sum(
        1
        for record in records
        if record.attempted and record.index not in actual_passed_index_set
    )
    return BatchProbeSummary(
        total_count=total_count,
        attempted_count=attempted_count,
        skipped_count=skipped_count,
        passed_count=len(actual_passed_indices),
        failed_count=failed_count,
        parallel_workers=options.max_workers,
        keep_all_passed=options.keep_all_passed,
        stop_after_max_passed=options.stop_after_max_passed,
        retained_passed_count=len(retained_passed_indices),
        truncated=truncated,
        records=records,
        passed_indices=retained_passed_indices,
        passed_candidate_ids=retained_passed_candidate_ids,
    )


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
