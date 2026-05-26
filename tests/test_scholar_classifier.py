"""Tests for Scholar semantic response classification."""

from __future__ import annotations

from dataclasses import asdict
import json

from scholar_outbound_manager.probe.http_probe import HttpProbeResponse
from scholar_outbound_manager.probe.scholar_classifier import build_scholar_reference_query_target
from scholar_outbound_manager.probe.scholar_classifier import classify_scholar_access
from scholar_outbound_manager.probe.scholar_classifier import build_scholar_home_target
from scholar_outbound_manager.probe.scholar_classifier import build_scholar_probe_result
from scholar_outbound_manager.probe.scholar_classifier import build_scholar_query_target
from scholar_outbound_manager.probe.scholar_classifier import classify_scholar_response


def test_classify_scholar_response_marks_plain_200_as_accessible(capsys) -> None:
    """Classify a normal 200 page as accessible."""
    classification = classify_scholar_response(
        _make_response(body_prefix="<html><title>Scholar</title></html>")
    )
    captured = capsys.readouterr()

    assert classification.accessible is True
    assert classification.blocked is False
    assert captured.out == ""
    assert captured.err == ""


def test_classify_scholar_response_marks_403_as_blocked() -> None:
    """Classify HTTP 403 as blocked."""
    classification = classify_scholar_response(_make_response(status_code=403))

    assert classification.blocked is True
    assert "http_403" in classification.failure_markers


def test_classify_scholar_response_marks_429_as_blocked() -> None:
    """Classify HTTP 429 as blocked."""
    classification = classify_scholar_response(_make_response(status_code=429))

    assert classification.blocked is True
    assert "http_429" in classification.failure_markers


def test_classify_scholar_response_marks_timeout() -> None:
    """Classify timed-out responses distinctly."""
    classification = classify_scholar_response(_make_response(timed_out=True, elapsed_ms=None))

    assert classification.timeout is True
    assert classification.failure_markers == ["timeout"]


def test_classify_scholar_response_marks_transport_error() -> None:
    """Classify transport errors distinctly."""
    classification = classify_scholar_response(_make_response(error="Connection refused"))

    assert classification.transport_error is True
    assert classification.failure_markers == ["transport_error"]


def test_classify_scholar_response_detects_unusual_traffic() -> None:
    """Detect unusual traffic block pages."""
    classification = classify_scholar_response(
        _make_response(body_prefix="Our systems have detected unusual traffic from your computer network.")
    )

    assert classification.blocked is True
    assert "unusual_traffic" in classification.failure_markers


def test_classify_scholar_response_detects_automated_queries() -> None:
    """Detect automated queries block pages."""
    classification = classify_scholar_response(
        _make_response(body_prefix="This page mentions automated queries explicitly.")
    )

    assert "automated_queries" in classification.failure_markers


def test_classify_scholar_response_detects_google_sorry() -> None:
    """Detect Google sorry pages from body or headers."""
    classification = classify_scholar_response(
        _make_response(headers={"Location": "/sorry/index?continue=1"})
    )

    assert "google_sorry" in classification.failure_markers


def test_classify_scholar_response_detects_captcha() -> None:
    """Detect captcha pages."""
    classification = classify_scholar_response(_make_response(body_prefix="Please solve the CAPTCHA challenge."))

    assert "captcha" in classification.failure_markers


def test_classify_scholar_response_detects_client_no_permission() -> None:
    """Detect permission-denied pages tied to client IP restrictions."""
    classification = classify_scholar_response(
        _make_response(body_prefix="Client IP address does not have permission to access this service.")
    )

    assert "client_no_permission" in classification.failure_markers


def test_classify_scholar_response_detects_unsupported_location() -> None:
    """Detect unsupported-location pages."""
    classification = classify_scholar_response(
        _make_response(url="https://scholar.google.com/?location=unsupported")
    )

    assert "unsupported_location" in classification.failure_markers


