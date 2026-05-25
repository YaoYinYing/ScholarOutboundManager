"""Tests for safe artifact inspection helpers."""

from __future__ import annotations

import json

import pytest

from scholar_outbound_manager.inspect import format_generated_manifest_inspection
from scholar_outbound_manager.inspect import format_probe_summary_inspection
from scholar_outbound_manager.inspect import format_sensitive_candidates_inspection
from scholar_outbound_manager.inspect import inspect_generated_manifest
from scholar_outbound_manager.inspect import inspect_probe_summary
from scholar_outbound_manager.inspect import inspect_sensitive_candidates
from scholar_outbound_manager.inspect import load_json_file


def test_load_json_file_reads_mapping(tmp_path) -> None:
    """Load one mapping payload from disk."""
    json_path = tmp_path / "payload.json"
    json_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

    payload = load_json_file(json_path)

    assert payload["schema_version"] == 1


def test_load_json_file_rejects_invalid_json(tmp_path) -> None:
    """Raise ValueError for invalid JSON input."""
    json_path = tmp_path / "invalid.json"
    json_path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid.json"):
        load_json_file(json_path)


def test_load_json_file_rejects_non_mapping_top_level(tmp_path) -> None:
    """Require a mapping at the top level."""
    json_path = tmp_path / "list.json"
    json_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(ValueError, match="top level"):
        load_json_file(json_path)


def test_inspect_probe_summary_extracts_counts_and_markers(tmp_path) -> None:
    """Inspect a probe summary and aggregate failure markers."""
    summary_path = tmp_path / "probe_summary.json"
    summary_path.write_text(json.dumps(_make_probe_summary_payload()), encoding="utf-8")

    inspection = inspect_probe_summary(summary_path)

    assert inspection.schema_version == 1
    assert inspection.total_count == 3
    assert inspection.attempted_count == 2
    assert inspection.skipped_count == 1
    assert inspection.passed_count == 1
    assert inspection.failed_count == 1
    assert inspection.top_failure_markers == [("http_403", 2), ("captcha", 1)]
    assert inspection.passed_candidate_ids == ["candidate-001-abc123"]


def test_inspect_generated_manifest_extracts_summary_fields(tmp_path) -> None:
    """Inspect a generated manifest without exposing candidate credentials."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_make_manifest_payload()), encoding="utf-8")

    inspection = inspect_generated_manifest(manifest_path)

    assert inspection.schema_version == 1
    assert inspection.generated_at == "2026-05-25T00:00:00Z"
    assert inspection.selected_count == 1
    assert inspection.rejected_count == 2
    assert inspection.selected_tags == ["google-scholar-node-001"]
    assert inspection.rejected_reasons == ["Candidate was not selected.", "Unsupported transport."]


def test_inspect_sensitive_candidates_returns_metadata_only(tmp_path) -> None:
    """Inspect a sensitive payload without returning candidate contents."""
    sensitive_path = tmp_path / "passed_candidates.json"
    sensitive_path.write_text(json.dumps(_make_sensitive_payload()), encoding="utf-8")

    inspection = inspect_sensitive_candidates(sensitive_path)

    assert inspection.schema_version == 1
    assert inspection.sensitive is True
    assert inspection.candidate_count == 1
    assert inspection.passed_candidate_ids == ["candidate-001-abc123"]
    assert inspection.description == "This file contains selected proxy credentials and must not be committed."
    assert not hasattr(inspection, "candidates")


def test_format_probe_summary_inspection_excludes_sensitive_values(tmp_path, capsys) -> None:
    """Format probe summary output without exposing secrets."""
    summary_path = tmp_path / "probe_summary.json"
    summary_path.write_text(json.dumps(_make_probe_summary_payload()), encoding="utf-8")

    rendered = format_probe_summary_inspection(inspect_probe_summary(summary_path))
    captured = capsys.readouterr()

    assert "Probe summary:" in rendered
    assert "total_count: 3" in rendered
    assert "http_403: 2" in rendered
    assert "candidate-001-abc123" in rendered
    assert "vless://" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered
    assert captured.out == ""
    assert captured.err == ""


def test_format_generated_manifest_inspection_lists_selected_tags(tmp_path) -> None:
    """Format manifest inspection output for CLI rendering."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_make_manifest_payload()), encoding="utf-8")

    rendered = format_generated_manifest_inspection(inspect_generated_manifest(manifest_path))

    assert "Generated manifest:" in rendered
    assert "google-scholar-node-001" in rendered
    assert "Candidate was not selected." in rendered
    assert "vless://" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered


