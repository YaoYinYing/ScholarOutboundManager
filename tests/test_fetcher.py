"""Tests for sequential subscription fetching helpers."""

from __future__ import annotations

import io
from email.message import Message

import pytest

from scholar_outbound_manager import fetcher
from scholar_outbound_manager.fetcher import FetchedSubscription
from scholar_outbound_manager.fetcher import fetch_enabled_subscriptions
from scholar_outbound_manager.fetcher import fetch_subscription
from scholar_outbound_manager.models import SubscriptionSource


def test_fetch_enabled_subscriptions_skips_disabled_sources() -> None:
    """Skip disabled sources without calling the fetcher."""
    observed: list[str] = []
    sources = [
        SubscriptionSource(name="enabled", url="https://example.invalid/enabled", enabled=True),
        SubscriptionSource(name="disabled", url="https://example.invalid/disabled", enabled=False),
    ]

    def fake_fetch(source: SubscriptionSource, timeout_seconds: float, max_bytes: int) -> FetchedSubscription:
        observed.append(source.name)
        return FetchedSubscription(source_name=source.name, content="vless://line", byte_count=12)

    fetched, summary = fetch_enabled_subscriptions(sources, 5.0, fetch_func=fake_fetch)

    assert observed == ["enabled"]
    assert len(fetched) == 1
    assert summary.disabled_count == 1
    assert summary.fetched_count == 1


def test_fetch_enabled_subscriptions_returns_fake_successes() -> None:
    """Collect successful results from the injected fetcher."""
    sources = [SubscriptionSource(name="enabled", url="https://example.invalid/enabled", enabled=True)]

    fetched, summary = fetch_enabled_subscriptions(
        sources,
        5.0,
        fetch_func=lambda source, timeout_seconds, max_bytes: FetchedSubscription(
            source_name=source.name,
            content="vless://line",
            byte_count=20,
        ),
    )

    assert fetched[0].source_name == "enabled"
    assert summary.total_bytes == 20


def test_fetch_enabled_subscriptions_records_individual_failures() -> None:
    """Keep fetching after one source fails."""
    sources = [
        SubscriptionSource(name="one", url="https://example.invalid/one", enabled=True),
        SubscriptionSource(name="two", url="https://example.invalid/two", enabled=True),
    ]

    def fake_fetch(source: SubscriptionSource, timeout_seconds: float, max_bytes: int) -> FetchedSubscription:
        if source.name == "one":
            raise ValueError("broken upstream")
        return FetchedSubscription(source_name=source.name, content="vless://line", byte_count=10)

    fetched, summary = fetch_enabled_subscriptions(sources, 5.0, fetch_func=fake_fetch)

    assert [item.source_name for item in fetched] == ["two"]
    assert summary.failed_count == 1
    assert summary.fetched_count == 1


def test_fetch_enabled_subscriptions_errors_do_not_include_urls() -> None:
    """Keep sensitive subscription URLs out of error summaries."""
    sources = [SubscriptionSource(name="one", url="https://example.invalid/token-secret", enabled=True)]

    def fake_fetch(source: SubscriptionSource, timeout_seconds: float, max_bytes: int) -> FetchedSubscription:
        raise ValueError(f"failure from {source.url}")

    _, summary = fetch_enabled_subscriptions(sources, 5.0, fetch_func=fake_fetch)

    rendered = " ".join(summary.errors)
    assert "https://example.invalid/token-secret" not in rendered
    assert "one" in rendered


def test_fetch_subscription_rejects_non_http_url() -> None:
    """Reject non-http subscription URLs."""
    source = SubscriptionSource(name="file-source", url="file:///tmp/subscription.txt", enabled=True)

    with pytest.raises(ValueError, match="http or https"):
        fetch_subscription(source, 5.0)


def test_fetch_subscription_rejects_non_positive_timeout() -> None:
    """Reject non-positive timeouts."""
    source = SubscriptionSource(name="fixture", url="https://example.invalid/subscription", enabled=True)

    with pytest.raises(ValueError, match="timeout_seconds"):
        fetch_subscription(source, 0)


def test_fetch_subscription_rejects_non_positive_max_bytes() -> None:
    """Reject non-positive max-byte limits."""
    source = SubscriptionSource(name="fixture", url="https://example.invalid/subscription", enabled=True)

    with pytest.raises(ValueError, match="max_bytes"):
        fetch_subscription(source, 5.0, max_bytes=0)


def test_fetcher_helpers_do_not_print(capsys) -> None:
    """Avoid writing to stdout or stderr."""
    sources = [SubscriptionSource(name="one", url="https://example.invalid/one", enabled=False)]

    fetch_enabled_subscriptions(sources, 5.0)
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == ""


def test_fetch_subscription_uses_headers_and_decodes_response(monkeypatch) -> None:
    """Use configured request headers and response charset when downloading."""
    observed: dict[str, object] = {}
    source = SubscriptionSource(
        name="fixture",
        url="https://example.invalid/subscription",
        enabled=True,
        headers={"X-Test": "value"},
    )

    class FakeResponse:
        def __init__(self) -> None:
            self.headers = Message()
            self.headers["Content-Type"] = "text/plain; charset=utf-8"
            self._payload = io.BytesIO("vless://fixture".encode("utf-8"))

        def read(self, size: int = -1) -> bytes:
            return self._payload.read(size)

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def fake_urlopen(request, timeout: float):
        observed["header"] = request.get_header("X-test")
        observed["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(fetcher, "urlopen", fake_urlopen)

    fetched = fetch_subscription(source, 7.0)

    assert observed["header"] == "value"
    assert observed["timeout"] == 7.0
    assert fetched.content == "vless://fixture"

