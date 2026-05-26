"""Tests for sequential subscription fetching helpers."""

from __future__ import annotations

import io
import ssl
from email.message import Message
from urllib.error import HTTPError
from urllib.error import URLError

import pytest

from scholar_outbound_manager import fetcher
from scholar_outbound_manager.fetcher import _classify_fetch_exception
from scholar_outbound_manager.fetcher import build_url_opener
from scholar_outbound_manager.fetcher import FetchedSubscription
from scholar_outbound_manager.fetcher import FetchTransportOptions
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
    assert len(summary.error_records) == 1


def test_fetch_enabled_subscriptions_errors_do_not_include_urls() -> None:
    """Keep sensitive subscription URLs out of error summaries."""
    sources = [SubscriptionSource(name="one", url="https://example.invalid/token-secret", enabled=True)]

    def fake_fetch(source: SubscriptionSource, timeout_seconds: float, max_bytes: int) -> FetchedSubscription:
        raise ValueError(f"failure from {source.url}")

    _, summary = fetch_enabled_subscriptions(sources, 5.0, fetch_func=fake_fetch)

    rendered = " ".join(summary.errors)
    structured_rendered = " ".join(record.message for record in summary.error_records)
    assert "https://example.invalid/token-secret" not in rendered
    assert "https://example.invalid/token-secret" not in structured_rendered
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

    class FakeOpener:
        def open(self, request, timeout: float):
            observed["header"] = request.get_header("X-test")
            observed["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(fetcher, "build_url_opener", lambda options=None: FakeOpener())

    fetched = fetch_subscription(source, 7.0)

    assert observed["header"] == "value"
    assert observed["timeout"] == 7.0
    assert fetched.content == "vless://fixture"


def test_build_url_opener_without_proxy_returns_opener() -> None:
    """Build a default opener when no proxy is configured."""
    opener = build_url_opener()

    assert hasattr(opener, "open")


def test_build_url_opener_accepts_http_proxy() -> None:
    """Accept HTTP proxy URLs."""
    opener = build_url_opener(FetchTransportOptions(proxy_url="http://127.0.0.1:7890"))

    assert hasattr(opener, "open")


def test_build_url_opener_accepts_https_proxy() -> None:
    """Accept HTTPS proxy URLs."""
    opener = build_url_opener(FetchTransportOptions(proxy_url="https://127.0.0.1:7890"))

    assert hasattr(opener, "open")


def test_build_url_opener_rejects_non_http_proxy_without_leaking_url() -> None:
    """Reject unsupported proxy schemes without echoing the raw proxy URL."""
    proxy_url = "socks5://user:pass@example.invalid:1080"

    with pytest.raises(ValueError, match="proxy URL must use http or https") as exc_info:
        build_url_opener(FetchTransportOptions(proxy_url=proxy_url))

    assert proxy_url not in str(exc_info.value)


def test_fetch_subscription_uses_opener_open_not_urlopen(monkeypatch) -> None:
    """Call the opener returned by build_url_opener for network access."""
    observed: dict[str, object] = {"open_called": False}
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

    class FakeOpener:
        def open(self, request, timeout: float):
            observed["open_called"] = True
            observed["user_agent"] = request.get_header("User-agent")
            return FakeResponse()

    monkeypatch.setattr(fetcher, "build_url_opener", lambda options=None: FakeOpener())

    fetched = fetch_subscription(source, 7.0)

    assert observed["open_called"] is True
    assert observed["user_agent"] == "ScholarOutboundManager/0.1"
    assert fetched.content == "vless://fixture"


def test_fetch_enabled_subscriptions_passes_transport_options() -> None:
    """Pass transport options through to the injected fetcher."""
    observed: dict[str, object] = {}
    sources = [SubscriptionSource(name="enabled", url="https://example.invalid/enabled", enabled=True)]
    transport_options = FetchTransportOptions(proxy_url="http://127.0.0.1:7890")

    def fake_fetch(
        source: SubscriptionSource,
        timeout_seconds: float,
        max_bytes: int,
        options: FetchTransportOptions | None,
    ) -> FetchedSubscription:
        observed["proxy_url"] = None if options is None else options.proxy_url
        return FetchedSubscription(source_name=source.name, content="vless://line", byte_count=12)

    fetched, _summary = fetch_enabled_subscriptions(
        sources,
        5.0,
        fetch_func=fake_fetch,
        transport_options=transport_options,
    )

    assert len(fetched) == 1
    assert observed["proxy_url"] == "http://127.0.0.1:7890"


def test_classify_fetch_exception_marks_unsupported_proxy() -> None:
    """Classify proxy validation failures as unsupported_proxy."""
    record = _classify_fetch_exception(
        "fixture",
        ValueError("proxy URL must use http or https."),
    )

    assert record.category == "unsupported_proxy"


def test_proxy_related_error_messages_do_not_include_proxy_url() -> None:
    """Keep proxy URLs out of redacted error messages."""
    proxy_url = "socks5://user:pass@example.invalid:1080"
    record = _classify_fetch_exception("fixture", ValueError(f"proxy failed for {proxy_url}"))

    assert proxy_url not in record.message


def test_classify_fetch_exception_marks_http_errors() -> None:
    """Classify HTTP errors with status codes."""
    record = _classify_fetch_exception(
        "fixture",
        HTTPError("https://example.invalid/token", 403, "Forbidden", None, None),
    )

    assert record.category == "http_error"
    assert record.http_status == 403


def test_classify_fetch_exception_marks_timeout_url_errors() -> None:
    """Classify URL timeouts as timeout."""
    record = _classify_fetch_exception("fixture", URLError(TimeoutError("timed out")))

    assert record.category == "timeout"


def test_classify_fetch_exception_marks_dns_url_errors() -> None:
    """Classify DNS-style failures as dns_error."""
    record = _classify_fetch_exception(
        "fixture",
        URLError("nodename nor servname provided, or not known"),
    )

    assert record.category == "dns_error"


def test_classify_fetch_exception_marks_ssl_errors() -> None:
    """Classify SSL failures as ssl_error."""
    record = _classify_fetch_exception("fixture", ssl.SSLError("CERTIFICATE_VERIFY_FAILED"))

    assert record.category == "ssl_error"


def test_classify_fetch_exception_marks_connection_errors() -> None:
    """Classify connection failures as connection_error."""
    record = _classify_fetch_exception("fixture", ConnectionRefusedError("Connection refused"))

    assert record.category == "connection_error"


def test_classify_fetch_exception_marks_too_large_value_errors() -> None:
    """Classify size-limit failures as too_large."""
    record = _classify_fetch_exception("fixture", ValueError("subscription is too large"))

    assert record.category == "too_large"


def test_classify_fetch_exception_marks_unsupported_schemes() -> None:
    """Classify unsupported-scheme failures explicitly."""
    record = _classify_fetch_exception(
        "fixture",
        ValueError("Subscription source 'fixture' must use http or https."),
    )

    assert record.category == "unsupported_scheme"


def test_fetch_subscription_adds_default_user_agent(monkeypatch) -> None:
    """Add a default User-Agent when the source does not define one."""
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

    class FakeOpener:
        def open(self, request, timeout: float):
            observed["user_agent"] = request.get_header("User-agent")
            return FakeResponse()

    monkeypatch.setattr(fetcher, "build_url_opener", lambda options=None: FakeOpener())

    fetch_subscription(source, 7.0)

    assert observed["user_agent"] == "ScholarOutboundManager/0.1"


def test_fetch_subscription_preserves_custom_user_agent(monkeypatch) -> None:
    """Keep a user-provided User-Agent header unchanged."""
    observed: dict[str, object] = {}
    source = SubscriptionSource(
        name="fixture",
        url="https://example.invalid/subscription",
        enabled=True,
        headers={"User-Agent": "CustomAgent/1.0"},
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

    class FakeOpener:
        def open(self, request, timeout: float):
            observed["user_agent"] = request.get_header("User-agent")
            return FakeResponse()

    monkeypatch.setattr(fetcher, "build_url_opener", lambda options=None: FakeOpener())

    fetch_subscription(source, 7.0)

    assert observed["user_agent"] == "CustomAgent/1.0"
