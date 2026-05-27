"""Tests for artifact CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from scholar_outbound_manager import cli
from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash


def test_artifact_check_returns_zero_for_matching_chain(tmp_path: Path, capsys) -> None:
    candidates_path, probe_path, passed_path = _write_matching_artifacts(tmp_path)

    exit_code = cli.main(
        [
            "artifact",
            "check",
            "--candidates",
            str(candidates_path),
            "--probe-summary",
            str(probe_path),
            "--passed-candidates",
            str(passed_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "overall_consistent: true" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_artifact_check_returns_one_for_mismatch(tmp_path: Path, capsys) -> None:
    candidates_path, probe_path, passed_path = _write_matching_artifacts(tmp_path)
    passed_payload = json.loads(passed_path.read_text(encoding="utf-8"))
    passed_payload["source_candidates_hash"] = "deadbeefdeadbeef"
    passed_path.write_text(json.dumps(passed_payload), encoding="utf-8")

    exit_code = cli.main(
        [
            "artifact",
            "check",
            "--candidates",
            str(candidates_path),
            "--probe-summary",
            str(probe_path),
            "--passed-candidates",
            str(passed_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "overall_consistent: false" in captured.out


def test_artifact_check_returns_two_for_legacy_unknown(tmp_path: Path, capsys) -> None:
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(json.dumps({"schema_version": 1, "candidates": []}), encoding="utf-8")

    exit_code = cli.main(["artifact", "check", "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "overall_consistent: unknown" in captured.out


def test_artifact_explain_probe_filters_by_candidate_id(tmp_path: Path, capsys) -> None:
    probe_path = tmp_path / "probe_summary.json"
    probe_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact_type": "probe_summary",
                "run_id": "probe-1",
                "created_at": "2026-05-27T00:00:00Z",
                "records": [
                    {
                        "index": 0,
                        "candidate_id": "candidate-001",
                        "candidate_name": "US-LA-01",
                        "attempted": True,
                        "passed": False,
                        "skipped": False,
                        "skip_reason": None,
                        "summary": {"result": {"home_status": 403, "query_status": 403, "failure_markers": ["stage_home_blocked"]}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(
        ["artifact", "explain-probe", "--probe-summary", str(probe_path), "--candidate-id", "candidate-001"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["record_count"] == 1
    assert payload["records"][0]["candidate_id"] == "candidate-001"
    _assert_no_secrets(captured.out + captured.err)


def _write_matching_artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    candidates_payload = {
        "schema_version": 1,
        "artifact_type": "candidates",
        "run_id": "fetch-1",
        "created_at": "2026-05-27T00:00:00Z",
        "candidates": [{"raw_name": "US-LA-01"}],
    }
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(json.dumps(candidates_payload), encoding="utf-8")
    candidates_hash = compute_artifact_hash(candidates_payload)

    probe_payload = {
        "schema_version": 1,
        "artifact_type": "probe_summary",
        "run_id": "probe-1",
        "created_at": "2026-05-27T00:01:00Z",
        "source_candidates_hash": candidates_hash,
        "source_candidates_run_id": "fetch-1",
        "records": [],
    }
    probe_path = tmp_path / "probe_summary.json"
    probe_path.write_text(json.dumps(probe_payload), encoding="utf-8")
    probe_hash = compute_artifact_hash(probe_payload)

    passed_payload = {
        "schema_version": 1,
        "artifact_type": "passed_candidates",
        "run_id": "probe-1",
        "created_at": "2026-05-27T00:01:00Z",
        "source_candidates_hash": candidates_hash,
        "source_candidates_run_id": "fetch-1",
        "source_probe_summary_hash": probe_hash,
        "source_probe_summary_run_id": "probe-1",
        "candidates": [],
    }
    passed_path = tmp_path / "passed_candidates.json"
    passed_path.write_text(json.dumps(passed_payload), encoding="utf-8")
    return candidates_path, probe_path, passed_path


def _assert_no_secrets(rendered: str) -> None:
    lowered = rendered.lower()
    assert "raw_uri" not in lowered
    assert "public_key_placeholder" not in lowered
    assert "password_placeholder" not in lowered
    assert "00000000-0000-0000-0000-000000000000" not in lowered
