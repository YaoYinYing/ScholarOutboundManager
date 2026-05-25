"""Sensitive value redaction helpers."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit
from urllib.parse import urlunsplit


SENSITIVE_FIELD_NAMES = {
    "url",
    "token",
    "secret",
    "password",
    "user_id",
    "uuid",
    "id",
    "public_key",
    "private_key",
    "short_id",
    "raw_uri",
    "headers",
}


def redact_text(value: str) -> str:
    """Redact a sensitive string while preserving limited structure."""
    if _looks_like_url(value):
        return _redact_url(value)
    if len(value) <= 8:
        return "<REDACTED>"
    return f"{value[:4]}<REDACTED>{value[-4:]}"


def redact_mapping(value: Mapping[str, object]) -> dict[str, object]:
    """Redact sensitive values within a mapping."""
    redacted: dict[str, object] = {}
    for key, item in value.items():
        normalized_key = key.lower()
        if normalized_key in SENSITIVE_FIELD_NAMES:
            redacted[key] = _redact_sensitive_value(item)
            continue
        if isinstance(item, Mapping):
            redacted[key] = redact_mapping(item)
            continue
        redacted[key] = item
    return redacted


def _redact_sensitive_value(value: object) -> object:
    """Redact one sensitive object value."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {str(key): _redact_sensitive_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_sensitive_value(item) for item in value]
    return "<REDACTED>"


def _looks_like_url(value: str) -> bool:
    """Return whether a string appears to be a URL."""
    parsed = urlsplit(value)
    return bool(parsed.scheme and parsed.netloc)


def _redact_url(value: str) -> str:
    """Redact a URL while preserving scheme and host details."""
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if ":" in hostname:
        netloc = f"[{hostname}]"
    else:
        netloc = hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    redacted_url = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    if parsed.query or parsed.fragment:
        return f"{redacted_url}<REDACTED_QUERY>"
    return redacted_url
