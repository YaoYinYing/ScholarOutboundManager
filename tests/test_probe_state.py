"""Tests for probe state serialization and persistence helpers."""

from __future__ import annotations

import json
from dataclasses import asdict

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import ProbeResult
from scholar_outbound_manager.probe.batch_probe import BatchProbeRecord
from scholar_outbound_manager.probe.batch_probe import BatchProbeSummary
from scholar_outbound_manager.probe.candidate_probe import CandidateProbeSummary
from scholar_outbound_manager.state.probe_state import build_passed_candidates_payload
from scholar_outbound_manager.state.probe_state import serialize_batch_probe_record
from scholar_outbound_manager.state.probe_state import serialize_batch_probe_summary
from scholar_outbound_manager.state.probe_state import serialize_candidate_probe_summary
from scholar_outbound_manager.state.probe_state import serialize_probe_result
from scholar_outbound_manager.state.probe_state import write_batch_probe_summary
from scholar_outbound_manager.state.probe_state import write_passed_candidates
from scholar_outbound_manager.state.probe_state import write_probe_artifacts


def test_serialize_probe_result_keeps_core_fields(capsys) -> None:
    """Serialize core ProbeResult fields without side effects."""
    serialized = serialize_probe_result(_make_probe_result())
    captured = capsys.readouterr()

    assert serialized["candidate_id"] == "candidate-001"
    assert serialized["home_status"] == 200
    assert serialized["checked_at"] == "2026-05-25T00:00:00Z"
    assert captured.out == ""
    assert captured.err == ""


def test_serialize_candidate_probe_summary_includes_result() -> None:
    """Serialize nested CandidateProbeSummary results."""
    serialized = serialize_candidate_probe_summary(_make_candidate_probe_summary())

    assert serialized["result"]["candidate_id"] == "candidate-001"


def test_serialize_batch_probe_record_supports_missing_summary() -> None:
    """Serialize records whose summary is absent."""
    serialized = serialize_batch_probe_record(
        BatchProbeRecord(
            index=0,
            candidate_id="candidate-001",
            candidate_name="node-name",
            attempted=False,
            passed=False,
            skipped=True,
            skip_reason="Unsupported transport.",
            summary=None,
        )
    )

    assert serialized["summary"] is None


def test_serialize_batch_probe_summary_includes_schema_version_and_records() -> None:
    """Serialize batch summaries with the expected top-level structure."""
    serialized = serialize_batch_probe_summary(_make_batch_probe_summary())

    assert serialized["schema_version"] == 1
    assert serialized["artifact_type"] == "probe_summary"
    assert isinstance(serialized["run_id"], str)
    assert isinstance(serialized["created_at"], str)
    assert serialized["parallel_workers"] == 1
    assert serialized["keep_all_passed"] is False
    assert serialized["retained_passed_count"] == 1
    assert serialized["truncated"] is False
    assert len(serialized["records"]) == 2


def test_redacted_summary_excludes_sensitive_proxy_material() -> None:
    """Keep redacted summaries free of raw proxy credentials."""
    rendered = json.dumps(serialize_batch_probe_summary(_make_batch_probe_summary()))

    assert "raw_uri" not in rendered
    assert "vless://" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered


def test_candidate_name_and_skip_reason_are_redacted() -> None:
    """Redact user-readable record text fields."""
    summary = _make_batch_probe_summary(
        records=[
            BatchProbeRecord(
                index=0,
                candidate_id="candidate-001",
                candidate_name="https://example.invalid/token=secret",
                attempted=False,
                passed=False,
                skipped=True,
                skip_reason="uuid 00000000-0000-0000-0000-000000000000",
                summary=None,
            )
        ]
    )

    serialized = serialize_batch_probe_summary(summary)
    rendered = json.dumps(serialized)
    assert "https://example.invalid/token=secret" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered


def test_write_batch_probe_summary_persists_json(tmp_path) -> None:
    """Write a redacted batch probe summary to disk."""
    path = tmp_path / "state" / "summary.json"

    write_batch_probe_summary(path, _make_batch_probe_summary())

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == 1


