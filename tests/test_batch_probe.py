"""Tests for sequential batch probe orchestration."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import ProbeResult
from scholar_outbound_manager.models import XrayConfig
from scholar_outbound_manager.probe.batch_probe import BatchProbeOptions
from scholar_outbound_manager.probe.batch_probe import BatchProbeSummary
from scholar_outbound_manager.probe.batch_probe import build_candidate_id
from scholar_outbound_manager.probe.batch_probe import is_probe_passed
from scholar_outbound_manager.probe.batch_probe import probe_candidates_sequential
from scholar_outbound_manager.probe.batch_probe import select_passed_candidates
from scholar_outbound_manager.probe.candidate_probe import CandidateProbeOptions
from scholar_outbound_manager.probe.candidate_probe import CandidateProbeSummary


def test_build_candidate_id_is_stable() -> None:
    """Build stable candidate IDs for the same candidate and index."""
    candidate = _make_candidate()

    first = build_candidate_id(candidate, 0)
    second = build_candidate_id(candidate, 0)

    assert first == second


def test_build_candidate_id_excludes_sensitive_material() -> None:
    """Keep source values and secrets out of the generated candidate ID."""
    candidate = _make_candidate()

    candidate_id = build_candidate_id(candidate, 0)

    assert candidate.raw_name not in candidate_id
    assert candidate.address not in candidate_id
    assert "00000000-0000-0000-0000-000000000000" not in candidate_id
    assert "PUBLIC_KEY_PLACEHOLDER" not in candidate_id
    assert "vless://" not in candidate_id


def test_is_probe_passed_accepts_clean_success() -> None:
    """Accept only clean successful results."""
    assert is_probe_passed(_make_probe_result())


def test_is_probe_passed_rejects_blocked() -> None:
    """Reject blocked results."""
    assert is_probe_passed(_make_probe_result(blocked=True)) is False


def test_is_probe_passed_rejects_timeout() -> None:
    """Reject timed-out results."""
    assert is_probe_passed(_make_probe_result(timeout=True)) is False


def test_is_probe_passed_rejects_error() -> None:
    """Reject results with transport or runtime errors."""
    assert is_probe_passed(_make_probe_result(error="boom")) is False


def test_is_probe_passed_rejects_bad_home_status() -> None:
    """Reject disallowed home status codes."""
    assert is_probe_passed(_make_probe_result(home_status=403)) is False


def test_is_probe_passed_rejects_bad_query_status() -> None:
    """Reject disallowed query status codes."""
    assert is_probe_passed(_make_probe_result(query_status=403)) is False


def test_is_probe_passed_rejects_missing_query_status() -> None:
    """Reject results that did not complete the query-stage check."""
    assert is_probe_passed(_make_probe_result(query_status=None)) is False


def test_is_probe_passed_rejects_failure_markers() -> None:
    """Reject results with failure markers."""
    assert is_probe_passed(_make_probe_result(failure_markers=["captcha"])) is False


def test_is_probe_passed_rejects_stage_query_blocked_marker() -> None:
    """Reject explicit query-blocked stage markers."""
    assert is_probe_passed(_make_probe_result(failure_markers=["stage_query_blocked"])) is False


def test_is_probe_passed_rejects_stage_home_blocked_marker() -> None:
    """Reject explicit home-blocked stage markers."""
    assert is_probe_passed(_make_probe_result(failure_markers=["stage_home_blocked"])) is False


def test_probe_candidates_sequential_probes_multiple_candidates(capsys) -> None:
    """Probe multiple candidates in order."""
    candidates = [_make_candidate(raw_name="a"), _make_candidate(raw_name="b")]
    summary = probe_candidates_sequential(
        candidates=candidates,
        xray_config=_make_xray_config(),
        probe_candidate_func=_fake_probe_factory(
            [
                _make_summary("candidate-001-a", home_status=200, query_status=200),
                _make_summary("candidate-002-b", home_status=403, query_status=403, blocked=True, failure_markers=["http_403"]),
            ]
        ),
    )
    captured = capsys.readouterr()

    assert summary.attempted_count == 2
    assert summary.records[0].attempted is True
    assert captured.out == ""
    assert captured.err == ""


def test_probe_candidates_sequential_records_passed_indices_and_ids() -> None:
    """Record passed indices and candidate IDs in stable order."""
    candidates = [_make_candidate(raw_name="a"), _make_candidate(raw_name="b")]

    summary = probe_candidates_sequential(
        candidates=candidates,
        xray_config=_make_xray_config(),
        probe_candidate_func=_fake_probe_factory(
            [
                _make_summary("candidate-001-a"),
                _make_summary("candidate-002-b", blocked=True, home_status=403, query_status=403, failure_markers=["http_403"]),
            ]
        ),
    )

    assert summary.passed_indices == [0]
    assert summary.passed_candidate_ids == [build_candidate_id(candidates[0], 0)]


def test_probe_candidates_sequential_respects_max_candidates() -> None:
    """Stop processing after the configured candidate limit."""
    candidates = [_make_candidate(raw_name="a"), _make_candidate(raw_name="b"), _make_candidate(raw_name="c")]

    summary = probe_candidates_sequential(
        candidates=candidates,
        xray_config=_make_xray_config(),
        options=BatchProbeOptions(max_candidates=2),
        probe_candidate_func=_fake_probe_factory(
            [
                _make_summary("candidate-001-a"),
                _make_summary("candidate-002-b"),
                _make_summary("candidate-003-c"),
            ]
        ),
    )

    assert len(summary.records) == 2
    assert summary.attempted_count == 2


def test_probe_candidates_sequential_stops_after_max_passed_when_requested() -> None:
    """Stop early when enough passed candidates have been retained."""
    candidates = [_make_candidate(raw_name="a"), _make_candidate(raw_name="b"), _make_candidate(raw_name="c")]

    summary = probe_candidates_sequential(
        candidates=candidates,
        xray_config=_make_xray_config(),
        options=BatchProbeOptions(max_passed=1, stop_after_max_passed=True),
        probe_candidate_func=_fake_probe_factory(
            [
                _make_summary("candidate-001-a"),
                _make_summary("candidate-002-b"),
                _make_summary("candidate-003-c"),
            ]
        ),
    )

    assert len(summary.records) == 1
    assert summary.passed_count == 1


def test_probe_candidates_sequential_can_continue_after_max_passed() -> None:
    """Continue probing after reaching max_passed when configured to do so."""
    candidates = [_make_candidate(raw_name="a"), _make_candidate(raw_name="b"), _make_candidate(raw_name="c")]

    summary = probe_candidates_sequential(
        candidates=candidates,
        xray_config=_make_xray_config(),
        options=BatchProbeOptions(max_passed=1, stop_after_max_passed=False),
        probe_candidate_func=_fake_probe_factory(
            [
                _make_summary("candidate-001-a"),
                _make_summary("candidate-002-b"),
                _make_summary("candidate-003-c"),
            ]
        ),
    )

    assert len(summary.records) == 3
    assert summary.passed_count == 1
    assert summary.failed_count == 2


def test_probe_candidates_sequential_skips_unsupported_candidates_by_default() -> None:
    """Skip unsupported candidates without calling the single-candidate probe."""
    candidates = [_make_candidate(supported=False, unsupported_reason="Unsupported transport.")]
    call_count = {"value": 0}

    def fake_probe(candidate, xray_config, candidate_id, candidate_options):
        del candidate, xray_config, candidate_id, candidate_options
        call_count["value"] += 1
        return _make_summary("unused")

    summary = probe_candidates_sequential(
        candidates=candidates,
        xray_config=_make_xray_config(),
        probe_candidate_func=fake_probe,
    )

    assert call_count["value"] == 0
    assert summary.records[0].skipped is True


def test_probe_candidates_sequential_can_include_unsupported_candidates() -> None:
    """Allow unsupported candidates through to the single-candidate probe when requested."""
    candidates = [_make_candidate(supported=False, unsupported_reason="Unsupported transport.")]
    call_count = {"value": 0}

    def fake_probe(candidate, xray_config, candidate_id, candidate_options):
        del candidate, xray_config, candidate_id, candidate_options
        call_count["value"] += 1
        return _make_summary("candidate-001-a", blocked=True, home_status=403, query_status=403, failure_markers=["runtime_prepare_failed"])

    summary = probe_candidates_sequential(
        candidates=candidates,
        xray_config=_make_xray_config(),
        options=BatchProbeOptions(include_unsupported=True),
        probe_candidate_func=fake_probe,
    )

    assert call_count["value"] == 1
    assert summary.records[0].attempted is True


def test_probe_candidates_sequential_wraps_probe_exceptions() -> None:
    """Convert single-candidate probe exceptions into structured batch failures."""
    candidates = [_make_candidate()]

    summary = probe_candidates_sequential(
        candidates=candidates,
        xray_config=_make_xray_config(),
        probe_candidate_func=lambda candidate, xray_config, candidate_id, candidate_options: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert summary.records[0].summary is not None
    assert summary.records[0].summary.result.failure_markers == ["batch_probe_exception"]


def test_probe_candidates_sequential_counts_attempted_skipped_passed_and_failed() -> None:
    """Track batch counters correctly."""
    candidates = [
        _make_candidate(raw_name="a"),
        _make_candidate(raw_name="b", supported=False, unsupported_reason="Unsupported transport."),
        _make_candidate(raw_name="c"),
    ]
    summary = probe_candidates_sequential(
        candidates=candidates,
        xray_config=_make_xray_config(),
        probe_candidate_func=_fake_probe_factory(
            [
                _make_summary("candidate-001-a"),
                _make_summary("candidate-003-c", blocked=True, home_status=403, query_status=403, failure_markers=["http_403"]),
            ]
        ),
    )

    assert summary.attempted_count == 2
    assert summary.skipped_count == 1
    assert summary.passed_count == 1
    assert summary.failed_count == 1


def test_select_passed_candidates_returns_original_candidates() -> None:
    """Return the original candidates referenced by passed indices."""
    candidates = [_make_candidate(raw_name="a"), _make_candidate(raw_name="b")]
    summary = BatchProbeSummary(
        total_count=2,
        attempted_count=1,
        skipped_count=0,
        passed_count=1,
        failed_count=0,
        records=[],
        passed_indices=[1],
        passed_candidate_ids=["candidate-002-b"],
    )

    selected = select_passed_candidates(candidates, summary)

    assert selected == [candidates[1]]


def test_select_passed_candidates_rejects_out_of_range_index() -> None:
    """Reject invalid passed indices."""
    with pytest.raises(ValueError, match="out of range"):
        select_passed_candidates(
            [_make_candidate()],
            BatchProbeSummary(
                total_count=1,
                attempted_count=0,
                skipped_count=0,
                passed_count=0,
                failed_count=0,
                records=[],
                passed_indices=[1],
                passed_candidate_ids=[],
            ),
        )


def test_batch_probe_summary_excludes_sensitive_values() -> None:
    """Keep sensitive candidate values out of batch summaries."""
    candidates = [_make_candidate()]
    summary = probe_candidates_sequential(
        candidates=candidates,
        xray_config=_make_xray_config(),
        probe_candidate_func=_fake_probe_factory([_make_summary("candidate-001-a")]),
    )

    rendered = str(asdict(summary))
    assert "raw_uri" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered


def test_probe_candidates_sequential_rejects_invalid_max_candidates() -> None:
    """Reject invalid max_candidates values."""
    with pytest.raises(ValueError, match="max_candidates"):
        probe_candidates_sequential(
            candidates=[],
            xray_config=_make_xray_config(),
            options=BatchProbeOptions(max_candidates=0),
        )


def test_probe_candidates_sequential_rejects_invalid_max_passed() -> None:
    """Reject invalid max_passed values."""
    with pytest.raises(ValueError, match="max_passed"):
        probe_candidates_sequential(
            candidates=[],
            xray_config=_make_xray_config(),
            options=BatchProbeOptions(max_passed=0),
        )


def test_probe_candidates_sequential_handles_empty_candidates() -> None:
    """Return an empty summary for empty candidate lists."""
    summary = probe_candidates_sequential([], _make_xray_config())

    assert summary.total_count == 0
    assert summary.records == []
    assert summary.attempted_count == 0
    assert summary.skipped_count == 0
    assert summary.passed_count == 0
    assert summary.failed_count == 0


def test_probe_candidates_sequential_uses_fallback_candidate_name() -> None:
    """Fallback to a generated candidate name when raw_name is empty."""
    candidates = [_make_candidate(raw_name="")]
    summary = probe_candidates_sequential(
        candidates=candidates,
        xray_config=_make_xray_config(),
        probe_candidate_func=_fake_probe_factory([_make_summary("candidate-001-a")]),
    )

    assert summary.records[0].candidate_name == "candidate-001"


def test_failed_count_excludes_skipped_records() -> None:
    """Do not count skipped records as failed."""
    candidates = [_make_candidate(supported=False)]
    summary = probe_candidates_sequential(candidates, _make_xray_config())

    assert summary.failed_count == 0


def test_failed_count_includes_attempted_non_passed_records() -> None:
    """Count attempted but non-passed records as failures."""
    candidates = [_make_candidate()]
    summary = probe_candidates_sequential(
        candidates=candidates,
        xray_config=_make_xray_config(),
        probe_candidate_func=_fake_probe_factory(
            [_make_summary("candidate-001-a", blocked=True, home_status=403, query_status=403, failure_markers=["http_403"])]
        ),
    )

    assert summary.failed_count == 1


def _make_candidate(**overrides: object) -> CandidateProxy:
    """Construct one placeholder candidate for batch probe tests."""
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


def _make_probe_result(
    *,
    blocked: bool = False,
    timeout: bool = False,
    error: str | None = None,
    home_status: int | None = 200,
    query_status: int | None = 200,
    failure_markers: list[str] | None = None,
) -> ProbeResult:
    """Construct one ProbeResult for batch probe tests."""
    return ProbeResult(
        candidate_id="candidate-001-a",
        home_status=home_status,
        query_status=query_status,
        blocked=blocked,
        timeout=timeout,
        error=error,
        failure_markers=[] if failure_markers is None else failure_markers,
        latency_ms=10,
        checked_at="2026-05-25T00:00:00Z",
    )


def _make_summary(
    candidate_id: str,
    *,
    blocked: bool = False,
    timeout: bool = False,
    error: str | None = None,
    home_status: int | None = 200,
    query_status: int | None = 200,
    failure_markers: list[str] | None = None,
) -> CandidateProbeSummary:
    """Construct one CandidateProbeSummary for batch probe tests."""
    return CandidateProbeSummary(
        candidate_id=candidate_id,
        runtime_config_path="/tmp/candidate_runtime.json",
        local_socks_host="127.0.0.1",
        local_socks_port=1081,
        xray_started=True,
        xray_test_passed=None,
        startup_ready=True,
        result=_make_probe_result(
            blocked=blocked,
            timeout=timeout,
            error=error,
            home_status=home_status,
            query_status=query_status,
            failure_markers=failure_markers,
        ),
    )


def _fake_probe_factory(summaries: list[CandidateProbeSummary]):
    """Build one sequential fake probe_candidate function."""
    state = {"index": 0}

    def fake_probe(candidate, xray_config, candidate_id, candidate_options):
        del candidate, xray_config, candidate_id, candidate_options
        summary = summaries[state["index"]]
        state["index"] += 1
        return summary

    return fake_probe


def _make_xray_config() -> XrayConfig:
    """Construct one placeholder Xray config for batch probe tests."""
    return XrayConfig(
        binary_path="fake-xray",
        runtime_dir="/tmp/runtime",
        local_socks_host="127.0.0.1",
        local_socks_port=1081,
    )
