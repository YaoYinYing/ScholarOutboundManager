"""Testing page store state builders and reducers."""

from __future__ import annotations

from dataclasses import replace

from scholar_outbound_manager.tui.config_centered import summarize_config_centered_state
from scholar_outbound_manager.tui.path_resolver import UserDataPaths
from scholar_outbound_manager.tui.state import TestingArtifactsState
from scholar_outbound_manager.tui.state import TestingStoreState
from scholar_outbound_manager.tui.testing_artifacts import TestingArtifacts
from scholar_outbound_manager.tui.testing_artifacts import load_testing_artifacts
from scholar_outbound_manager.tui.testing_events import TestingEvent
from scholar_outbound_manager.tui.testing_jobs import idle_testing_job_state
from scholar_outbound_manager.tui.testing_jobs import update_testing_job_state
from scholar_outbound_manager.tui.testing_model import CandidateTestRow
from scholar_outbound_manager.tui.testing_model import build_candidate_test_rows
from scholar_outbound_manager.tui.testing_reconciliation import reconcile_testing_runtime
from scholar_outbound_manager.tui.testing_runtime import TestingRuntimeState
from scholar_outbound_manager.tui.testing_runtime import idle_testing_runtime
from scholar_outbound_manager.tui.view_model import redact_text


def build_testing_store_state(
    *,
    config_path: str,
    user_data_paths: UserDataPaths,
    selected_index: int | None = None,
    previous_runtime: TestingRuntimeState | None = None,
    recent_events: tuple[str, ...] | None = None,
) -> TestingStoreState:
    config_summary = summarize_config_centered_state(config_path)
    artifacts = load_testing_artifacts(user_data_paths)
    selected_route_ids = {
        str(entry.get("candidate_id"))
        for entry in config_summary.route_entries
        if isinstance(entry, dict) and entry.get("candidate_id")
    }
    rows = tuple(
        build_candidate_test_rows(
            candidates=artifacts.candidates,
            probe_records=artifacts.probe_results_by_candidate_id,
            passed_candidate_ids=artifacts.passed_ids,
            selected_route_ids=selected_route_ids,
            experimental_hysteria2=config_summary.experimental_hysteria2,
            artifacts_stale=artifacts.probe_summary_exists and not artifacts.lineage_consistent,
        )
    )
    selected = 0 if not rows else max(0, min(len(rows) - 1, selected_index or 0))
    summary = build_testing_summary(
        rows=list(rows),
        subscription_configured=config_summary.subscription_url_configured,
        artifacts=artifacts,
    )
    runtime_seed = idle_testing_runtime() if previous_runtime is None else previous_runtime
    runtime = _reconcile_runtime(runtime_seed, artifacts=artifacts, summary=summary)
    recent = tuple(artifacts.warnings[:1]) if recent_events is None or not recent_events else recent_events
    return TestingStoreState(
        artifacts=TestingArtifactsState(
            candidates_exists=artifacts.candidates_exists,
            probe_summary_exists=artifacts.probe_summary_exists,
            passed_candidates_exists=artifacts.passed_candidates_exists,
            lineage_consistent=artifacts.lineage_consistent,
            warnings=tuple(artifacts.warnings),
            source_hashes=dict(artifacts.source_hashes),
        ),
        rows=rows,
        selected_index=selected,
        job=idle_testing_job_state(message=_runtime_message(runtime)),
        runtime=runtime,
        summary=summary,
        stale_warning=runtime.warning_message or (artifacts.warnings[0] if artifacts.warnings else None),
        recent_events=recent,
    )


