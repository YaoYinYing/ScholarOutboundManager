"""Structured Xray outbound specification models."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TypeAlias


@dataclass(slots=True)
class XrayServerEndpoint:
    """Represent one remote server endpoint."""

    address: str
    port: int

    def __post_init__(self) -> None:
        if not self.address:
            raise ValueError("Xray endpoint address must not be empty.")
        if not 1 <= self.port <= 65535:
            raise ValueError("Xray endpoint port must be within 1..65535.")


@dataclass(slots=True)
class XrayTlsSpec:
    """Represent Xray TLS stream settings."""

    enabled: bool = False
    server_name: str | None = None
    allow_insecure: bool = False
    fingerprint: str | None = None
    alpn: list[str] = field(default_factory=list)


@dataclass(slots=True)
class XrayRealitySpec:
    """Represent Xray Reality stream settings."""

    server_name: str
    public_key: str
    short_id: str = ""
    fingerprint: str = "chrome"
    spider_x: str = "/"
    alpn: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.server_name:
            raise ValueError("Xray Reality server_name must not be empty.")
        if not self.public_key:
            raise ValueError("Xray Reality public_key must not be empty.")


@dataclass(slots=True)
class XrayHysteriaTransportSpec:
    """Represent Xray hysteria transport settings."""

    auth: str
    version: int = 2

    def __post_init__(self) -> None:
        if not self.auth:
            raise ValueError("Xray hysteria transport auth must not be empty.")
        if self.version != 2:
            raise ValueError("This phase only supports Xray hysteria transport version 2.")


@dataclass(slots=True)
class XrayTransportSpec:
    """Represent Xray transport-level settings."""

    network: str = "tcp"
    ws_path: str | None = None
    ws_host: str | None = None
    grpc_service_name: str | None = None
    hysteria: XrayHysteriaTransportSpec | None = None


@dataclass(slots=True)
class VlessProtocolSpec:
    """Represent a VLESS outbound protocol payload."""

    endpoint: XrayServerEndpoint
    user_id: str
    encryption: str = "none"
    flow: str | None = None

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("VLESS protocol spec requires a non-empty user_id.")


@dataclass(slots=True)
class VmessProtocolSpec:
    """Represent a VMess outbound protocol payload."""

    endpoint: XrayServerEndpoint
    user_id: str
    security: str = "auto"
    alter_id: int = 0

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("VMess protocol spec requires a non-empty user_id.")
        if self.alter_id < 0:
            raise ValueError("VMess protocol spec alter_id must not be negative.")


@dataclass(slots=True)
class TrojanProtocolSpec:
    """Represent a Trojan outbound protocol payload."""

    endpoint: XrayServerEndpoint
    password: str

    def __post_init__(self) -> None:
        if not self.password:
            raise ValueError("Trojan protocol spec requires a non-empty password.")


@dataclass(slots=True)
class ShadowsocksProtocolSpec:
    """Represent a Shadowsocks outbound protocol payload."""

    endpoint: XrayServerEndpoint
    method: str
    password: str

    def __post_init__(self) -> None:
        if not self.method:
            raise ValueError("Shadowsocks protocol spec requires a non-empty method.")
        if not self.password:
            raise ValueError("Shadowsocks protocol spec requires a non-empty password.")


@dataclass(slots=True)
class HysteriaProtocolSpec:
    """Represent a Xray hysteria outbound protocol payload."""

    endpoint: XrayServerEndpoint
    version: int = 2

    def __post_init__(self) -> None:
        if self.version != 2:
            raise ValueError("This phase only supports Xray hysteria outbound version 2.")


XrayProtocolSpec: TypeAlias = (
    VlessProtocolSpec
    | VmessProtocolSpec
    | TrojanProtocolSpec
    | ShadowsocksProtocolSpec
    | HysteriaProtocolSpec
)


@dataclass(slots=True)
class XrayOutboundSpec:
    """Represent one normalized Xray outbound specification."""

    tag: str
    protocol: str
    protocol_spec: XrayProtocolSpec
    transport: XrayTransportSpec = field(default_factory=XrayTransportSpec)
    tls: XrayTlsSpec | None = None
    reality: XrayRealitySpec | None = None
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tag:
            raise ValueError("Xray outbound tag must not be empty.")
        if not self.protocol:
            raise ValueError("Xray outbound protocol must not be empty.")
