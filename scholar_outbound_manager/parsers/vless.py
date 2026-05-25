"""VLESS URI parsing support."""

from __future__ import annotations

from urllib.parse import parse_qs
from urllib.parse import SplitResult
from urllib.parse import unquote
from urllib.parse import urlsplit

from scholar_outbound_manager.models import CandidateProxy


def parse_vless_uri(uri: str, source_name: str) -> CandidateProxy:
    """Parse a VLESS URI into a candidate proxy model."""
    parsed = urlsplit(uri)
    if parsed.scheme.lower() != "vless":
        return _unsupported_candidate(
            uri=uri,
            source_name=source_name,
            reason="URI scheme is not vless.",
        )

    query = parse_qs(parsed.query, keep_blank_values=True)
    address = parsed.hostname or ""
    raw_name = _safe_raw_name(parsed.fragment, address)
    user_id = parsed.username
    port, port_error = _safe_port(parsed)

    missing_fields: list[str] = []
    if not user_id:
        missing_fields.append("UUID")
    if not address:
        missing_fields.append("host")
    if port is None:
        missing_fields.append("port")

    unsupported_reasons: list[str] = []
    if port_error is not None:
        unsupported_reasons.append(port_error)
    if missing_fields:
        unsupported_reasons.append(f"Missing required VLESS fields: {', '.join(missing_fields)}.")

    security = _first_query_value(query, "security")
    if security == "reality":
        if not _first_query_value(query, "pbk"):
            unsupported_reasons.append("Reality node is missing pbk.")
        if not _first_query_value(query, "sni"):
            unsupported_reasons.append("Reality node is missing sni.")

    return CandidateProxy(
        source_name=source_name,
        raw_name=raw_name,
        protocol="vless",
        address=address,
        port=port or 0,
        user_id=user_id,
        encryption="none",
        flow=_first_query_value(query, "flow"),
        network=_first_query_value(query, "type"),
        security=security,
        server_name=_first_query_value(query, "sni"),
        fingerprint=_first_query_value(query, "fp"),
        public_key=_first_query_value(query, "pbk"),
        short_id=_first_query_value(query, "sid"),
        alpn=_first_query_value(query, "alpn"),
        path=_first_query_value(query, "path"),
        host=_first_query_value(query, "host"),
        raw_uri=uri,
        supported=not unsupported_reasons,
        unsupported_reason=" ".join(unsupported_reasons) or None,
    )


def _first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    """Return the first query value for a key."""
    values = query.get(key)
    if not values:
        return None
    return values[0] or None


def _safe_port(parsed: SplitResult) -> tuple[int | None, str | None]:
    """Read a parsed URI port without propagating ValueError."""
    try:
        port = parsed.port
    except ValueError:
        return None, "Invalid port in proxy URI."
    return port, None


def _safe_raw_name(fragment: str, address: str) -> str:
    """Build a display name without exposing credentials."""
    if fragment:
        return unquote(fragment)
    if address:
        return f"unnamed-vless-{address}"
    return "unnamed-vless"


def _unsupported_candidate(uri: str, source_name: str, reason: str) -> CandidateProxy:
    """Build a consistent unsupported candidate result."""
    parsed = urlsplit(uri)
    port, port_error = _safe_port(parsed)
    unsupported_reason = reason
    if port_error is not None:
        unsupported_reason = f"{reason} {port_error}".strip()
    scheme = parsed.scheme.lower()
    raw_name = unquote(parsed.fragment) if parsed.fragment else (f"unsupported-{scheme}" if scheme else "unsupported-proxy")
    return CandidateProxy(
        source_name=source_name,
        raw_name=raw_name,
        protocol=scheme or "vless",
        address=parsed.hostname or "",
        port=port or 0,
        raw_uri=uri,
        supported=False,
        unsupported_reason=unsupported_reason,
    )
