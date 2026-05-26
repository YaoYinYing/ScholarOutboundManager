"""Semantic classification helpers for Scholar HTTP probe responses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from urllib.parse import quote_plus

from scholar_outbound_manager.models import ProbeResult
from scholar_outbound_manager.probe.http_probe import HttpProbeResponse
from scholar_outbound_manager.probe.http_probe import HttpProbeTarget


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
)

SCHOLAR_STAGE_FULL_ACCESS = "full_access"
SCHOLAR_STAGE_HOME_BLOCKED = "home_blocked"
SCHOLAR_STAGE_QUERY_BLOCKED = "query_blocked"
SCHOLAR_STAGE_TIMEOUT = "timeout"
SCHOLAR_STAGE_TRANSPORT_FAILED = "transport_failed"
SCHOLAR_STAGE_SERVER_ERROR = "server_error"
SCHOLAR_STAGE_UNKNOWN = "unknown"

_BLOCK_MARKER_RULES: list[tuple[str, str, str]] = [
    ("unusual traffic", "unusual_traffic", "Body or headers mention unusual traffic."),
    ("automated queries", "automated_queries", "Body or headers mention automated queries."),
    ("our systems have detected", "unusual_traffic", "Body or headers mention systems detected unusual activity."),
    ("/sorry/", "google_sorry", "Body, headers, or URL reference a Google sorry page."),
    ("sorry/index", "google_sorry", "Body, headers, or URL reference a Google sorry page."),
    ("captcha", "captcha", "Body or headers mention captcha."),
    ("not have permission", "client_no_permission", "Body or headers mention missing permission."),
    ("client ip address", "client_no_permission", "Body or headers mention the client IP address."),
    ("location=unsupported", "unsupported_location", "Body, headers, or URL indicate an unsupported location."),
    ("not available in your country", "geo_unavailable", "Body or headers indicate country unavailability."),
    ("not available in your region", "geo_unavailable", "Body or headers indicate regional unavailability."),
    ("service is not available", "geo_unavailable", "Body or headers indicate service unavailability."),
    ("access denied", "access_denied", "Body or headers mention access denied."),
    ("forbidden", "access_denied", "Body or headers mention forbidden access."),
]


@dataclass(slots=True)
class ScholarClassification:
    """Represent the semantic classification of a Scholar probe response."""

    accessible: bool
    blocked: bool
    timeout: bool
    transport_error: bool
    status_code: int | None
    failure_markers: list[str]
    evidence: list[str]


@dataclass(slots=True)
class ScholarAccessDecision:
    """Represent a two-stage Scholar accessibility decision."""

    stage: str
    passed: bool
    home_status: int | None
    query_status: int | None
    blocked: bool
    timeout: bool
    transport_error: bool
    failure_markers: list[str]
    evidence: list[str]


def classify_scholar_response(response: HttpProbeResponse) -> ScholarClassification:
    """Classify one transport-level HTTP probe response into Scholar semantics."""
    if response.timed_out:
        return ScholarClassification(
            accessible=False,
            blocked=False,
            timeout=True,
            transport_error=False,
            status_code=response.status_code,
            failure_markers=["timeout"],
            evidence=["Response timed out before a complete Scholar page could be observed."],
        )

    if response.error:
        return ScholarClassification(
            accessible=False,
            blocked=False,
            timeout=False,
            transport_error=True,
            status_code=response.status_code,
            failure_markers=["transport_error"],
            evidence=[_truncate_evidence(f"Transport error: {response.error}")],
        )

    failure_markers: list[str] = []
    evidence: list[str] = []
    searchable_text = _searchable_text(response)
    searchable_url = response.url.lower()

    for needle, marker, message in _BLOCK_MARKER_RULES:
        haystack = searchable_text
        if needle in haystack or needle in searchable_url:
            _append_unique(failure_markers, marker)
            _append_unique(evidence, _truncate_evidence(message))

    if response.status_code == 403:
        _append_unique(failure_markers, "http_403")
        _append_unique(evidence, "HTTP status 403 indicates the request was forbidden.")
    if response.status_code == 429:
        _append_unique(failure_markers, "http_429")
        _append_unique(evidence, "HTTP status 429 indicates rate limiting or throttling.")
    if response.status_code is not None and response.status_code >= 500:
        _append_unique(failure_markers, "server_error")
        _append_unique(evidence, _truncate_evidence(f"HTTP status {response.status_code} indicates a server error."))

    blocked = bool(
        any(
            marker
            for marker in failure_markers
            if marker
            in {
                "http_403",
                "http_429",
                "unusual_traffic",
                "automated_queries",
                "google_sorry",
                "captcha",
                "client_no_permission",
                "unsupported_location",
                "geo_unavailable",
                "access_denied",
            }
        )
    )
    accessible = (
        response.status_code in {200, 301, 302, 303, 307, 308}
        and not blocked
        and "server_error" not in failure_markers
    )

    return ScholarClassification(
        accessible=accessible,
        blocked=blocked,
        timeout=False,
        transport_error=False,
        status_code=response.status_code,
        failure_markers=failure_markers,
        evidence=evidence,
    )


def classify_scholar_access(
    home_response: HttpProbeResponse,
    query_response: HttpProbeResponse | None,
) -> ScholarAccessDecision:
    """Classify combined Scholar home and query responses into a two-stage decision."""
    home_classification = classify_scholar_response(home_response)
    query_classification = (
        None if query_response is None else classify_scholar_response(query_response)
    )
    failure_markers = _merge_unique(
        home_classification.failure_markers,
        [] if query_classification is None else query_classification.failure_markers,
    )
    evidence = _merge_unique(
        home_classification.evidence,
        [] if query_classification is None else query_classification.evidence,
    )

    blocked = home_classification.blocked or bool(query_classification and query_classification.blocked)
    timeout = home_classification.timeout or bool(query_classification and query_classification.timeout)
    transport_error = home_classification.transport_error or bool(
        query_classification and query_classification.transport_error
    )

    home_status = home_response.status_code
    query_status = None if query_response is None else query_response.status_code
    status_values = [status for status in (home_status, query_status) if status is not None]

    if timeout:
        stage = SCHOLAR_STAGE_TIMEOUT
        passed = False
    elif transport_error:
        stage = SCHOLAR_STAGE_TRANSPORT_FAILED
        passed = False
    elif home_status is not None and home_status >= 500 or "server_error" in home_classification.failure_markers:
        stage = SCHOLAR_STAGE_SERVER_ERROR
        passed = False
    elif query_classification is not None and (
        query_status is not None and query_status >= 500 or "server_error" in query_classification.failure_markers
    ):
        stage = SCHOLAR_STAGE_SERVER_ERROR
        passed = False
    elif home_classification.blocked or home_status == 403:
        stage = SCHOLAR_STAGE_HOME_BLOCKED
        passed = False
    elif query_response is None:
        stage = SCHOLAR_STAGE_UNKNOWN
        passed = False
    elif query_classification.blocked or query_status == 403:
        stage = SCHOLAR_STAGE_QUERY_BLOCKED
        passed = False
    elif (
        home_status in {200, 301, 302, 303, 307, 308}
        and query_status in {200, 301, 302, 303, 307, 308}
        and not failure_markers
    ):
        stage = SCHOLAR_STAGE_FULL_ACCESS
        passed = True
    elif any(status >= 500 for status in status_values):
        stage = SCHOLAR_STAGE_SERVER_ERROR
        passed = False
    else:
        stage = SCHOLAR_STAGE_UNKNOWN
        passed = False

    return ScholarAccessDecision(
        stage=stage,
        passed=passed,
        home_status=home_status,
        query_status=query_status,
        blocked=blocked,
        timeout=timeout,
        transport_error=transport_error,
        failure_markers=failure_markers,
        evidence=evidence,
    )


def build_scholar_probe_result(
    candidate_id: str,
    home_response: HttpProbeResponse,
    query_response: HttpProbeResponse | None,
    checked_at: str | None = None,
) -> ProbeResult:
    """Build one semantic ProbeResult from home and query probe responses."""
    decision = classify_scholar_access(home_response, query_response)
    failure_markers = list(decision.failure_markers)
    if decision.stage == SCHOLAR_STAGE_HOME_BLOCKED:
        _append_unique(failure_markers, "stage_home_blocked")
    elif decision.stage == SCHOLAR_STAGE_QUERY_BLOCKED:
        _append_unique(failure_markers, "stage_query_blocked")
    elif decision.stage == SCHOLAR_STAGE_TRANSPORT_FAILED:
        _append_unique(failure_markers, "stage_transport_failed")
    elif decision.stage == SCHOLAR_STAGE_TIMEOUT:
        _append_unique(failure_markers, "stage_timeout")
    elif decision.stage == SCHOLAR_STAGE_SERVER_ERROR:
        _append_unique(failure_markers, "stage_server_error")

    errors: list[str] = []
    if home_response.error:
        errors.append(f"home: {home_response.error}")
    if query_response is not None and query_response.error:
        errors.append(f"query: {query_response.error}")

    return ProbeResult(
        candidate_id=candidate_id,
        home_status=decision.home_status,
        query_status=decision.query_status,
        blocked=decision.blocked,
        timeout=decision.timeout,
        error=None if not errors else "; ".join(errors),
        failure_markers=failure_markers,
        latency_ms=_combine_latency(home_response.elapsed_ms, None if query_response is None else query_response.elapsed_ms),
        checked_at=checked_at or _utc_now_iso8601(),
    )


def build_scholar_home_target() -> HttpProbeTarget:
    """Build the canonical Scholar home-page probe target."""
    return HttpProbeTarget(
        url="https://scholar.google.com/",
        user_agent=BROWSER_USER_AGENT,
    )


def build_scholar_query_target(query: str = "test") -> HttpProbeTarget:
    """Build the canonical Scholar query probe target."""
    encoded_query = quote_plus(query)
    return HttpProbeTarget(
        url=f"https://scholar.google.com/scholar?hl=zh-CN&as_sdt=0%2C5&q={encoded_query}&btnG=",
        user_agent=BROWSER_USER_AGENT,
    )


def build_scholar_reference_query_target() -> HttpProbeTarget:
    """Build the canonical reference Scholar query target used for access checks."""
    return build_scholar_query_target("ppr")


def _searchable_text(response: HttpProbeResponse) -> str:
    """Build one case-insensitive searchable text blob from the response."""
    header_values = " ".join(f"{key}: {value}" for key, value in response.headers.items())
    return f"{header_values} {response.body_prefix}".lower()


def _append_unique(values: list[str], value: str) -> None:
    """Append one string only if it is not already present."""
    if value not in values:
        values.append(value)


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    """Merge two ordered string lists while preserving stable uniqueness."""
    merged: list[str] = []
    for value in left + right:
        _append_unique(merged, value)
    return merged


def _combine_latency(home_elapsed_ms: int | None, query_elapsed_ms: int | None) -> int | None:
    """Combine home and query latency values."""
    if home_elapsed_ms is None and query_elapsed_ms is None:
        return None
    if home_elapsed_ms is None:
        return query_elapsed_ms
    if query_elapsed_ms is None:
        return home_elapsed_ms
    return home_elapsed_ms + query_elapsed_ms


def _utc_now_iso8601() -> str:
    """Return the current UTC timestamp in ISO 8601 format with a Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _truncate_evidence(value: str) -> str:
    """Bound evidence strings to short, reviewable fragments."""
    if len(value) <= 160:
        return value
    return value[:157] + "..."
