"""Workflow and tab descriptors for the optional TUI."""

from __future__ import annotations

from dataclasses import dataclass


MAIN_TABS: tuple[str, ...] = (
    "Dashboard",
    "Preflight",
    "Fetch & Probe",
    "Artifacts",
    "Selection",
    "Sidecar",
    "Pool",
    "Troubleshooting",
    "Snippets",
)

WIZARD_STEPS: tuple[str, ...] = (
    "preflight",
    "fetch",
    "probe",
    "artifact_check",
    "select_candidate",
    "stage_sidecar",
    "restart_validate",
    "snippet_export",
)


@dataclass(slots=True)
class WorkflowStep:
    """Describe one wizard step and its gating state."""

    key: str
    title: str
    allow_continue: bool = True
    warning: str | None = None
    blocking_reason: str | None = None


def build_workflow_steps(
    *,
    artifact_check_result: dict[str, object] | None = None,
) -> list[WorkflowStep]:
    """Build the workflow step descriptors in the documented order."""
    steps = [
        WorkflowStep("preflight", "Step 1: Preflight"),
        WorkflowStep("fetch", "Step 2: Fetch"),
        WorkflowStep("probe", "Step 3: Probe"),
        evaluate_artifact_check_step(artifact_check_result),
        WorkflowStep("select_candidate", "Step 5: Select Candidate"),
        WorkflowStep("stage_sidecar", "Step 6: Stage Sidecar"),
        WorkflowStep("restart_validate", "Step 7: Restart & Validate"),
        WorkflowStep("snippet_export", "Step 8: Snippet Export"),
    ]
    return steps


def evaluate_artifact_check_step(result: dict[str, object] | None) -> WorkflowStep:
    """Gate the artifact-check step according to the documented rules."""
    if result is None:
        return WorkflowStep("artifact_check", "Step 4: Artifact Check")

    overall_consistent = result.get("overall_consistent")
    if overall_consistent is True:
        return WorkflowStep("artifact_check", "Step 4: Artifact Check", allow_continue=True)
    if overall_consistent is None:
        return WorkflowStep(
            "artifact_check",
            "Step 4: Artifact Check",
            allow_continue=True,
            warning="Artifact lineage is legacy or unknown; continuing is allowed with warning.",
        )
    return WorkflowStep(
        "artifact_check",
        "Step 4: Artifact Check",
        allow_continue=False,
        blocking_reason="Artifact mismatch detected; rerun fetch and probe before continuing.",
    )

