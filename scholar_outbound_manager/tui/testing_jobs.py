"""Job models for the TUI Testing workbench."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class TestingJobState:
    """Represent one fetch/probe job state for the Testing page."""

    job_id: str | None
    kind: str
    status: str
    started_at: str | None
    finished_at: str | None
    current: int
    total: int
    passed: int
    failed: int
    skipped: int
    message: str
    can_cancel: bool
    redacted_log_tail: list[str]


@dataclass(slots=True, frozen=True)
class TestingJobEvent:
    """Represent one redacted fetch/probe event line."""

    type: str
    message: str
    current: int | None
    total: int | None
    redacted: bool = True


def update_testing_job_state(
    state: TestingJobState,
    *,
    status: str | None = None,
    current: int | None = None,
    total: int | None = None,
    passed: int | None = None,
    failed: int | None = None,
    skipped: int | None = None,
    message: str | None = None,
    can_cancel: bool | None = None,
    redacted_log_tail: list[str] | None = None,
) -> TestingJobState:
    """Return one updated job state."""
    return TestingJobState(
        job_id=state.job_id,
        kind=state.kind,
        status=state.status if status is None else status,
        started_at=state.started_at,
        finished_at=state.finished_at,
        current=state.current if current is None else current,
        total=state.total if total is None else total,
        passed=state.passed if passed is None else passed,
        failed=state.failed if failed is None else failed,
        skipped=state.skipped if skipped is None else skipped,
        message=state.message if message is None else message,
        can_cancel=state.can_cancel if can_cancel is None else can_cancel,
        redacted_log_tail=state.redacted_log_tail if redacted_log_tail is None else list(redacted_log_tail),
    )


class TestingJobRunner:
    """Future runner surface for live Testing jobs."""

    def fetch_subscription(self) -> TestingJobState:
        raise NotImplementedError("fetch_subscription is not implemented for the current backend.")

    def probe_candidates(self) -> TestingJobState:
        raise NotImplementedError("probe_candidates is not implemented for the current backend.")

    def retest_failed(self) -> TestingJobState:
        raise NotImplementedError("retest_failed is not implemented for the current backend.")

    def cancel(self) -> TestingJobState:
        raise NotImplementedError("cancel is not implemented for the current backend.")


def idle_testing_job_state(*, message: str = "Idle.") -> TestingJobState:
    """Return the default idle job state used by the current phase-level UI."""

    return TestingJobState(
        job_id=None,
        kind="none",
        status="idle",
        started_at=None,
        finished_at=None,
        current=0,
        total=0,
        passed=0,
        failed=0,
        skipped=0,
        message=message,
        can_cancel=False,
        redacted_log_tail=[],
    )
