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
        message=message,
        can_cancel=False,
        redacted_log_tail=[],
    )