def test_build_passed_candidates_payload_marks_sensitive_and_keeps_credentials() -> None:
    """Build the sensitive passed-candidate payload used for later generation."""
    candidates = [_make_candidate(raw_name="a"), _make_candidate(raw_name="b")]
    payload = build_passed_candidates_payload(candidates, _make_batch_probe_summary())

    assert payload["sensitive"] is True
    assert payload["artifact_type"] == "passed_candidates"
    assert "must not be committed" in payload["description"]
    assert payload["passed_count"] == 1
    assert payload["retained_passed_count"] == 1
    assert payload["truncated"] is False
    assert payload["candidates"][0]["candidate"]["user_id"] == "00000000-0000-0000-0000-000000000000"
    assert payload["candidates"][0]["candidate"]["public_key"] == "PUBLIC_KEY_PLACEHOLDER"
    assert payload["candidates"][0]["probe"]["home_status"] == 200
    assert len(payload["candidates"]) == 1


def test_write_passed_candidates_persists_json(tmp_path) -> None:
    """Write the sensitive passed-candidate payload to disk."""
    path = tmp_path / "state" / "passed.json"
    candidates = [_make_candidate(raw_name="a"), _make_candidate(raw_name="b")]

    write_passed_candidates(path, candidates, _make_batch_probe_summary())

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["sensitive"] is True


def test_write_probe_artifacts_writes_both_files_and_returns_counts(tmp_path) -> None:
    """Write both probe artifacts and return their summary counts."""
    candidates = [_make_candidate(raw_name="a"), _make_candidate(raw_name="b")]
    summary = _make_batch_probe_summary()

    result = write_probe_artifacts(
        summary_path=tmp_path / "artifacts" / "summary.json",
        passed_candidates_path=tmp_path / "artifacts" / "passed.json",
        candidates=candidates,
        summary=summary,
    )

    assert (tmp_path / "artifacts" / "summary.json").exists()
    assert (tmp_path / "artifacts" / "passed.json").exists()
    assert result["passed_count"] == summary.passed_count
    assert result["retained_passed_count"] == summary.retained_passed_count
    assert result["truncated"] == summary.truncated
    assert result["attempted_count"] == summary.attempted_count
    summary_payload = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    passed_payload = json.loads((tmp_path / "artifacts" / "passed.json").read_text(encoding="utf-8"))
    assert summary_payload["source_candidates_hash"] is None
    assert passed_payload["source_probe_summary_hash"]


def test_write_passed_candidates_rejects_out_of_range_indices(tmp_path) -> None:
    """Raise when passed indices do not match the candidate list."""
    summary = _make_batch_probe_summary(passed_indices=[3], passed_candidate_ids=["candidate-004"])
    try:
        write_passed_candidates(tmp_path / "passed.json", [_make_candidate()], summary)
    except ValueError as exc:
        assert "out of range" in str(exc)
    else:
        raise AssertionError("Expected ValueError for out-of-range passed index.")


def test_original_candidates_are_not_modified() -> None:
    """Leave the original candidate objects unchanged."""
    candidates = [_make_candidate(raw_name="a"), _make_candidate(raw_name="b")]
    before = [candidate.to_dict() for candidate in candidates]

    build_passed_candidates_payload(candidates, _make_batch_probe_summary())

    assert [candidate.to_dict() for candidate in candidates] == before


def test_empty_passed_indices_produce_empty_sensitive_candidates_payload() -> None:
    """Return an empty candidate list when nothing passed."""
    payload = build_passed_candidates_payload(
        [_make_candidate()],
        _make_batch_probe_summary(passed_indices=[], passed_candidate_ids=[], passed_count=0),
    )

    assert payload["candidates"] == []


def test_passed_candidates_payload_tracks_truncated_retention() -> None:
    """Preserve actual and retained pass counts when the artifact is truncated."""
    payload = build_passed_candidates_payload(
        [_make_candidate(raw_name="a"), _make_candidate(raw_name="b")],
        _make_batch_probe_summary(
            passed_indices=[0],
            passed_candidate_ids=["candidate-001"],
            passed_count=2,
            retained_passed_count=1,
            truncated=True,
        ),
    )

    assert payload["passed_count"] == 2
    assert payload["retained_passed_count"] == 1
    assert payload["truncated"] is True
    assert len(payload["candidates"]) == 1


def test_passed_candidates_payload_keeps_probe_result_for_selected_candidate() -> None:
    """Preserve probe evidence alongside each passed candidate."""
    payload = build_passed_candidates_payload(
        [_make_candidate(raw_name="a"), _make_candidate(raw_name="b")],
        _make_batch_probe_summary(),
    )

    assert payload["candidates"][0]["probe"]["candidate_id"] == "candidate-001"
    assert payload["candidates"][0]["probe"]["checked_at"] == "2026-05-25T00:00:00Z"


