"""Build structured Xray outbound specifications from candidates."""

from __future__ import annotations

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.xray.spec import HysteriaProtocolSpec
from scholar_outbound_manager.xray.spec import ShadowsocksProtocolSpec
from scholar_outbound_manager.xray.spec import TrojanProtocolSpec
from scholar_outbound_manager.xray.spec import VlessProtocolSpec
from scholar_outbound_manager.xray.spec import VmessProtocolSpec
from scholar_outbound_manager.xray.spec import XrayHysteriaTransportSpec
from scholar_outbound_manager.xray.spec import XrayOutboundSpec
from scholar_outbound_manager.xray.spec import XrayRealitySpec
from scholar_outbound_manager.xray.spec import XrayServerEndpoint
from scholar_outbound_manager.xray.spec import XrayTlsSpec
from scholar_outbound_manager.xray.spec import XrayTransportSpec

_SUPPORTED_NETWORKS = {"tcp", "ws"}


def build_xray_outbound_spec(candidate: CandidateProxy, tag: str) -> XrayOutboundSpec:
    """Build one normalized Xray outbound specification."""
    _validate_candidate_and_tag(candidate, tag)
    protocol = candidate.protocol.lower()
    if protocol == "vless":
        return build_vless_spec(candidate, tag)
    if protocol == "trojan":
        return build_trojan_spec(candidate, tag)
    if protocol in {"shadowsocks", "ss"}:
        return build_shadowsocks_spec(candidate, tag)
    if protocol == "vmess":
        return build_vmess_spec(candidate, tag)
    if protocol == "hysteria2":
        return build_hysteria2_spec(candidate, tag)
    raise ValueError(f"Xray outbound is not supported for protocol '{protocol}'.")


def build_vless_spec(candidate: CandidateProxy, tag: str) -> XrayOutboundSpec:
    """Build one VLESS spec."""
    _validate_protocol(candidate, tag, expected_protocol="vless")
    endpoint = _require_endpoint(candidate, protocol_name="VLESS")
    _require_non_empty(candidate.user_id, "VLESS outbound requires a non-empty client identifier.")

    transport = _build_transport_spec(candidate)
    security = _normalize_vless_security(candidate.security)
    tls: XrayTlsSpec | None = None
    reality: XrayRealitySpec | None = None

    if security == "tls":
        tls = XrayTlsSpec(
            enabled=True,
            server_name=candidate.server_name,
            fingerprint=candidate.fingerprint or "chrome",
        )
    elif security == "reality":
        if not candidate.server_name or not candidate.public_key:
            raise ValueError("VLESS Reality outbound requires server name and Reality key material.")
        reality = XrayRealitySpec(
            server_name=candidate.server_name,
            public_key=candidate.public_key,
            short_id=candidate.short_id or "",
            fingerprint=candidate.fingerprint or "chrome",
            spider_x="/",
            alpn=_normalize_alpn_list(candidate.alpn),
        )

    return XrayOutboundSpec(
        tag=tag,
        protocol="vless",
        protocol_spec=VlessProtocolSpec(
            endpoint=endpoint,
            user_id=candidate.user_id,
            encryption=candidate.encryption or "none",
            flow=candidate.flow,
        ),
        transport=transport,
        tls=tls,
        reality=reality,
    )


def build_trojan_spec(candidate: CandidateProxy, tag: str) -> XrayOutboundSpec:
    """Build one Trojan spec."""
    _validate_protocol(candidate, tag, expected_protocol="trojan")
    endpoint = _require_endpoint(candidate, protocol_name="Trojan")
    _require_non_empty(candidate.password, "Trojan outbound requires a non-empty authentication secret.")

    security = _normalize_optional_tls_security(candidate.security, protocol_name="Trojan")
    tls = XrayTlsSpec(enabled=True, server_name=candidate.server_name) if security == "tls" else None
    return XrayOutboundSpec(
        tag=tag,
        protocol="trojan",
        protocol_spec=TrojanProtocolSpec(endpoint=endpoint, password=candidate.password),
        transport=_build_transport_spec(candidate),
        tls=tls,
    )


def build_shadowsocks_spec(candidate: CandidateProxy, tag: str) -> XrayOutboundSpec:
    """Build one Shadowsocks spec."""
    _validate_protocol(candidate, tag, expected_protocols={"shadowsocks", "ss"})
    endpoint = _require_endpoint(candidate, protocol_name="Shadowsocks")
    _require_non_empty(candidate.encryption, "Shadowsocks outbound requires a non-empty method.")
    _require_non_empty(candidate.password, "Shadowsocks outbound requires a non-empty authentication secret.")
    return XrayOutboundSpec(
        tag=tag,
        protocol="shadowsocks",
        protocol_spec=ShadowsocksProtocolSpec(
            endpoint=endpoint,
            method=candidate.encryption,
            password=candidate.password,
        ),
    )


def build_vmess_spec(candidate: CandidateProxy, tag: str) -> XrayOutboundSpec:
    """Build one VMess spec."""
    _validate_protocol(candidate, tag, expected_protocol="vmess")
    endpoint = _require_endpoint(candidate, protocol_name="VMess")
    _require_non_empty(candidate.user_id, "VMess outbound requires a non-empty client identifier.")

    security = _normalize_vmess_security(candidate.security)
    tls = XrayTlsSpec(enabled=True, server_name=candidate.server_name) if security == "tls" else None
    return XrayOutboundSpec(
        tag=tag,
        protocol="vmess",
        protocol_spec=VmessProtocolSpec(
            endpoint=endpoint,
            user_id=candidate.user_id,
            security=candidate.encryption or "auto",
            alter_id=_extract_alter_id(candidate.extra),
        ),
        transport=_build_transport_spec(candidate),
        tls=tls,
    )


