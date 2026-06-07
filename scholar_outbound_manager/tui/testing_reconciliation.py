"""Artifact reconciliation rules for the Testing workbench."""

from __future__ import annotations

from dataclasses import dataclass

from scholar_outbound_manager.tui.testing_runtime import TestingPhase
from scholar_outbound_manager.tui.testing_runtime import TestingRuntimeState


@dataclass(slots=True, frozen=True)
class TestingArtifactReconciliation:
    phase: TestingPhase
    lineage_consistent: bool
    attempted_count: int
    passed_count: int
    failed_count: int
    skipped_count: int
    warnings: tuple[str, ...]
    completion_message: str | None
    warning_message: str | None


def reconcile_testing_runtime(
    *,
    runtime: TestingRuntimeState,
    testable_candidates: int,
    attempted_count: int,
    passed_count: int,
    failed_count: int,
    skipped_count: int,
    probe_summary_exists: bool,
    passed_candidates_exists: bool,
    lineage_consistent: bool,
) -> TestingArtifactReconciliation:
    warnings: list[str] = []
    completion_message: str | None = None
    warning_message: str | None = None

    if runtime.process_exit_code not in (None, 0):
        warning_message = runtime.failure_message or _failure_message_for_exit_code(runtime.process_exit_code)
        return TestingArtifactReconciliation(
            phase="failed",
            lineage_consistent=lineage_consistent,
            attempted_count=attempted_count,
            passed_count=passed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            warnings=(warning_message,),
            completion_message=None,
            warning_message=warning_message,
        )
    if runtime.process_completed:
        if not probe_summary_exists or not passed_candidates_exists:
            warning_message = "Probe process exited, but result artifacts were not found."
            warnings.append(warning_message)
            return TestingArtifactReconciliation(
                phase="warning",
                lineage_consistent=lineage_consistent,
                attempted_count=attempted_count,
                passed_count=passed_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                warnings=tuple(warnings),
                completion_message=None,
                warning_message=warning_message,
            )
        if not lineage_consistent:
            warning_message = "Probe artifacts do not match current candidates."
            warnings.append(warning_message)
            return TestingArtifactReconciliation(
                phase="stale",
                lineage_consistent=False,
                attempted_count=attempted_count,
                passed_count=passed_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                warnings=tuple(warnings),
                completion_message=None,
                warning_message=warning_message,
            )
        if testable_candidates > 0 and attempted_count == 0:
            warning_message = "Probe process exited, but no candidate results were loaded."
            warnings.append(warning_message)
            return TestingArtifactReconciliation(
                phase="warning",
                lineage_consistent=True,
                attempted_count=attempted_count,
                passed_count=passed_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                warnings=tuple(warnings),
                completion_message=None,
                warning_message=warning_message,
            )
        completion_message = "Probe completed and artifacts reconciled."
        return TestingArtifactReconciliation(
            phase="completed",
            lineage_consistent=True,
            attempted_count=attempted_count,
            passed_count=passed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            warnings=(),
            completion_message=completion_message,
            warning_message=None,
        )
    if probe_summary_exists and not lineage_consistent:
        warning_message = "Probe artifacts do not match current candidates."
        return TestingArtifactReconciliation(
            phase="stale",
            lineage_consistent=False,
            attempted_count=attempted_count,
            passed_count=passed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            warnings=(warning_message,),
            completion_message=None,
            warning_message=warning_message,
        )
    if probe_summary_exists and testable_candidates > 0 and attempted_count == 0:
        warning_message = "Probe artifacts are present, but no attempted candidate results were loaded."
        return TestingArtifactReconciliation(
            phase="warning",
            lineage_consistent=lineage_consistent,
            attempted_count=attempted_count,
            passed_count=passed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            warnings=(warning_message,),
            completion_message=None,
            warning_message=warning_message,
        )
    phase: TestingPhase = "catalog_ready" if testable_candidates > 0 else "idle"
    return TestingArtifactReconciliation(
        phase=phase,
        lineage_consistent=lineage_consistent,
        attempted_count=attempted_count,
        passed_count=passed_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        warnings=(),
        completion_message=None,
        warning_message=None,
    )


def _failure_message_for_exit_code(exit_code: int) -> str:
    if exit_code == 124:
        return "Probe timed out or was interrupted. Artifacts may be stale; rerun Test Nodes."
    return f"Probe failed with exit code {exit_code}."
