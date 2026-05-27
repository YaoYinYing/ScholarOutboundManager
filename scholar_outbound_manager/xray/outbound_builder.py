"""Xray outbound fragment builders."""

from __future__ import annotations

from typing import Any

from scholar_outbound_manager.models import CandidateProxy

_SUPPORTED_NETWORKS = {"tcp", "ws"}


def build_xray_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray outbound for a supported candidate protocol."""
    _validate_candidate_and_tag(candidate, tag)
    protocol = candidate.protocol.lower()
    if protocol == "vless":
        return build_vless_outbound(candidate, tag)
    if protocol == "trojan":
        return build_trojan_outbound(candidate, tag)
    if protocol in {"shadowsocks", "ss"}:
        return build_shadowsocks_outbound(candidate, tag)
    if protocol == "vmess":
        return build_vmess_outbound(candidate, tag)
    if protocol == "hysteria2":
        return build_hysteria2_outbound(candidate, tag)
    raise ValueError(f"Xray outbound is not supported for protocol '{protocol}'.")


def build_vless_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray VLESS outbound fragment from a parsed candidate."""
    _validate_candidate_and_tag(candidate, tag)
    if candidate.protocol.lower() != "vless":
        raise ValueError(f"Xray outbound is not supported for protocol '{candidate.protocol}'.")
    _require_base_endpoint(candidate, protocol_name="VLESS")
    _require_non_empty(candidate.user_id, "VLESS outbound requires a non-empty client identifier.")

    network = _normalize_network(candidate.network)
    security = _normalize_vless_security(candidate.security)

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
        if not candidate.server_name or not candidate.public_key:
            raise ValueError("VLESS Reality outbound requires server name and Reality key material.")
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
    elif security == "tls":
        tls_settings: dict[str, object] = {
            "fingerprint": candidate.fingerprint or "chrome",
        }
        if candidate.server_name:
            tls_settings["serverName"] = candidate.server_name
        stream_settings["tlsSettings"] = tls_settings

    if network == "ws":
        stream_settings["wsSettings"] = _build_ws_settings(candidate)

    return outbound


def build_trojan_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray Trojan outbound fragment."""
    _validate_candidate_and_tag(candidate, tag)
    if candidate.protocol.lower() != "trojan":
        raise ValueError(f"Xray outbound is not supported for protocol '{candidate.protocol}'.")
    _require_base_endpoint(candidate, protocol_name="Trojan")
    _require_non_empty(candidate.password, "Trojan outbound requires a non-empty authentication secret.")

    network = _normalize_network(candidate.network)
    security = _normalize_optional_tls_security(candidate.security, protocol_name="Trojan")

    outbound: dict[str, object] = {
        "tag": tag,
        "protocol": "trojan",
        "settings": {
            "servers": [
                {
                    "address": candidate.address,
                    "port": candidate.port,
                    "password": candidate.password,
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

    if security == "tls":
        tls_settings: dict[str, object] = {}
        if candidate.server_name:
            tls_settings["serverName"] = candidate.server_name
        stream_settings["tlsSettings"] = tls_settings
    if network == "ws":
        stream_settings["wsSettings"] = _build_ws_settings(candidate)

    return outbound


def build_shadowsocks_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray Shadowsocks outbound fragment."""
    _validate_candidate_and_tag(candidate, tag)
    if candidate.protocol.lower() not in {"shadowsocks", "ss"}:
        raise ValueError(f"Xray outbound is not supported for protocol '{candidate.protocol}'.")
    _require_base_endpoint(candidate, protocol_name="Shadowsocks")
    _require_non_empty(candidate.encryption, "Shadowsocks outbound requires a non-empty method.")
    _require_non_empty(candidate.password, "Shadowsocks outbound requires a non-empty authentication secret.")

    return {
        "tag": tag,
        "protocol": "shadowsocks",
        "settings": {
            "servers": [
                {
                    "address": candidate.address,
                    "port": candidate.port,
                    "method": candidate.encryption,
                    "password": candidate.password,
                }
            ]
        },
    }