def test_format_sensitive_candidates_inspection_includes_warning(tmp_path) -> None:
    """Format sensitive candidate inspection output without candidate contents."""
    sensitive_path = tmp_path / "passed_candidates.json"
    sensitive_path.write_text(json.dumps(_make_sensitive_payload()), encoding="utf-8")

    rendered = format_sensitive_candidates_inspection(inspect_sensitive_candidates(sensitive_path))

    assert "Sensitive passed candidates:" in rendered
    assert "candidate_count: 1" in rendered
    assert "Warning: sensitive candidate credentials are not displayed." in rendered
    assert "vless://" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered


def _make_probe_summary_payload() -> dict[str, object]:
    """Construct one redacted probe summary payload for inspection tests."""
    return {
        "schema_version": 1,
        "total_count": 3,
        "attempted_count": 2,
        "skipped_count": 1,
        "passed_count": 1,
        "failed_count": 1,
        "passed_indices": [0],
        "passed_candidate_ids": ["candidate-001-abc123"],
        "records": [
            {
                "index": 0,
                "candidate_id": "candidate-001-abc123",
                "candidate_name": "node-a",
                "attempted": True,
                "passed": True,
                "skipped": False,
                "skip_reason": None,
                "summary": {
                    "candidate_id": "candidate-001-abc123",
                    "runtime_config_path": "/tmp/runtime-1.json",
                    "local_socks_host": "127.0.0.1",
                    "local_socks_port": 1081,
                    "xray_started": True,
                    "xray_test_passed": True,
                    "startup_ready": True,
                    "result": {
                        "candidate_id": "candidate-001-abc123",
                        "home_status": 200,
                        "query_status": 200,
                        "blocked": False,
                        "timeout": False,
                        "error": None,
                        "failure_markers": [],
                        "latency_ms": 10,
                        "checked_at": "2026-05-25T00:00:00Z",
                    },
                },
            },
            {
                "index": 1,
                "candidate_id": "candidate-002-def456",
                "candidate_name": "node-b",
                "attempted": True,
                "passed": False,
                "skipped": False,
                "skip_reason": None,
                "summary": {
                    "candidate_id": "candidate-002-def456",
                    "runtime_config_path": "/tmp/runtime-2.json",
                    "local_socks_host": "127.0.0.1",
                    "local_socks_port": 1082,
                    "xray_started": True,
                    "xray_test_passed": True,
                    "startup_ready": True,
                    "result": {
                        "candidate_id": "candidate-002-def456",
                        "home_status": 403,
                        "query_status": None,
                        "blocked": True,
                        "timeout": False,
                        "error": None,
                        "failure_markers": ["http_403", "captcha", "http_403"],
                        "latency_ms": 18,
                        "checked_at": "2026-05-25T00:00:00Z",
                    },
                },
            },
            {
                "index": 2,
                "candidate_id": "candidate-003-ghi789",
                "candidate_name": "node-c",
                "attempted": False,
                "passed": False,
                "skipped": True,
                "skip_reason": "Unsupported transport.",
                "summary": None,
            },
        ],
    }


def _make_manifest_payload() -> dict[str, object]:
    """Construct one generated manifest payload for inspection tests."""
    return {
        "schema_version": 1,
        "generated_at": "2026-05-25T00:00:00Z",
        "selected": [
            {
                "tag": "google-scholar-node-001",
                "candidate": {
                    "raw_name": "US Scholar IPv4",
                    "user_id": "<REDACTED>",
                    "public_key": "<REDACTED>",
                    "raw_uri": "<REDACTED>",
                },
                "probe": None,
            }
        ],
        "rejected": [
            {"candidate": {"raw_name": "node-b"}, "reason": "Candidate was not selected."},
            {"candidate": {"raw_name": "node-c"}, "reason": "Unsupported transport."},
        ],
    }


def _make_sensitive_payload() -> dict[str, object]:
    """Construct one sensitive passed-candidate payload for inspection tests."""
    return {
        "schema_version": 1,
        "sensitive": True,
        "description": "This file contains selected proxy credentials and must not be committed.",
        "passed_candidate_ids": ["candidate-001-abc123"],
        "candidates": [
            {
                "raw_name": "US Scholar IPv4",
                "address": "example.invalid",
                "port": 443,
                "user_id": "00000000-0000-0000-0000-000000000000",
                "public_key": "PUBLIC_KEY_PLACEHOLDER",
                "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
            }
        ],
    }
