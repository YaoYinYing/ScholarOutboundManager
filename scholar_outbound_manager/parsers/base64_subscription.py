"""Base64-encoded subscription parsing support."""

from __future__ import annotations

import base64
import binascii


def decode_subscription_text(raw_text: str) -> str:
    """Decode a subscription body when it is base64-encoded text."""
    stripped = "".join(raw_text.strip().split())
    if not stripped:
        return raw_text

    candidates = [
        stripped,
        _add_base64_padding(stripped),
    ]

    for candidate in candidates:
        decoded_text = _try_decode_base64(candidate)
        if decoded_text is not None and _looks_like_subscription_text(decoded_text):
            return decoded_text

        decoded_text = _try_decode_base64(candidate, urlsafe=True)
        if decoded_text is not None and _looks_like_subscription_text(decoded_text):
            return decoded_text

    return raw_text


def split_subscription_lines(text: str) -> list[str]:
    """Split subscription text into non-empty non-comment lines."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def _add_base64_padding(value: str) -> str:
    """Add standard base64 padding when it is missing."""
    remainder = len(value) % 4
    if remainder == 0:
        return value
    return value + ("=" * (4 - remainder))


def _try_decode_base64(value: str, urlsafe: bool = False) -> str | None:
    """Attempt to decode UTF-8 text from base64 input."""
    try:
        if urlsafe:
            decoded = base64.urlsafe_b64decode(value)
        else:
            decoded = base64.b64decode(value, validate=True)
        return decoded.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None


def _looks_like_subscription_text(value: str) -> bool:
    """Determine whether decoded text resembles subscription content."""
    return "://" in value or "proxies:" in value or "vless://" in value