def test_redacted_summary_does_not_expose_secret_like_terms_verbatim() -> None:
    """Redact obvious secret-like free-text content in review-safe summaries."""
    summary = _make_batch_probe_summary(
        records=[
            BatchProbeRecord(
                index=0,
                candidate_id="candidate-001",
                candidate_name="token secret password value",
                attempted=False,
                passed=False,
                skipped=True,
                skip_reason="public_key and raw_uri and uuid",
                summary=None,
            )
        ]
    )

    rendered = json.dumps(serialize_batch_probe_summary(summary))
    assert "token secret password value" not in rendered
    assert "public_key and raw_uri and uuid" not in rendered


def _make_candidate(**overrides: object) -> CandidateProxy:
    """Construct one placeholder candidate for probe state tests."""
    candidate_data: dict[str, object] = {
        "source_name": "fixture-source",
        "raw_name": "US Scholar IPv4",
        "protocol": "vless",
        "address": "example.invalid",
        "port": 443,
        "user_id": "00000000-0000-0000-0000-000000000000",
        "encryption": "none",
        "flow": "xtls-rprx-vision",
        "network": "tcp",
        "security": "reality",
        "server_name": "www.cloudflare.com",
        "fingerprint": "chrome",
        "public_key": "PUBLIC_KEY_PLACEHOLDER",
        "short_id": "SHORT_ID_PLACEHOLDER",
        "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
        "supported": True,
        "unsupported_reason": None,
    }
    candidate_data.update(overrides)
    return CandidateProxy(**candidate_data)


def _make_probe_result() -> ProbeResult:
    """Construct one ProbeResult for probe state tests."""
    return ProbeResult(
        candidate_id="candidate-001",
        home_status=200,
        query_status=200,
        blocked=False,
        timeout=False,
        error=None,
        failure_markers=[],
        latency_ms=20,
        checked_at="2026-05-25T00:00:00Z",
    )


def _make_candidate_probe_summary() -> CandidateProbeSummary:
    """Construct one CandidateProbeSummary for probe state tests."""
    return CandidateProbeSummary(
        candidate_id="candidate-001",
        runtime_config_path="/tmp/runtime.json",
        local_socks_host="127.0.0.1",
        local_socks_port=1081,
        xray_started=True,
        xray_test_passed=True,
        startup_ready=True,
        result=_make_probe_result(),
    )


def _make_batch_probe_summary(
    *,
    records: list[BatchProbeRecord] | None = None,
    passed_indices: list[int] | None = None,
    passed_candidate_ids: list[str] | None = None,
    passed_count: int | None = None,
    retained_passed_count: int | None = None,
    truncated: bool = False,
) -> BatchProbeSummary:
    """Construct one BatchProbeSummary for probe state tests."""
    built_records = records if records is not None else [
        BatchProbeRecord(
            index=0,
            candidate_id="candidate-001",
            candidate_name="node-a",
            attempted=True,
            passed=True,
            skipped=False,
            skip_reason=None,
            summary=_make_candidate_probe_summary(),
        ),
        BatchProbeRecord(
            index=1,
            candidate_id="candidate-002",
            candidate_name="node-b",
            attempted=False,
            passed=False,
            skipped=True,
            skip_reason="Unsupported transport.",
            summary=None,
        ),
    ]
    actual_passed_indices = [0] if passed_indices is None else passed_indices
    actual_passed_candidate_ids = ["candidate-001"] if passed_candidate_ids is None else passed_candidate_ids
    actual_passed_count = len(actual_passed_indices) if passed_count is None else passed_count
    retained_count = len(actual_passed_indices) if retained_passed_count is None else retained_passed_count
    return BatchProbeSummary(
        total_count=2,
        attempted_count=1,
        skipped_count=1,
        passed_count=actual_passed_count,
        failed_count=0,
        parallel_workers=1,
        keep_all_passed=False,
        stop_after_max_passed=True,
        retained_passed_count=retained_count,
        truncated=truncated,
        records=built_records,
        passed_indices=actual_passed_indices,
        passed_candidate_ids=actual_passed_candidate_ids,
    )
