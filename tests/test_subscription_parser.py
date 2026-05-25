"""Tests for plain text and base64 subscription parsing helpers."""

import base64
from pathlib import Path

from scholar_outbound_manager.parsers.base64_subscription import decode_subscription_text
from scholar_outbound_manager.parsers.base64_subscription import split_subscription_lines


def test_split_subscription_lines_ignores_empty_and_comment_lines() -> None:
    """Keep only meaningful URI lines from plain text."""
    text = "\n# comment\nvless://one\n\n  # another comment\nvless://two  \n"

    assert split_subscription_lines(text) == ["vless://one", "vless://two"]


def test_decode_subscription_text_supports_base64_fixture() -> None:
    """Decode a base64 fixture into the original URI line."""
    raw_text = (Path(__file__).resolve().parent / "fixtures" / "vless_reality_base64.txt").read_text(
        encoding="utf-8"
    )

    decoded = decode_subscription_text(raw_text)

    assert "vless://" in decoded
    assert "PUBLIC_KEY_PLACEHOLDER" in decoded


def test_decode_subscription_text_keeps_plain_text_when_not_base64() -> None:
    """Treat non-base64 content as plain text."""
    raw_text = "vless://plain-text-line"

    assert decode_subscription_text(raw_text) == raw_text


def test_decode_subscription_text_supports_missing_padding() -> None:
    """Decode base64 input even when padding is omitted."""
    raw_text = "dmxlc3M6Ly9wYWRkaW5nLXRlc3Q"

    assert decode_subscription_text(raw_text) == "vless://padding-test"


def test_decode_subscription_text_supports_urlsafe_base64() -> None:
    """Decode urlsafe base64 when it contains subscription-like text."""
    raw_text = base64.urlsafe_b64encode(b"vless://urlsafe-test").decode("ascii")

    assert decode_subscription_text(raw_text) == "vless://urlsafe-test"


def test_decode_subscription_text_rejects_non_subscription_payload() -> None:
    """Keep base64 input unchanged when decoded text does not look like a subscription."""
    raw_text = "dGVzdA=="

    assert decode_subscription_text(raw_text) == raw_text
