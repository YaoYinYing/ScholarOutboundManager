"""Tests for workflow-oriented TUI step state."""

from __future__ import annotations

from scholar_outbound_manager.tui.workflow import WIZARD_STEPS
from scholar_outbound_manager.tui.workflow import build_workflow_steps
from scholar_outbound_manager.tui.workflow import evaluate_artifact_check_step


def test_workflow_steps_are_in_expected_order() -> None:
    """Keep the wizard steps aligned with the documented workflow."""
    assert WIZARD_STEPS == (
        "preflight",
        "fetch",
        "probe",
        "artifact_check",
        "select_candidate",
        "stage_sidecar",
        "restart_validate",
        "snippet_export",
    )

    built = build_workflow_steps()
    assert [step.key for step in built] == list(WIZARD_STEPS)


def test_wizard_blocks_artifact_mismatch_by_default() -> None:
    """Block continuation on artifact mismatch."""
    step = evaluate_artifact_check_step({"overall_consistent": False})

    assert step.allow_continue is False
    assert step.blocking_reason is not None


def test_wizard_allows_legacy_unknown_with_warning() -> None:
    """Allow legacy or unknown artifact lineage with warning."""
    step = evaluate_artifact_check_step({"overall_consistent": None})

    assert step.allow_continue is True
    assert step.warning is not None
