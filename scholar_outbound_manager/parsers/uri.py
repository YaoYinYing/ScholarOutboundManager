"""Generic URI parsing helpers for proxy subscriptions."""

from __future__ import annotations

from urllib.parse import unquote
from urllib.parse import urlsplit

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.parsers.vless import parse_vless_uri


def parse_proxy_uri(uri: str, source_name: str) -> CandidateProxy:
    """Parse one proxy URI into a candidate model."""
    parsed = urlsplit(uri)
    scheme = parsed.scheme.lower()
    if scheme == "vless":
        return parse_vless_uri(uri, source_name)
    try:
        port = parsed.port
        port_error = None
    except ValueError:
        port = None
        port_error = "Invalid port in proxy URI."
    raw_name = unquote(parsed.fragment) if parsed.fragment else (f"unsupported-{scheme}" if scheme else "unsupported-proxy")
    unsupported_reason = f"Unsupported proxy scheme: {scheme or 'unknown'}"
    if port_error is not None:
        unsupported_reason = f"{unsupported_reason}. {port_error}"

    return CandidateProxy(
        source_name=source_name,
        raw_name=raw_name,
        protocol=scheme or "unknown",
        address=parsed.hostname or "",
        port=port or 0,
        raw_uri=uri,
        supported=False,
        unsupported_reason=unsupported_reason,
    )
