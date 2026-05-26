"""Subscription fetching helpers."""

from __future__ import annotations

import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request
from urllib.request import urlopen

from scholar_outbound_manager.models import SubscriptionSource


@dataclass(frozen=True)
class FetchedSubscription:
    """Represent one downloaded subscription payload."""

    source_name: str
    content: str
    byte_count: int


@dataclass(frozen=True)
class FetchSummary:
    """Summarize one sequential subscription fetch run."""

    source_count: int
    fetched_count: int
    disabled_count: int
    failed_count: int
    total_bytes: int
    errors: list[str]
    error_records: list["FetchErrorRecord"]


@dataclass(frozen=True)
class FetchErrorRecord:
    """Represent one structured non-secret fetch failure."""

    source_name: str
    category: str
    message: str
    http_status: int | None = None


def fetch_subscription(
    source: SubscriptionSource,
    timeout_seconds: float,
    max_bytes: int = 1_048_576,
) -> FetchedSubscription:
    """Download one enabled subscription using the standard library only."""
    if not source.enabled:
        raise ValueError(f"Subscription source '{source.name}' is disabled.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0.")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be greater than 0.")

    parsed = urlsplit(source.url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"Subscription source '{source.name}' must use http or https.")

    request_headers = dict(source.headers)
    if not any(str(key).lower() == "user-agent" for key in request_headers):
        request_headers["User-Agent"] = "ScholarOutboundManager/0.1"
    request = Request(source.url, headers=request_headers)
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError(
                f"Subscription source '{source.name}' is too large and exceeds the configured byte limit."
            )
        charset = response.headers.get_content_charset() or "utf-8"

    return FetchedSubscription(
        source_name=source.name,
        content=payload.decode(charset, errors="replace"),
        byte_count=len(payload),
    )


def fetch_enabled_subscriptions(
    sources: list[SubscriptionSource],
    timeout_seconds: float,
    max_bytes: int = 1_048_576,
    fetch_func: Callable[[SubscriptionSource, float, int], FetchedSubscription] = fetch_subscription,
) -> tuple[list[FetchedSubscription], FetchSummary]:
    """Fetch enabled subscriptions sequentially without failing the full batch."""
    fetched: list[FetchedSubscription] = []
    errors: list[str] = []
    error_records: list[FetchErrorRecord] = []
    disabled_count = 0
    total_bytes = 0

    for source in sources:
        if not source.enabled:
            disabled_count += 1
            continue
        try:
            result = fetch_func(source, timeout_seconds, max_bytes)
        except Exception as exc:  # pragma: no cover - defensive boundary
            error_record = _classify_fetch_exception(source.name, exc)
            errors.append(error_record.message)
            error_records.append(error_record)
            continue
        fetched.append(result)
        total_bytes += result.byte_count

    summary = FetchSummary(
        source_count=len(sources),
        fetched_count=len(fetched),
        disabled_count=disabled_count,
        failed_count=len(error_records),
        total_bytes=total_bytes,
        errors=errors,
        error_records=error_records,
    )
    return fetched, summary


def _classify_fetch_exception(source_name: str, exc: Exception) -> FetchErrorRecord:
    """Classify one fetch failure into a structured safe category."""
    if isinstance(exc, HTTPError):
        return FetchErrorRecord(
            source_name=source_name,
            category="http_error",
            message=f"Subscription source '{source_name}' failed: HTTP {exc.code}.",
            http_status=exc.code,
        )

    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        reason_text = _safe_reason_text(reason if reason is not None else exc)
        lowered = reason_text.lower()
        if isinstance(reason, TimeoutError) or "timed out" in lowered:
            return FetchErrorRecord(source_name, "timeout", f"Subscription source '{source_name}' failed: {reason_text}.")
        if isinstance(reason, ssl.SSLError) or "ssl" in lowered or "certificate" in lowered:
            return FetchErrorRecord(source_name, "ssl_error", f"Subscription source '{source_name}' failed: {reason_text}.")
        if any(fragment in lowered for fragment in ("name or service not known", "nodename nor servname", "temporary failure in name resolution")):
            return FetchErrorRecord(source_name, "dns_error", f"Subscription source '{source_name}' failed: {reason_text}.")
        if any(fragment in lowered for fragment in ("connection refused", "connection reset")):
            return FetchErrorRecord(source_name, "connection_error", f"Subscription source '{source_name}' failed: {reason_text}.")
        return FetchErrorRecord(source_name, "url_error", f"Subscription source '{source_name}' failed: {reason_text}.")

    if isinstance(exc, TimeoutError):
        return FetchErrorRecord(source_name, "timeout", f"Subscription source '{source_name}' failed: {_safe_reason_text(exc)}.")
    if isinstance(exc, ssl.SSLError):
        return FetchErrorRecord(source_name, "ssl_error", f"Subscription source '{source_name}' failed: {_safe_reason_text(exc)}.")
    if isinstance(exc, (ConnectionRefusedError, ConnectionResetError)):
        return FetchErrorRecord(source_name, "connection_error", f"Subscription source '{source_name}' failed: {_safe_reason_text(exc)}.")
    if isinstance(exc, ValueError):
        reason_text = _safe_reason_text(exc)
        lowered = reason_text.lower()
        if "too large" in lowered:
            return FetchErrorRecord(source_name, "too_large", f"Subscription source '{source_name}' failed: {reason_text}.")
        if "http or https" in lowered or "scheme" in lowered:
            return FetchErrorRecord(source_name, "unsupported_scheme", f"Subscription source '{source_name}' failed: {reason_text}.")
        return FetchErrorRecord(source_name, "unknown_error", f"Subscription source '{source_name}' failed: {reason_text}.")
    if isinstance(exc, OSError):
        return FetchErrorRecord(source_name, "os_error", f"Subscription source '{source_name}' failed: {_safe_reason_text(exc)}.")
    return FetchErrorRecord(source_name, "unknown_error", f"Subscription source '{source_name}' failed: {_safe_reason_text(exc)}.")


def _safe_reason_text(reason: object) -> str:
    """Return a compact reason string without embedding subscription URLs."""
    text = str(reason).strip() or "unknown error"
    sanitized = text.replace("\n", " ")
    sanitized = re.sub(r"https?://\S+", "<REDACTED_URL>", sanitized)
    sanitized = re.sub(r"vless://\S+", "<REDACTED_VLESS_URI>", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        "<REDACTED_UUID>",
        sanitized,
    )
    sanitized = re.sub(r"(?i)\b(?:pbk|public_key)\s*[:=]\s*([^\s&]+)", "public_key=<REDACTED>", sanitized)
    sanitized = re.sub(r"(?i)\b(token|secret|password)\b", "<REDACTED>", sanitized)
    return sanitized
