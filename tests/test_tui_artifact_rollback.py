"""Tests for TUI artifact snapshot and rollback helpers."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from scholar_outbound_manager.tui.artifact_rollback import create_artifact_snapshot
from scholar_outbound_manager.tui.artifact_rollback import list_artifact_snapshots
from scholar_outbound_manager.tui.artifact_rollback import rollback_artifact_snapshot


def test_create_snapshot_copies_existing_artifacts_and_records_missing(tmp_path: Path) -> None:
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text('{"candidates":["secret"]}', encoding="utf-8")

    snapshot = create_artifact_snapshot(
        reason="before_fetch",
        candidates_path=candidates_path,
        probe_summary_path=tmp_path / "state_data" / "probe_summary.json",
        passed_candidates_path=tmp_path / "state_data" / "passed_candidates.json",
        selected_candidate_path=tmp_path / "state_data" / "selected_candidate.json",
        pool_plan_path=tmp_path / "state_data" / "sidecar_pool_plan.json",
        snapshot_root=tmp_path / "state_data" / "tui" / "artifact_snapshots",
    )

    assert snapshot.files["candidates"].exists is True
    assert snapshot.files["probe_summary"].exists is False
    assert "state_data/tui/artifact_snapshots" in snapshot.files["candidates"].snapshot_path
    assert snapshot.files["candidates"].sha256


def test_list_and_rollback_snapshot_restores_previous_content(tmp_path: Path) -> None:
    selected_candidate_path = tmp_path / "state_data" / "selected_candidate.json"
    selected_candidate_path.parent.mkdir(parents=True, exist_ok=True)
    selected_candidate_path.write_text('{"selected":"before"}', encoding="utf-8")
    root = tmp_path / "state_data" / "tui" / "artifact_snapshots"

    snapshot = create_artifact_snapshot(
        reason="before_select",
        candidates_path=tmp_path / "candidates.json",
        probe_summary_path=tmp_path / "state_data" / "probe_summary.json",
        passed_candidates_path=tmp_path / "state_data" / "passed_candidates.json",
        selected_candidate_path=selected_candidate_path,
        pool_plan_path=tmp_path / "state_data" / "sidecar_pool_plan.json",
        snapshot_root=root,
    )
    selected_candidate_path.write_text('{"selected":"after"}', encoding="utf-8")

    snapshots = list_artifact_snapshots(root)
    result = rollback_artifact_snapshot(snapshot.snapshot_id, snapshot_root=root)

    assert snapshots[0].snapshot_id == snapshot.snapshot_id
    assert result.restored is True
    assert selected_candidate_path.read_text(encoding="utf-8") == '{"selected":"before"}'
    assert "network and systemd side effects were not undone" in result.message.lower()


def test_snapshot_metadata_does_not_print_file_content(tmp_path: Path) -> None:
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text("vless://secret@example.invalid", encoding="utf-8")
    root = tmp_path / "state_data" / "tui" / "artifact_snapshots"

    snapshot = create_artifact_snapshot(
        reason="before_probe",
        candidates_path=candidates_path,
        probe_summary_path=tmp_path / "state_data" / "probe_summary.json",
        passed_candidates_path=tmp_path / "state_data" / "passed_candidates.json",
        selected_candidate_path=tmp_path / "state_data" / "selected_candidate.json",
        pool_plan_path=tmp_path / "state_data" / "sidecar_pool_plan.json",
        snapshot_root=root,
    )
    metadata = json.dumps(asdict(snapshot), ensure_ascii=False)

    assert "vless://" not in metadata
