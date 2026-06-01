"""Render structured Xray outbound specs into Xray JSON."""

from __future__ import annotations

from scholar_outbound_manager.xray.spec import HysteriaProtocolSpec
from scholar_outbound_manager.xray.spec import ShadowsocksProtocolSpec
from scholar_outbound_manager.xray.spec import TrojanProtocolSpec
from scholar_outbound_manager.xray.spec import VlessProtocolSpec
from scholar_outbound_manager.xray.spec import VmessProtocolSpec
from scholar_outbound_manager.xray.spec import XrayOutboundSpec


def render_xray_outbound(spec: XrayOutboundSpec) -> dict[str, object]:
    """Render one normalized outbound spec to Xray JSON."""
    outbound: dict[str, object] = {
        "tag": spec.tag,
        "protocol": spec.protocol,
        "settings": _render_protocol_settings(spec),
    }
    stream_settings = render_stream_settings(spec)
    if stream_settings:
        outbound["streamSettings"] = stream_settings
    return outbound


def render_stream_settings(spec: XrayOutboundSpec) -> dict[str, object]:
    """Render Xray streamSettings from the normalized spec."""
    if spec.protocol == "shadowsocks":
        return {}

    stream_settings: dict[str, object] = {
        "network": spec.transport.network,
        "security": "reality" if spec.reality is not None else ("tls" if spec.tls and spec.tls.enabled else "none"),
    }

    if spec.tls and spec.tls.enabled:
        tls_settings: dict[str, object] = {}
        if spec.tls.fingerprint:
            tls_settings["fingerprint"] = spec.tls.fingerprint
        if spec.tls.server_name:
            tls_settings["serverName"] = spec.tls.server_name
        if spec.tls.allow_insecure:
            tls_settings["allowInsecure"] = spec.tls.allow_insecure
        elif spec.transport.network == "hysteria":
            tls_settings["allowInsecure"] = False
        if spec.tls.alpn:
            tls_settings["alpn"] = spec.tls.alpn if len(spec.tls.alpn) > 1 else spec.tls.alpn[0]
        stream_settings["tlsSettings"] = tls_settings

    if spec.reality is not None:
        reality_settings: dict[str, object] = {
            "serverName": spec.reality.server_name,
            "fingerprint": spec.reality.fingerprint,
            "publicKey": spec.reality.public_key,
            "shortId": spec.reality.short_id,
            "spiderX": spec.reality.spider_x,
        }
        if spec.reality.alpn:
            reality_settings["alpn"] = spec.reality.alpn if len(spec.reality.alpn) > 1 else spec.reality.alpn[0]
        stream_settings["realitySettings"] = reality_settings

    if spec.transport.network == "ws":
        headers: dict[str, object] = {}
        if spec.transport.ws_host:
            headers["Host"] = spec.transport.ws_host
        stream_settings["wsSettings"] = {
            "path": spec.transport.ws_path or "/",
            "headers": headers,
        }

    if spec.transport.network == "hysteria":
        if spec.transport.hysteria is None or not spec.transport.hysteria.auth:
            raise ValueError("Hysteria transport rendering requires auth.")
        stream_settings["hysteriaSettings"] = {
            "version": spec.transport.hysteria.version,
            "auth": spec.transport.hysteria.auth,
        }

    return stream_settings


def _render_protocol_settings(spec: XrayOutboundSpec) -> dict[str, object]:
    protocol_spec = spec.protocol_spec
    if isinstance(protocol_spec, VlessProtocolSpec):
        user: dict[str, object] = {
            "id": protocol_spec.user_id,
            "encryption": protocol_spec.encryption,
        }
        if protocol_spec.flow is not None:
            user["flow"] = protocol_spec.flow
        return {
            "vnext": [
                {
                    "address": protocol_spec.endpoint.address,
                    "port": protocol_spec.endpoint.port,
                    "users": [user],
                }
            ]
        }
    if isinstance(protocol_spec, TrojanProtocolSpec):
        return {
            "servers": [
                {
                    "address": protocol_spec.endpoint.address,
                    "port": protocol_spec.endpoint.port,
                    "password": protocol_spec.password,
                }
            ]
        }
    if isinstance(protocol_spec, ShadowsocksProtocolSpec):
        return {
            "servers": [
                {
                    "address": protocol_spec.endpoint.address,
                    "port": protocol_spec.endpoint.port,
                    "method": protocol_spec.method,
                    "password": protocol_spec.password,
                }
            ]
        }
    if isinstance(protocol_spec, VmessProtocolSpec):
        return {
            "vnext": [
                {
                    "address": protocol_spec.endpoint.address,
                    "port": protocol_spec.endpoint.port,
                    "users": [
                        {
                            "id": protocol_spec.user_id,
                            "alterId": protocol_spec.alter_id,
                            "security": protocol_spec.security,
                        }
                    ],
                }
            ]
        }
    if isinstance(protocol_spec, HysteriaProtocolSpec):
        return {
            "version": protocol_spec.version,
            "address": protocol_spec.endpoint.address,
            "port": protocol_spec.endpoint.port,
        }
    raise ValueError(f"Unsupported Xray protocol spec type '{type(protocol_spec).__name__}'.")