def test_classify_scholar_response_detects_geo_unavailable() -> None:
    """Detect regionally unavailable pages."""
    classification = classify_scholar_response(
        _make_response(body_prefix="This service is not available in your country.")
    )

    assert "geo_unavailable" in classification.failure_markers


def test_classify_scholar_response_detects_access_denied() -> None:
    """Detect generic access-denied responses."""
    classification = classify_scholar_response(_make_response(body_prefix="Access denied by policy."))

    assert "access_denied" in classification.failure_markers


def test_classify_scholar_response_marks_200_with_block_marker_as_blocked() -> None:
    """Treat 200 responses with block markers as blocked pages."""
    classification = classify_scholar_response(
        _make_response(status_code=200, body_prefix="captcha required before continuing")
    )

    assert classification.accessible is False
    assert classification.blocked is True


def test_classify_scholar_response_deduplicates_failure_markers() -> None:
    """Deduplicate repeated semantic markers while preserving order."""
    classification = classify_scholar_response(
        _make_response(body_prefix="captcha captcha unusual traffic unusual traffic")
    )

    assert classification.failure_markers == ["unusual_traffic", "captcha"]


def test_classify_scholar_response_truncates_evidence_entries() -> None:
    """Keep evidence strings short and reviewable."""
    classification = classify_scholar_response(
        _make_response(body_prefix="x" * 400 + " forbidden")
    )

    assert all(len(item) <= 160 for item in classification.evidence)


def test_build_scholar_probe_result_merges_markers() -> None:
    """Merge home and query semantic markers into one ProbeResult."""
    result = build_scholar_probe_result(
        candidate_id="candidate-1",
        home_response=_make_response(status_code=403),
        query_response=_make_response(body_prefix="captcha"),
        checked_at="2026-05-25T00:00:00Z",
    )

    assert result.failure_markers == ["http_403", "captcha", "stage_home_blocked"]
    assert result.blocked is True


def test_build_scholar_probe_result_combines_latency() -> None:
    """Combine home and query latency values."""
    result = build_scholar_probe_result(
        candidate_id="candidate-1",
        home_response=_make_response(elapsed_ms=10),
        query_response=_make_response(elapsed_ms=25),
        checked_at="2026-05-25T00:00:00Z",
    )

    assert result.latency_ms == 35


def test_build_scholar_probe_result_handles_missing_query_response() -> None:
    """Build a ProbeResult when only the home response is available."""
    result = build_scholar_probe_result(
        candidate_id="candidate-1",
        home_response=_make_response(status_code=200),
        query_response=None,
        checked_at="2026-05-25T00:00:00Z",
    )

    assert result.query_status is None
    assert result.home_status == 200


def test_classify_scholar_access_marks_home_blocked() -> None:
    """Classify home-page blocking distinctly from query-page blocking."""
    decision = classify_scholar_access(
        _make_response(status_code=403),
        _make_response(status_code=200),
    )

    assert decision.stage == "home_blocked"
    assert decision.passed is False


def test_classify_scholar_access_marks_query_blocked() -> None:
    """Classify query-page blocking distinctly when home remains accessible."""
    decision = classify_scholar_access(
        _make_response(status_code=200),
        _make_response(status_code=403),
    )

    assert decision.stage == "query_blocked"
    assert decision.passed is False


def test_classify_scholar_access_marks_full_access() -> None:
    """Require both home and query to pass for full access."""
    decision = classify_scholar_access(
        _make_response(status_code=200),
        _make_response(status_code=200),
    )

    assert decision.stage == "full_access"
    assert decision.passed is True


def test_classify_scholar_access_marks_query_blocked_on_unusual_traffic() -> None:
    """Treat a query-stage block page as query_blocked even with a 200 status."""
    decision = classify_scholar_access(
        _make_response(status_code=200),
        _make_response(status_code=200, body_prefix="Our systems have detected unusual traffic."),
    )

    assert decision.stage == "query_blocked"
    assert decision.passed is False