def build_vmess_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray VMess outbound fragment."""
    _validate_candidate_and_tag(candidate, tag)
    if candidate.protocol.lower() != "vmess":
        raise ValueError(f"Xray outbound is not supported for protocol '{candidate.protocol}'.")
    _require_base_endpoint(candidate, protocol_name="VMess")
    _require_non_empty(candidate.user_id, "VMess outbound requires a non-empty client identifier.")

    network = _normalize_network(candidate.network)
    security = _normalize_vmess_security(candidate.security)
    alter_id = _extract_alter_id(candidate.extra)

    outbound: dict[str, object] = {
        "tag": tag,
        "protocol": "vmess",
        "settings": {
            "vnext": [
                {
                    "address": candidate.address,
                    "port": candidate.port,
                    "users": [
                        {
                            "id": candidate.user_id,
                            "alterId": alter_id,
                            "security": candidate.encryption or "auto",
                        }
                    ],
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

    if security == "tls":
        tls_settings: dict[str, object] = {}
        if candidate.server_name:
            tls_settings["serverName"] = candidate.server_name
        stream_settings["tlsSettings"] = tls_settings
    if network == "ws":
        stream_settings["wsSettings"] = _build_ws_settings(candidate)

    return outbound


def build_hysteria2_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray Hysteria outbound fragment for a Hysteria2 candidate."""
    _validate_candidate_and_tag(candidate, tag)
    if candidate.protocol.lower() != "hysteria2":
        raise ValueError(f"Xray outbound is not supported for protocol '{candidate.protocol}'.")
    _require_base_endpoint(candidate, protocol_name="Hysteria2")
    _require_non_empty(candidate.password, "Hysteria2 outbound requires a non-empty authentication secret.")
    _require_hysteria2_supported_fields(candidate)
    server_name = candidate.server_name or candidate.address
    allow_insecure = _hysteria2_allow_insecure(candidate)

    return {
        "tag": tag,
        "protocol": "hysteria",
        "settings": {
            "version": 2,
            "address": candidate.address,
            "port": candidate.port,
        },
        "streamSettings": {
            "network": "hysteria",
            "security": "tls",
            "tlsSettings": {
                # Fall back to the endpoint address so Xray still sends SNI/hostname-based TLS
                # when the Clash node omits an explicit server name field.
                "serverName": server_name,
                "allowInsecure": allow_insecure,
            },
            "hysteriaSettings": {
                "version": 2,
                "auth": candidate.password,
            },
        },
    }


def _validate_candidate_and_tag(candidate: CandidateProxy, tag: str) -> None:
    """Validate shared preconditions for all outbound builders."""
    if not tag:
        raise ValueError("Xray outbound tag must not be empty.")
    if not candidate.supported:
        raise ValueError(candidate.unsupported_reason or "Candidate is marked unsupported.")


def _require_base_endpoint(candidate: CandidateProxy, *, protocol_name: str) -> None:
    """Validate that a candidate has the shared address and port fields."""
    if not candidate.address:
        raise ValueError(f"{protocol_name} outbound requires a non-empty address.")
    if candidate.port <= 0:
        raise ValueError(f"{protocol_name} outbound requires port > 0.")


def _require_non_empty(value: str | None, message: str) -> None:
    """Raise when a required string field is empty."""
    if not value:
        raise ValueError(message)


def _normalize_network(network: str | None) -> str:
    """Normalize outbound network selection."""
    normalized = (network or "tcp").strip().lower()
    if normalized == "grpc":
        raise ValueError("Phase 13B does not support grpc yet.")
    if normalized not in _SUPPORTED_NETWORKS:
        raise ValueError(f"Xray outbound does not support network '{normalized}'.")
    return normalized


def _normalize_vless_security(security: str | None) -> str:
    """Normalize VLESS transport security."""
    normalized = (security or "none").strip().lower()
    if normalized not in {"none", "tls", "reality"}:
        raise ValueError(f"VLESS outbound does not support security '{normalized}'.")
    return normalized


def _normalize_optional_tls_security(security: str | None, *, protocol_name: str) -> str:
    """Normalize protocol security for builders that only support none/tls."""
    normalized = (security or "tls").strip().lower()
    if normalized not in {"none", "tls"}:
        raise ValueError(f"{protocol_name} outbound does not support security '{normalized}'.")
    return normalized


def _normalize_vmess_security(security: str | None) -> str:
    """Normalize VMess transport security."""
    normalized = (security or "none").strip().lower()
    if normalized not in {"none", "tls"}:
        raise ValueError(f"VMess outbound does not support security '{normalized}'.")
    return normalized


def _extract_alter_id(extra: dict[str, object]) -> int:
    """Extract a VMess alterId from candidate metadata."""
    for key in ("alter_id", "alterId"):
        value = extra.get(key)
        if value is None:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            raise ValueError("VMess outbound requires a valid alterId value.")
    return 0


def _build_ws_settings(candidate: CandidateProxy) -> dict[str, object]:
    """Build WebSocket settings without leaking source material."""
    headers: dict[str, object] = {}
    if candidate.host:
        headers["Host"] = candidate.host
    return {
        "path": candidate.path or "/",
        "headers": headers,
    }


def _require_hysteria2_supported_fields(candidate: CandidateProxy) -> None:
    """Reject Hysteria2 candidates with field combinations not mapped to Xray yet."""
    obfs = candidate.extra.get("obfs")
    obfs_password = candidate.extra.get("obfs-password")
    if obfs or obfs_password:
        raise ValueError("Hysteria2 obfs is not mapped to Xray yet.")
    if candidate.alpn:
        raise ValueError("Hysteria2 alpn is not mapped to Xray yet.")


def _hysteria2_allow_insecure(candidate: CandidateProxy) -> bool:
    """Resolve Hysteria2 TLS allowInsecure from normalized parser metadata."""
    for key in ("skip_cert_verify", "skip-cert-verify"):
        value = candidate.extra.get(key)
        if isinstance(value, bool):
            return value
    return False


def _normalize_alpn(value: str | None) -> list[str] | str | None:
    """Normalize ALPN values for Xray output."""
    if value is None:
        return None
    if "," not in value:
        return value
    values = [item.strip() for item in value.split(",") if item.strip()]
    return values or None
