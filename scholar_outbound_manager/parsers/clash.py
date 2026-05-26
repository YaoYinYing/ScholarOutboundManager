"""Clash YAML subscription parsing support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from scholar_outbound_manager.models import CandidateProxy


@dataclass(frozen=True)
class ClashParseSummary:
    """Summarize one Clash YAML parse pass."""

    proxy_count: int
    parsed_count: int
    unsupported_count: int
    ignored_url_field_count: int


def looks_like_clash_yaml(content: str) -> bool:
    """Return whether content is a Clash-style YAML mapping with a proxies list."""
    try:
        loaded = yaml.safe_load(content)
    except yaml.YAMLError:
        return False
    return isinstance(loaded, dict) and isinstance(loaded.get("proxies"), list)


def parse_clash_yaml_subscription(
    content: str,
    source_name: str,
) -> tuple[list[CandidateProxy], ClashParseSummary]:
    """Parse the top-level Clash proxies list into candidate models."""
    loaded = yaml.safe_load(content)
    if not isinstance(loaded, dict):
        raise ValueError("Clash YAML subscription root must be a mapping.")

    proxies = loaded.get("proxies")
    if not isinstance(proxies, list):
        raise ValueError("Clash YAML subscription must contain a top-level proxies list.")

    ignored_url_field_count = _count_url_fields_outside_proxies(loaded)
    candidates = [_parse_proxy_item(item, index, source_name) for index, item in enumerate(proxies)]
    unsupported_count = sum(1 for candidate in candidates if not candidate.supported)
    summary = ClashParseSummary(
        proxy_count=len(proxies),
        parsed_count=len(candidates),
        unsupported_count=unsupported_count,
        ignored_url_field_count=ignored_url_field_count,
    )
    return candidates, summary


def _count_url_fields_outside_proxies(document: dict[str, Any]) -> int:
    """Count ignored url fields without descending into the top-level proxies list."""
    return sum(
        _count_url_fields(value)
        for key, value in document.items()
        if key != "proxies"
    )


def _count_url_fields(value: Any) -> int:
    """Count nested mapping keys named url."""
    if isinstance(value, dict):
        count = 1 if "url" in value else 0
        return count + sum(_count_url_fields(item) for item in value.values())
    if isinstance(value, list):
        return sum(_count_url_fields(item) for item in value)
    return 0


def _parse_proxy_item(item: Any, index: int, source_name: str) -> CandidateProxy:
    """Parse one Clash proxy entry into a candidate model."""
    if not isinstance(item, dict):
        raise ValueError(f"Clash proxy entry at index {index} must be a mapping.")

    proxy_type = _string(item.get("type")).lower()
    raw_name = _string(item.get("name")) or f"unnamed-{proxy_type or 'proxy'}"
    if proxy_type == "vless":
        return _parse_vless_proxy(item, source_name, raw_name)
    if proxy_type == "trojan":
        return _parse_trojan_proxy(item, source_name, raw_name)
    if proxy_type == "ss":
        return _parse_shadowsocks_proxy(item, source_name, raw_name)
    if proxy_type == "vmess":
        return _parse_vmess_proxy(item, source_name, raw_name)
    return CandidateProxy(
        source_name=source_name,
        raw_name=raw_name,
        protocol=proxy_type or "unknown",
        address=_string(item.get("server")),
        port=_int(item.get("port")),
        raw_uri=None,
        supported=False,
        unsupported_reason=f"Clash proxy type '{proxy_type or 'unknown'}' is not supported yet.",
        extra={"clash_type": proxy_type or "unknown"},
    )


def _parse_vless_proxy(item: dict[str, Any], source_name: str, raw_name: str) -> CandidateProxy:
    """Parse one Clash VLESS node."""
    reality_opts = _mapping(item.get("reality-opts"))
    ws_opts = _mapping(item.get("ws-opts"))
    grpc_opts = _mapping(item.get("grpc-opts"))
    tls_enabled = _bool(item.get("tls"))
    network = _string(item.get("network")) or "tcp"
    server_name = _first_non_empty(item.get("servername"), item.get("sni"))

    unsupported_reasons: list[str] = []
    missing_fields = _missing_required_fields(item, ("server", "port", "uuid"))
    if missing_fields:
        unsupported_reasons.append(f"Missing required VLESS fields: {', '.join(missing_fields)}.")

    security: str | None = None
    public_key = _string(reality_opts.get("public-key"))
    short_id = _string(reality_opts.get("short-id"))
    if reality_opts:
        security = "reality"
        if not public_key:
            unsupported_reasons.append("Reality node is missing public-key.")
        if not server_name:
            unsupported_reasons.append("Reality node is missing server_name.")
    elif tls_enabled:
        security = "tls"

    if network == "grpc":
        unsupported_reasons.append("Clash VLESS grpc nodes are parsed but not yet supported by the Xray runtime builder.")
    elif network not in {"tcp", "ws"}:
        unsupported_reasons.append(f"Clash VLESS network '{network}' is not supported by the Xray runtime builder.")

    ws_path, ws_host = _ws_values(ws_opts)
    extra = {
        "clash_type": "vless",
        "tls": tls_enabled,
        "skip_cert_verify": _bool_or_none(item.get("skip-cert-verify")),
        "grpc_service_name": _string(grpc_opts.get("grpc-service-name")),
        "runtime_supported_by": ["xray"] if not unsupported_reasons else [],
    }
    return CandidateProxy(
        source_name=source_name,
        raw_name=raw_name,
        protocol="vless",
        address=_string(item.get("server")),
        port=_int(item.get("port")),
        user_id=_string(item.get("uuid")) or None,
        flow=_string(item.get("flow")) or None,
        network=network,
        security=security,
        server_name=server_name,
        fingerprint=_string(item.get("client-fingerprint")) or None,
        public_key=public_key or None,
        short_id=short_id or None,
        path=ws_path,
        host=ws_host,
        raw_uri=None,
        supported=not unsupported_reasons,
        unsupported_reason=" ".join(unsupported_reasons) or None,
        extra={key: value for key, value in extra.items() if value is not None},
    )


def _parse_trojan_proxy(item: dict[str, Any], source_name: str, raw_name: str) -> CandidateProxy:
    """Parse one Clash Trojan node."""
    ws_path, ws_host = _ws_values(_mapping(item.get("ws-opts")))
    unsupported_reasons: list[str] = []
    if missing_fields := _missing_required_fields(item, ("server", "port", "password")):
        unsupported_reasons.insert(0, f"Missing required Trojan fields: {', '.join(missing_fields)}.")
    network = _string(item.get("network")) or "tcp"
    if network not in {"tcp", "ws"}:
        unsupported_reasons.append(f"Clash Trojan network '{network}' is not supported by the Xray runtime builder.")
    security = "tls" if _bool(item.get("tls")) else None
    return CandidateProxy(
        source_name=source_name,
        raw_name=raw_name,
        protocol="trojan",
        address=_string(item.get("server")),
        port=_int(item.get("port")),
        password=_string(item.get("password")) or None,
        network=network,
        security=security,
        server_name=_first_non_empty(item.get("sni"), item.get("servername")),
        path=ws_path,
        host=ws_host,
        raw_uri=None,
        supported=not unsupported_reasons,
        unsupported_reason=" ".join(unsupported_reasons) or None,
        extra={
            "clash_type": "trojan",
            "tls": _bool(item.get("tls")),
            "skip_cert_verify": _bool_or_none(item.get("skip-cert-verify")),
            "runtime_supported_by": ["xray"] if not unsupported_reasons else [],
        },
    )


def _parse_shadowsocks_proxy(item: dict[str, Any], source_name: str, raw_name: str) -> CandidateProxy:
    """Parse one Clash Shadowsocks node."""
    unsupported_reasons: list[str] = []
    if missing_fields := _missing_required_fields(item, ("server", "port", "cipher", "password")):
        unsupported_reasons.insert(0, f"Missing required Shadowsocks fields: {', '.join(missing_fields)}.")
    return CandidateProxy(
        source_name=source_name,
        raw_name=raw_name,
        protocol="shadowsocks",
        address=_string(item.get("server")),
        port=_int(item.get("port")),
        password=_string(item.get("password")) or None,
        encryption=_string(item.get("cipher")) or None,
        raw_uri=None,
        supported=not unsupported_reasons,
        unsupported_reason=" ".join(unsupported_reasons) or None,
        extra={
            "clash_type": "ss",
            "udp": _bool_or_none(item.get("udp")),
            "runtime_supported_by": ["xray"] if not unsupported_reasons else [],
        },
    )


def _parse_vmess_proxy(item: dict[str, Any], source_name: str, raw_name: str) -> CandidateProxy:
    """Parse one Clash VMess node."""
    ws_path, ws_host = _ws_values(_mapping(item.get("ws-opts")))
    unsupported_reasons: list[str] = []
    if missing_fields := _missing_required_fields(item, ("server", "port", "uuid")):
        unsupported_reasons.insert(0, f"Missing required VMess fields: {', '.join(missing_fields)}.")
    network = _string(item.get("network")) or "tcp"
    if network == "grpc":
        unsupported_reasons.append("Clash VMess grpc nodes are parsed but not yet supported by the Xray runtime builder.")
    elif network not in {"tcp", "ws"}:
        unsupported_reasons.append(f"Clash VMess network '{network}' is not supported by the Xray runtime builder.")
    return CandidateProxy(
        source_name=source_name,
        raw_name=raw_name,
        protocol="vmess",
        address=_string(item.get("server")),
        port=_int(item.get("port")),
        user_id=_string(item.get("uuid")) or None,
        encryption=_string(item.get("cipher")) or None,
        network=network,
        security="tls" if _bool(item.get("tls")) else None,
        server_name=_first_non_empty(item.get("servername"), item.get("sni")),
        path=ws_path,
        host=ws_host,
        raw_uri=None,
        supported=not unsupported_reasons,
        unsupported_reason=" ".join(unsupported_reasons) or None,
        extra={
            "clash_type": "vmess",
            "alter_id": item.get("alterId"),
            "runtime_supported_by": ["xray"] if not unsupported_reasons else [],
        },
    )


def _missing_required_fields(item: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    """Collect missing required fields from a Clash proxy item."""
    missing: list[str] = []
    for key in keys:
        value = item.get(key)
        if key == "port":
            if _int(value) <= 0:
                missing.append(key)
        elif not _string(value):
            missing.append(key)
    return missing


def _ws_values(ws_opts: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extract WebSocket path and host values."""
    path = _string(ws_opts.get("path")) or None
    headers = _mapping(ws_opts.get("headers"))
    host = _first_non_empty(headers.get("Host"), headers.get("host"))
    return path, host


def _mapping(value: Any) -> dict[str, Any]:
    """Return a mapping value or an empty mapping."""
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str:
    """Normalize a value into a stripped string."""
    if value is None:
        return ""
    return str(value).strip()


def _int(value: Any) -> int:
    """Normalize a numeric field into an integer or zero."""
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return normalized if normalized > 0 else 0


def _bool(value: Any) -> bool:
    """Normalize a boolean-like value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _bool_or_none(value: Any) -> bool | None:
    """Normalize a boolean-like value while preserving absence."""
    if value is None:
        return None
    return _bool(value)


def _first_non_empty(*values: Any) -> str | None:
    """Return the first non-empty stringified value."""
    for value in values:
        normalized = _string(value)
        if normalized:
            return normalized
    return None
