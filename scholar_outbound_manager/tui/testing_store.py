"""Testing page store state builders and reducers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from scholar_outbound_manager.tui.path_resolver import UserDataPaths
from scholar_outbound_manager.tui.state import TestingArtifactsState
from scholar_outbound_manager.tui.state import TestingStoreState
from scholar_outbound_manager.tui.testing_artifacts import load_testing_artifacts
from scholar_outbound_manager.tui.testing_events import TestingEvent
from scholar_outbound_manager.tui.testing_jobs import TestingJobState
from scholar_outbound_manager.tui.testing_jobs import idle_testing_job_state
from scholar_outbound_manager.tui.testing_jobs import update_testing_job_state
from scholar_outbound_manager.tui.testing_model import CandidateTestRow
from scholar_outbound_manager.tui.testing_model import build_testing_screen_state
from scholar_outbound_manager.tui.view_model import redact_text


def build_testing_store_state(
    *,
    config_path: str,
    user_data_paths: UserDataPaths,
    selected_index: int | None = None,
) -> TestingStoreState:
    screen = build_testing_screen_state(
        config_path=config_path,
        user_data_paths=user_data_paths,
        selected_index=selected_index,
    )
    artifacts = load_testing_artifacts(user_data_paths)
    return TestingStoreState(
        artifacts=TestingArtifactsState(
            candidates_exists=artifacts.candidates_exists,
            probe_summary_exists=artifacts.probe_summary_exists,
            passed_candidates_exists=artifacts.passed_candidates_exists,
            lineage_consistent=artifacts.lineage_consistent,
            warnings=tuple(artifacts.warnings),
            source_hashes=dict(artifacts.source_hashes),
        ),
        rows=tuple(screen.rows),
        selected_index=screen.selected_index or 0,
        job=idle_testing_job_state(message=screen.job_state.title()),
        summary=screen.summary,
        stale_warning=screen.inspector.artifact_warning,
        recent_events=tuple(screen.log_lines),
    )


def apply_testing_event(state: TestingStoreState, event: TestingEvent) -> TestingStoreState:
    safe_message = redact_text(event.message)
    rows = list(state.rows)
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
            break
    passed = sum(1 for row in rows if row.status_icon == "PASS")
    failed = sum(1 for row in rows if row.status_icon == "FAIL")
    skipped = sum(1 for row in rows if row.status_icon == "SKIP")
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
    summary = replace(
        state.summary,
        attempted_count=job.current,
        passed_count=passed,
        failed_count=failed,
    )
    return replace(
        state,
        rows=tuple(rows),
        job=job,
        summary=summary,
        recent_events=tuple([*state.recent_events[-9:], safe_message]),
    )