def build_hysteria2_spec(candidate: CandidateProxy, tag: str) -> XrayOutboundSpec:
    """Build one Xray hysteria spec for a Hysteria2 candidate."""
    _validate_protocol(candidate, tag, expected_protocol="hysteria2")
    endpoint = _require_endpoint(candidate, protocol_name="Hysteria2")
    _require_non_empty(candidate.password, "Hysteria2 outbound requires a non-empty authentication secret.")
    _require_hysteria2_supported_fields(candidate)

    warnings: list[str] = []
    server_name = candidate.server_name
    if not server_name:
        server_name = candidate.address
        warnings.append("Hysteria2 server_name missing; renderer falls back to endpoint address.")

    return XrayOutboundSpec(
        tag=tag,
        protocol="hysteria",
        protocol_spec=HysteriaProtocolSpec(endpoint=endpoint, version=2),
        transport=XrayTransportSpec(
            network="hysteria",
            hysteria=XrayHysteriaTransportSpec(auth=candidate.password, version=2),
        ),
        tls=XrayTlsSpec(
            enabled=True,
            server_name=server_name,
            allow_insecure=_allow_insecure_from_extra(candidate),
            fingerprint=candidate.fingerprint,
        ),
        warnings=warnings,
    )


def _validate_candidate_and_tag(candidate: CandidateProxy, tag: str) -> None:
    if not tag:
        raise ValueError("Xray outbound tag must not be empty.")
    if not candidate.supported:
        raise ValueError(candidate.unsupported_reason or "Candidate is marked unsupported.")


def _validate_protocol(
    candidate: CandidateProxy,
    tag: str,
    *,
    expected_protocol: str | None = None,
    expected_protocols: set[str] | None = None,
) -> None:
    _validate_candidate_and_tag(candidate, tag)
    protocol = candidate.protocol.lower()
    if expected_protocol is not None and protocol != expected_protocol:
        raise ValueError(f"Xray outbound is not supported for protocol '{candidate.protocol}'.")
    if expected_protocols is not None and protocol not in expected_protocols:
        raise ValueError(f"Xray outbound is not supported for protocol '{candidate.protocol}'.")


def _require_endpoint(candidate: CandidateProxy, *, protocol_name: str) -> XrayServerEndpoint:
    if not candidate.address:
        raise ValueError(f"{protocol_name} outbound requires a non-empty address.")
    if candidate.port <= 0:
        raise ValueError(f"{protocol_name} outbound requires port > 0.")
    return XrayServerEndpoint(address=candidate.address, port=candidate.port)


def _require_non_empty(value: str | None, message: str) -> None:
    if not value:
        raise ValueError(message)


def _build_transport_spec(candidate: CandidateProxy) -> XrayTransportSpec:
    network = _normalize_network(candidate.network)
    transport = XrayTransportSpec(network=network)
    if network == "ws":
        transport.ws_path = candidate.path or "/"
        transport.ws_host = candidate.host
    return transport


def _normalize_network(network: str | None) -> str:
    normalized = (network or "tcp").strip().lower()
    if normalized == "grpc":
        raise ValueError("Phase 13B does not support grpc yet.")
    if normalized not in _SUPPORTED_NETWORKS:
        raise ValueError(f"Xray outbound does not support network '{normalized}'.")
    return normalized


def _normalize_vless_security(security: str | None) -> str:
    normalized = (security or "none").strip().lower()
    if normalized not in {"none", "tls", "reality"}:
        raise ValueError(f"VLESS outbound does not support security '{normalized}'.")
    return normalized


def _normalize_optional_tls_security(security: str | None, *, protocol_name: str) -> str:
    normalized = (security or "tls").strip().lower()
    if normalized not in {"none", "tls"}:
        raise ValueError(f"{protocol_name} outbound does not support security '{normalized}'.")
    return normalized


def _normalize_vmess_security(security: str | None) -> str:
    normalized = (security or "none").strip().lower()
    if normalized not in {"none", "tls"}:
        raise ValueError(f"VMess outbound does not support security '{normalized}'.")
    return normalized


def _extract_alter_id(extra: dict[str, object]) -> int:
    for key in ("alter_id", "alterId"):
        value = extra.get(key)
        if value is None:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("VMess outbound requires a valid alterId value.") from exc
    return 0


def _require_hysteria2_supported_fields(candidate: CandidateProxy) -> None:
    if candidate.extra.get("obfs") or candidate.extra.get("obfs-password"):
        raise ValueError("Hysteria2 obfs is not mapped to Xray yet.")
    if candidate.alpn:
        raise ValueError("Hysteria2 alpn is not mapped to Xray yet.")


def _allow_insecure_from_extra(candidate: CandidateProxy) -> bool:
    for key in ("skip_cert_verify", "skip-cert-verify"):
        value = candidate.extra.get(key)
        if isinstance(value, bool):
            return value
    return False


def _normalize_alpn_list(value: str | None) -> list[str]:
    if value is None:
        return []
    values = [item.strip() for item in value.split(",") if item.strip()]
    return values
