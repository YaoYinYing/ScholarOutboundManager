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
                        "candidate_protocol": "hysteria2",
                        "candidate_name": "US-LA-01",
                        "attempted": True,
                        "passed": False,
                        "skipped": False,
                        "skip_reason": None,
                        "summary": {
                            "attempt_count": 2,
                            "transport_retry_count_used": 1,
                            "warmup_attempt_count": 1,
                            "final_attempt_index": 1,
                            "result": {
                                "home_status": None,
                                "query_status": None,
                                "error": "TLS/SSL connection has been closed (EOF)",
                                "failure_markers": ["transport_error", "stage_transport_failed"],
                            }
                        },
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
    assert payload["records"][0]["protocol"] == "hysteria2"
    assert payload["records"][0]["region_hint"] == "US-LA"
    assert payload["records"][0]["error_category"] == "ssl_eof"
    assert payload["records"][0]["attempt_count"] == 2
    assert payload["records"][0]["retries_used"] == 1
    assert payload["records"][0]["warmup_attempts"] == 1
    assert payload["records"][0]["final_attempt_index"] == 1
    _assert_no_secrets(captured.out + captured.err)


def test_artifact_explain_probe_filters_by_protocol_error_category_and_marker(tmp_path: Path, capsys) -> None:
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
                        "candidate_protocol": "hysteria2",
                        "candidate_name": "HK-01",
                        "attempted": True,
                        "passed": False,
                        "skipped": False,
                        "skip_reason": None,
                        "summary": {
                            "attempt_count": 2,
                            "transport_retry_count_used": 1,
                            "warmup_attempt_count": 1,
                            "final_attempt_index": 1,
                            "result": {
                                "home_status": None,
                                "query_status": None,
                                "error": "TLS/SSL connection has been closed (EOF)",
                                "failure_markers": ["transport_error", "stage_transport_failed"],
                            }
                        },
                    },
                    {
                        "index": 1,
                        "candidate_id": "candidate-002",
                        "candidate_protocol": "vless",
                        "candidate_name": "US-02",
                        "attempted": True,
                        "passed": False,
                        "skipped": False,
                        "skip_reason": None,
                        "summary": {
                            "attempt_count": 1,
                            "transport_retry_count_used": 0,
                            "warmup_attempt_count": 0,
                            "final_attempt_index": 0,
                            "result": {
                                "home_status": 403,
                                "query_status": 403,
                                "error": None,
                                "failure_markers": ["stage_home_blocked"],
                            }
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "artifact",
            "explain-probe",
            "--probe-summary",
            str(probe_path),
            "--protocol",
            "hysteria2",
            "--error-category",
            "ssl_eof",
            "--marker",
            "stage_transport_failed",
        ]
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
    assert "server_name" not in lowered
    assert "hy2.example.invalid" not in lowered
    assert "00000000-0000-0000-0000-000000000000" not in lowered
