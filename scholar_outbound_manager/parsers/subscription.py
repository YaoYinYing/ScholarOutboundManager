"""Subscription decoding and proxy URI extraction helpers."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from scholar_outbound_manager.fetcher import FetchedSubscription
from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.parsers.uri import parse_proxy_uri
from scholar_outbound_manager.parsers.vless import parse_vless_uri


@dataclass(frozen=True)
class ParsedSubscription:
    """Represent one parsed subscription payload."""

    source_name: str
    candidates: list[CandidateProxy]
    raw_line_count: int
    parsed_count: int
    unsupported_count: int


def decode_subscription_text(content: str, fmt: str = "auto") -> str:
    """Decode one subscription text body in plain, base64, or auto mode."""
    if fmt == "plain":
        return content
    if fmt == "base64":
        return _decode_base64_text(content)
    if fmt != "auto":
        raise ValueError(f"Unsupported subscription format: {fmt}")

    if "://" in content:
        return content
    try:
        decoded = _decode_base64_text(content)
    except ValueError:
        return content
    return decoded if "://" in decoded else content


def extract_proxy_uris(content: str) -> list[str]:
    """Extract one URI-bearing line per non-empty subscription line."""
    uris: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "://" in stripped:
            uris.append(stripped)
    return uris


def parse_subscription_content(
    content: str,
    source_name: str,
    fmt: str = "auto",
) -> ParsedSubscription:
    """Decode and parse one subscription body into candidate models."""
    decoded_text = decode_subscription_text(content, fmt=fmt)
    proxy_uris = extract_proxy_uris(decoded_text)
    candidates: list[CandidateProxy] = []
    for uri in proxy_uris:
        if uri.lower().startswith("vless://"):
            candidates.append(parse_vless_uri(uri, source_name))
        else:
            candidates.append(parse_proxy_uri(uri, source_name))
    unsupported_count = sum(1 for candidate in candidates if not candidate.supported)
    return ParsedSubscription(
        source_name=source_name,
        candidates=candidates,
        raw_line_count=len(decoded_text.splitlines()),
        parsed_count=len(candidates),
        unsupported_count=unsupported_count,
    )


def parse_fetched_subscriptions(
    fetched: list[FetchedSubscription],
    format_by_source: dict[str, str],
) -> list[ParsedSubscription]:
    """Parse all fetched subscriptions using the configured per-source format."""
    parsed_subscriptions: list[ParsedSubscription] = []
    for item in fetched:
        fmt = format_by_source.get(item.source_name, "auto")
        parsed_subscriptions.append(
            parse_subscription_content(
                content=item.content,
                source_name=item.source_name,
                fmt=fmt,
            )
        )
    return parsed_subscriptions


def _decode_base64_text(content: str) -> str:
    """Decode base64 or urlsafe-base64 text into UTF-8 with replacement."""
    stripped = "".join(content.split())
    if not stripped:
        return content

    candidates = [stripped, _add_padding(stripped)]
    for encoded in candidates:
        decoded = _try_base64_decode(encoded, urlsafe=False)
        if decoded is not None:
            return decoded
        decoded = _try_base64_decode(encoded, urlsafe=True)
        if decoded is not None:
            return decoded
    raise ValueError("Subscription content is not valid base64.")


def _add_padding(value: str) -> str:
    """Add base64 padding when it is absent."""
    remainder = len(value) % 4
    if remainder == 0:
        return value
    return value + ("=" * (4 - remainder))


def _try_base64_decode(value: str, *, urlsafe: bool) -> str | None:
    """Attempt one UTF-8 base64 decode without propagating decode errors."""
    try:
        if urlsafe:
            decoded = base64.urlsafe_b64decode(value)
        else:
            decoded = base64.b64decode(value, validate=True)
        return decoded.decode("utf-8", errors="replace")
    except (binascii.Error, ValueError):
        return None
