"""Tests for the Logs screen model."""

from __future__ import annotations

from scholar_outbound_manager.tui.view_model import build_logs_summary


def test_logs_summary_exposes_rollback_boundary() -> None:
    summary = build_logs_summary(
        {
            "logs_screen": {
                "latest_snapshot_id": "snap-1",
                "latest_snapshot_reason": "pre_probe",
                "rollback_warning": [
                    "Artifact rollback restores local artifacts only.",
                    "It does not restart sidecar.",
                ],
                "last_action": {
                    "title": "Artifact Check",
                    "succeeded": True,
                    "summary": "Artifact Check completed successfully.",
                },
            }
        }
    )

    assert summary.action_rows[0][0] == "Artifact Check"
    assert summary.snapshot_rows[0][0] == "snap-1"
    assert "Artifact rollback restores local artifacts only." in summary.rollback_warning