def apply_testing_event(state: TestingStoreState, event: TestingEvent) -> TestingStoreState:
    safe_message = redact_text(event.message)
    rows = list(state.rows)
    current_label = state.runtime.current_candidate_label
    for index, row in enumerate(rows):
        if event.candidate_id and row.candidate_id == event.candidate_id:
            rows[index] = CandidateTestRow(
                index=row.index,
                candidate_id=row.candidate_id,
                label=row.label,
                region_hint=row.region_hint,
                protocol=row.protocol,
                status_icon=event.status or row.status_icon,
                supported=row.supported,
                experimental=row.experimental,
                attempted=True if event.status in {"RUN", "PASS", "FAIL", "SKIP"} else row.attempted,
                passed=True if event.status == "PASS" else (False if event.status in {"FAIL", "SKIP"} else row.passed),
                latency_ms=event.latency_ms if event.latency_ms is not None else row.latency_ms,
                home_status=event.home_status if event.home_status is not None else row.home_status,
                query_status=event.query_status if event.query_status is not None else row.query_status,
                stage=event.stage or row.stage,
                markers=event.markers or row.markers,
                selected_for_route=row.selected_for_route,
            )
            current_label = row.label
            break
    passed = sum(1 for row in rows if row.status_icon == "PASS")
    failed = sum(1 for row in rows if row.status_icon == "FAIL")
    skipped = sum(1 for row in rows if row.status_icon == "SKIP")
    pending = sum(1 for row in rows if row.status_icon == "PEND")
    running = sum(1 for row in rows if row.status_icon == "RUN")
    stale = sum(1 for row in rows if row.status_icon == "STALE")
    attempted = sum(1 for row in rows if row.attempted)
    summary = replace(
        state.summary,
        attempted_count=attempted,
        passed_count=passed,
        failed_count=failed,
        attempted=attempted,
        passed=passed,
        failed=failed,
        skipped=skipped,
        pending=pending,
        running=running,
        stale=stale,
    )
    job = update_testing_job_state(
        state.job,
        current=event.current if event.current is not None else state.job.current,
        total=event.total if event.total is not None else state.job.total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        message=safe_message,
        redacted_log_tail=[*state.job.redacted_log_tail[-9:], safe_message],
    )
    runtime = replace(
        state.runtime,
        current=event.current if event.current is not None else state.runtime.current,
        total=event.total if event.total is not None else state.runtime.total,
        current_candidate_label=current_label,
    )
    return replace(
        state,
        rows=tuple(rows),
        job=job,
        runtime=runtime,
        summary=summary,
        recent_events=tuple([*state.recent_events[-9:], safe_message]),
    )


def build_testing_summary(*, rows: list[CandidateTestRow], subscription_configured: bool, artifacts: TestingArtifacts):
    from scholar_outbound_manager.tui.testing_model import _build_testing_summary

    return _build_testing_summary(rows=rows, subscription_configured=subscription_configured, artifacts=artifacts)


def _reconcile_runtime(runtime: TestingRuntimeState, *, artifacts: TestingArtifacts, summary) -> TestingRuntimeState:
    reconciliation = reconcile_testing_runtime(
        runtime=runtime,
        testable_candidates=summary.testable_candidates,
        attempted_count=summary.attempted,
        passed_count=summary.passed,
        failed_count=summary.failed,
        skipped_count=summary.skipped,
        probe_summary_exists=artifacts.probe_summary_exists,
        passed_candidates_exists=artifacts.passed_candidates_exists,
        lineage_consistent=artifacts.lineage_consistent,
    )
    return replace(
        runtime,
        phase=reconciliation.phase,
        current=summary.attempted,
        total=summary.testable_candidates,
        parallel_workers=artifacts.parallel_workers,
        artifacts_loaded=artifacts.probe_summary_exists or artifacts.passed_candidates_exists,
        lineage_consistent=reconciliation.lineage_consistent,
        completion_message=reconciliation.completion_message,
        warning_message=reconciliation.warning_message,
    )


def _runtime_message(runtime: TestingRuntimeState) -> str:
    if runtime.completion_message:
        return runtime.completion_message
    if runtime.warning_message:
        return runtime.warning_message
    if runtime.failure_message:
        return runtime.failure_message
    if runtime.phase == "catalog_ready":
        return "Candidates fetched. Press Test Nodes."
    if runtime.phase == "probing":
        return "Running probe. Live per-candidate progress is not available for this backend yet."
    return "Idle. Fetch Subscription to populate candidates."
