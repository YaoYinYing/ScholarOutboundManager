"""Core data models for subscriptions, probes, and generated outputs."""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field


@dataclass(slots=True)
class SubscriptionSource:
    """Define one subscription source entry."""

    name: str
    url: str
    format: str = "auto"
    enabled: bool = True
    headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Convert the model to a plain dictionary."""
        return asdict(self)


@dataclass(slots=True)
class FilterConfig:
    """Define candidate filtering rules."""

    include_keywords: list[str]
    exclude_keywords: list[str]
    deprioritize_keywords: list[str]

    def to_dict(self) -> dict[str, object]:
        """Convert the model to a plain dictionary."""
        return asdict(self)


@dataclass(slots=True)
class ProbeConfig:
    """Define Scholar probing behavior."""

    timeout_seconds: int
    concurrency: int
    cache_ttl_hours: int
    failure_backoff_hours: int
    allow_network_probe: bool

    def to_dict(self) -> dict[str, object]:
        """Convert the model to a plain dictionary."""
        return asdict(self)


@dataclass(slots=True)
class XrayConfig:
    """Define local Xray invocation settings."""

    binary_path: str
    runtime_dir: str
    local_socks_host: str
    local_socks_port: int

    def to_dict(self) -> dict[str, object]:
        """Convert the model to a plain dictionary."""
        return asdict(self)


@dataclass(slots=True)
class OutputConfig:
    """Define generated output locations."""

    outbounds_path: str
    routes_path: str
    manifest_path: str
    history_dir: str

    def to_dict(self) -> dict[str, object]:
        """Convert the model to a plain dictionary."""
        return asdict(self)


@dataclass(slots=True)
class GenerationConfig:
    """Define generated node and retention constraints."""

    tag_prefix: str
    max_passed_nodes: int
    fallback_blackhole_tag: str
    previous_output_max_age_hours: int

    def to_dict(self) -> dict[str, object]:
        """Convert the model to a plain dictionary."""
        return asdict(self)


@dataclass(slots=True)
class RoutingConfig:
    """Define routing behavior for generated Scholar traffic."""

    mode: str
    inbound_tags: list[str]
    fail_closed: bool

    def to_dict(self) -> dict[str, object]:
        """Convert the model to a plain dictionary."""
        return asdict(self)


@dataclass(slots=True)
class AppConfig:
    """Define the application configuration contract."""

    subscriptions: list[SubscriptionSource]
    filters: FilterConfig
    probe: ProbeConfig
    xray: XrayConfig
    output: OutputConfig
    generation: GenerationConfig
    routing: RoutingConfig

    def to_dict(self) -> dict[str, object]:
        """Convert the model to a plain dictionary."""
        return asdict(self)


@dataclass(slots=True)
class CandidateProxy:
    """Represent one parsed proxy candidate."""

    source_name: str
    raw_name: str
    protocol: str
    address: str
    port: int
    user_id: str | None = None
    password: str | None = None
    encryption: str | None = None
    flow: str | None = None
    network: str | None = None
    security: str | None = None
    server_name: str | None = None
    fingerprint: str | None = None
    public_key: str | None = None
    short_id: str | None = None
    alpn: str | None = None
    path: str | None = None
    host: str | None = None
    extra: dict[str, object] = field(default_factory=dict)
    raw_uri: str | None = None
    supported: bool = True
    unsupported_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Convert the model to a plain dictionary."""
        return asdict(self)


@dataclass(slots=True)
class ProbeResult:
    """Represent one Scholar accessibility probe result."""

    candidate_id: str
    home_status: int | None
    query_status: int | None
    blocked: bool
    timeout: bool
    error: str | None
    failure_markers: list[str]
    latency_ms: int | None
    checked_at: str

    def to_dict(self) -> dict[str, object]:
        """Convert the model to a plain dictionary."""
        return asdict(self)


@dataclass(slots=True)
class GeneratedNode:
    """Represent one generated outbound with its evidence."""

    tag: str
    candidate: CandidateProxy
    outbound: dict[str, object]
    probe: ProbeResult | None

    def to_dict(self) -> dict[str, object]:
        """Convert the model to a plain dictionary."""
        return asdict(self)
