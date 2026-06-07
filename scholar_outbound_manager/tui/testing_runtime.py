"""Typed runtime contracts for the Testing workbench."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TestingPhase = Literal[
    "idle",
    "catalog_ready",
    "probing",
    "finalizing",
    "completed",
    "warning",
    "stale",
    "failed",
    "cancelled",
]

TestingProgressMode = Literal["none", "phase_only", "live_candidate_stream"]
TestingTableScope = Literal["all_candidates", "testable_only", "passed_only", "failed_only"]


@dataclass(slots=True, frozen=True)
class TestingSummary:
    subscription_configured: bool
    fetched_count: int
    candidate_count: int
    supported_count: int
    unsupported_count: int
    experimental_disabled_count: int
    attempted_count: int
    passed_count: int
    failed_count: int
    full_access_count: int
    query_blocked_count: int
    transport_failed_count: int
    last_fetch_status: str | None
    last_probe_status: str | None
    total_candidates: int
    supported_candidates: int
    unsupported_candidates: int
    experimental_disabled: int
    testable_candidates: int
    visible_rows: int
    attempted: int
    passed: int
    failed: int
    skipped: int
    pending: int
    running: int
    stale: int
    table_scope: TestingTableScope


@dataclass(slots=True, frozen=True)
class TestingRuntimeState:
    phase: TestingPhase
    progress_mode: TestingProgressMode
    current: int
    total: int
    current_candidate_label: str | None
    parallel_workers: int | None
    elapsed_seconds: float | None
    process_exit_code: int | None
    process_completed: bool
    artifacts_loaded: bool
    lineage_consistent: bool | None
    completion_message: str | None
    warning_message: str | None
    failure_message: str | None


def idle_testing_runtime() -> TestingRuntimeState:
    return TestingRuntimeState(
        phase="idle",
        progress_mode="none",
        current=0,
        total=0,
        current_candidate_label=None,
        parallel_workers=None,
        elapsed_seconds=None,
        process_exit_code=None,
        process_completed=False,
        artifacts_loaded=False,
        lineage_consistent=None,
        completion_message=None,
        warning_message=None,
        failure_message=None,
    )
