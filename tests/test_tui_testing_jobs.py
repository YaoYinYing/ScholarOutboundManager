from __future__ import annotations

from scholar_outbound_manager.tui.testing_jobs import idle_testing_job_state
from scholar_outbound_manager.tui.testing_jobs import update_testing_job_state


def test_idle_testing_job_state_defaults_to_zero_counts() -> None:
    state = idle_testing_job_state()

    assert state.status == "idle"
    assert state.current == 0
    assert state.passed == 0
    assert state.failed == 0
    assert state.skipped == 0


def test_update_testing_job_state_updates_progress_counts() -> None:
    state = idle_testing_job_state(message="Idle.")
    updated = update_testing_job_state(
        state,
        status="probing",
        current=2,
        total=5,
        passed=1,
        failed=1,
        skipped=0,
        message="Probing: 2 / 5",
        can_cancel=True,
    )

    assert updated.status == "probing"
    assert updated.current == 2
    assert updated.total == 5
    assert updated.passed == 1
    assert updated.failed == 1
    assert updated.can_cancel is True
