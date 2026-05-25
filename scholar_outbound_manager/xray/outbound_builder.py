"""Xray outbound fragment builders."""

from __future__ import annotations

from scholar_outbound_manager.models import CandidateProxy


def build_vless_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray VLESS outbound fragment from a parsed candidate."""
    _validate_candidate(candidate)
    network = candidate.network or "tcp"
    security = candidate.security or "none"

    if network == "grpc":
        raise ValueError("Phase 3 does not support grpc yet.")

    user: dict[str, object] = {
        "id": candidate.user_id,
        "encryption": candidate.encryption or "none",
    }
    if candidate.flow is not None:
        user["flow"] = candidate.flow

    outbound: dict[str, object] = {
        "tag": tag,
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": candidate.address,
                    "port": candidate.port,
                    "users": [user],
                }
            ]
        },
        "streamSettings": {
            "network": network,
            "security": security,
        },
    }

    stream_settings = outbound["streamSettings"]
    assert isinstance(stream_settings, dict)

    if security == "reality":
        if not candidate.server_name:
            raise ValueError("VLESS Reality outbound requires server_name.")
        if not candidate.public_key:
            raise ValueError("VLESS Reality outbound requires public_key.")
        reality_settings: dict[str, object] = {
            "serverName": candidate.server_name,
            "fingerprint": candidate.fingerprint or "chrome",
            "publicKey": candidate.public_key,
            "shortId": candidate.short_id or "",
            "spiderX": "/",
        }
        alpn_values = _normalize_alpn(candidate.alpn)
        if alpn_values is not None:
            reality_settings["alpn"] = alpn_values
        stream_settings["realitySettings"] = reality_settings

    if network == "ws":
        ws_settings: dict[str, object] = {
            "path": candidate.path or "/",
        }
        if candidate.host:
            ws_settings["headers"] = {"Host": candidate.host}
        stream_settings["wsSettings"] = ws_settings

    return outbound


def _validate_candidate(candidate: CandidateProxy) -> None:
    """Validate whether one candidate can be converted to an outbound."""
    if candidate.protocol != "vless":
        raise ValueError(f"Unsupported protocol for Phase 3 outbound builder: {candidate.protocol}.")
    if not candidate.supported:
        reason = candidate.unsupported_reason or "Candidate is marked unsupported."
        raise ValueError(reason)
    if not candidate.address:
        raise ValueError("VLESS outbound requires a non-empty address.")
    if candidate.port <= 0:
        raise ValueError("VLESS outbound requires port > 0.")
    if not candidate.user_id:
        raise ValueError("VLESS outbound requires a non-empty user_id.")


def _normalize_alpn(value: str | None) -> list[str] | str | None:
    """Normalize ALPN values for Xray output."""
    if value is None:
        return None
    if "," not in value:
        return value
    values = [item.strip() for item in value.split(",") if item.strip()]
    return values or None
