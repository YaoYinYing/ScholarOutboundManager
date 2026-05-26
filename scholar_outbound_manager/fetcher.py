"""Subscription fetching helpers."""

from __future__ import annotations

import re
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

    request = Request(source.url, headers=dict(source.headers))
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise ValueError(
                    f"Subscription source '{source.name}' is too large and exceeds the configured byte limit."
                )
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        raise ValueError(
            f"Failed to fetch subscription source '{source.name}': HTTP {exc.code}."
        ) from exc
    except URLError as exc:
        reason = getattr(exc, "reason", None)
        raise ValueError(
            f"Failed to fetch subscription source '{source.name}': {_safe_reason_text(reason)}."
        ) from exc
    except OSError as exc:
        raise ValueError(
            f"Failed to fetch subscription source '{source.name}': {_safe_reason_text(exc)}."
        ) from exc

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
    disabled_count = 0
    total_bytes = 0

    for source in sources:
        if not source.enabled:
            disabled_count += 1
            continue
        try:
            result = fetch_func(source, timeout_seconds, max_bytes)
        except Exception as exc:  # pragma: no cover - defensive boundary
            errors.append(_safe_fetch_error(source.name, exc))
            continue
        fetched.append(result)
        total_bytes += result.byte_count

    summary = FetchSummary(
        source_count=len(sources),
        fetched_count=len(fetched),
        disabled_count=disabled_count,
        failed_count=len(errors),
        total_bytes=total_bytes,
        errors=errors,
    )
    return fetched, summary


def _safe_fetch_error(source_name: str, exc: Exception) -> str:
    """Convert one fetch exception into a source-scoped non-secret message."""
    return f"Subscription source '{source_name}' failed: {_safe_reason_text(exc)}."


def _safe_reason_text(reason: object) -> str:
    """Return a compact reason string without embedding subscription URLs."""
    text = str(reason).strip() or "unknown error"
    sanitized = text.replace("\n", " ")
    sanitized = re.sub(r"https?://\S+", "<REDACTED_URL>", sanitized)
    sanitized = re.sub(r"(?i)\b(token|secret|password)\b", "<REDACTED>", sanitized)
    return sanitized