def test_classify_scholar_access_marks_timeout_from_home() -> None:
    """Promote home-stage timeout into a timeout decision."""
    decision = classify_scholar_access(
        _make_response(status_code=None, timed_out=True, elapsed_ms=None),
        _make_response(status_code=200),
    )

    assert decision.stage == "timeout"
    assert decision.timeout is True


def test_classify_scholar_access_marks_timeout_from_query() -> None:
    """Promote query-stage timeout into a timeout decision."""
    decision = classify_scholar_access(
        _make_response(status_code=200),
        _make_response(status_code=None, timed_out=True, elapsed_ms=None),
    )

    assert decision.stage == "timeout"
    assert decision.timeout is True


def test_classify_scholar_access_marks_transport_failed() -> None:
    """Promote transport errors into a transport_failed decision."""
    decision = classify_scholar_access(
        _make_response(status_code=None, error="Connection refused"),
        _make_response(status_code=200),
    )

    assert decision.stage == "transport_failed"
    assert decision.transport_error is True


def test_classify_scholar_access_requires_query_response_for_full_access() -> None:
    """Do not treat a missing query response as full access."""
    decision = classify_scholar_access(
        _make_response(status_code=200),
        None,
    )

    assert decision.stage == "unknown"
    assert decision.passed is False


def test_classify_scholar_access_evidence_is_short_and_secret_free() -> None:
    """Keep two-stage decision evidence review-safe."""
    decision = classify_scholar_access(
        _make_response(status_code=200),
        _make_response(status_code=200, body_prefix="captcha " + ("x" * 400)),
    )

    rendered = json.dumps(decision.evidence)
    assert all(len(item) <= 160 for item in decision.evidence)
    assert "vless://" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered


def test_build_scholar_probe_result_generates_checked_at_with_z_suffix() -> None:
    """Generate a UTC timestamp when checked_at is omitted."""
    result = build_scholar_probe_result(
        candidate_id="candidate-1",
        home_response=_make_response(status_code=200),
        query_response=None,
    )

    assert result.checked_at.endswith("Z")


def test_build_scholar_home_target_uses_expected_url() -> None:
    """Build the canonical Scholar home target URL."""
    target = build_scholar_home_target()

    assert target.url == "https://scholar.google.com/"


def test_build_scholar_query_target_url_encodes_query() -> None:
    """Encode query terms in the canonical Scholar query target URL."""
    target = build_scholar_query_target("deep learning")

    assert target.url == "https://scholar.google.com/scholar?hl=zh-CN&as_sdt=0%2C5&q=deep+learning&btnG="


def test_build_scholar_reference_query_target_uses_expected_reference_url() -> None:
    """Build the canonical reference query target for two-stage access checks."""
    target = build_scholar_reference_query_target()

    assert "/scholar?hl=zh-CN" in target.url
    assert "q=ppr" in target.url


def test_target_builders_are_pure_configuration_helpers() -> None:
    """Keep target builders free of side effects and network calls."""
    home_target = build_scholar_home_target()
    query_target = build_scholar_query_target("test")

    assert home_target.user_agent.startswith("Mozilla/5.0")
    assert query_target.user_agent.startswith("Mozilla/5.0")


def test_classifier_outputs_do_not_include_raw_uri_field() -> None:
    """Keep raw URI material out of classifier outputs."""
    classification = classify_scholar_response(_make_response())

    assert "raw_uri" not in type(classification).__annotations__
    assert "raw_uri" not in json.dumps(asdict(classification))


def _make_response(
    status_code: int | None = 200,
    body_prefix: str = "",
    headers: dict[str, str] | None = None,
    error: str | None = None,
    timed_out: bool = False,
    elapsed_ms: int | None = 10,
    url: str = "https://scholar.google.com/",
) -> HttpProbeResponse:
    """Build one HTTP probe response for pure semantic tests."""
    return HttpProbeResponse(
        url=url,
        status_code=status_code,
        reason="OK" if status_code == 200 else None,
        headers={} if headers is None else headers,
        body_prefix=body_prefix,
        elapsed_ms=elapsed_ms,
        timed_out=timed_out,
        error=error,
    )
