"""Configuration loading and validation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scholar_outbound_manager.models import AppConfig
from scholar_outbound_manager.models import FilterConfig
from scholar_outbound_manager.models import GenerationConfig
from scholar_outbound_manager.models import OutputConfig
from scholar_outbound_manager.models import ProbeConfig
from scholar_outbound_manager.models import RoutingConfig
from scholar_outbound_manager.models import SubscriptionSource
from scholar_outbound_manager.models import XrayConfig


class ConfigError(ValueError):
    """Raise when configuration input is missing or invalid."""


def load_config(path: str | Path) -> AppConfig:
    """Load YAML configuration into an application dataclass tree."""
    config_path = Path(path)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            raw_data = yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigError(f"Could not read configuration file: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse YAML configuration: {config_path}") from exc

    if not isinstance(raw_data, dict):
        raise ConfigError("Configuration root must be a mapping.")

    _normalize_legacy_tui_keys(raw_data)

    subscriptions_raw = _require_list(raw_data, "subscriptions")
    filters_raw = _require_mapping(raw_data, "filters")
    probe_raw = _require_mapping(raw_data, "probe")
    xray_raw = _require_mapping(raw_data, "xray")
    output_raw = _require_mapping(raw_data, "output")
    generation_raw = _require_mapping(raw_data, "generation")
    routing_raw = _require_mapping(raw_data, "routing")
    subscriptions = [
        SubscriptionSource(
            name=_require_str(item, "name", context=f"subscriptions[{index}]"),
            url=_require_str(item, "url", context=f"subscriptions[{index}]"),
            format=_optional_str(item, "format", default="auto", context=f"subscriptions[{index}]"),
            enabled=_optional_bool(item, "enabled", default=True, context=f"subscriptions[{index}]"),
            headers=_require_str_mapping(item, "headers", context=f"subscriptions[{index}]"),
        )
        for index, item in enumerate(subscriptions_raw)
    ]

    return AppConfig(
        subscriptions=subscriptions,
        filters=FilterConfig(
            include_keywords=_require_str_list(filters_raw, "include_keywords", "filters"),
            exclude_keywords=_require_str_list(filters_raw, "exclude_keywords", "filters"),
            deprioritize_keywords=_require_str_list(
                filters_raw,
                "deprioritize_keywords",
                "filters",
            ),
        ),
        probe=ProbeConfig(
            timeout_seconds=_require_int(probe_raw, "timeout_seconds", "probe"),
            concurrency=_require_int(probe_raw, "concurrency", "probe"),
            cache_ttl_hours=_require_int(probe_raw, "cache_ttl_hours", "probe"),
            failure_backoff_hours=_require_int(
                probe_raw,
                "failure_backoff_hours",
                "probe",
            ),
            allow_network_probe=_require_bool(probe_raw, "allow_network_probe", "probe"),
        ),
        xray=XrayConfig(
            binary_path=_require_str(xray_raw, "binary_path", "xray"),
            runtime_dir=_require_str(xray_raw, "runtime_dir", "xray"),
            local_socks_host=_require_str(xray_raw, "local_socks_host", "xray"),
            local_socks_port=_require_int(xray_raw, "local_socks_port", "xray"),
        ),
        output=OutputConfig(
            outbounds_path=_require_str(output_raw, "outbounds_path", "output"),
            routes_path=_require_str(output_raw, "routes_path", "output"),
            manifest_path=_require_str(output_raw, "manifest_path", "output"),
            history_dir=_require_str(output_raw, "history_dir", "output"),
        ),
        generation=GenerationConfig(
            tag_prefix=_require_str(generation_raw, "tag_prefix", "generation"),
            max_passed_nodes=_require_int(
                generation_raw,
                "max_passed_nodes",
                "generation",
            ),
            fallback_blackhole_tag=_require_str(
                generation_raw,
                "fallback_blackhole_tag",
                "generation",
            ),
            previous_output_max_age_hours=_require_int(
                generation_raw,
                "previous_output_max_age_hours",
                "generation",
            ),
        ),
        routing=RoutingConfig(
            mode=_require_str(routing_raw, "mode", "routing"),
            inbound_tags=_require_str_list(routing_raw, "inbound_tags", "routing"),
            fail_closed=_require_bool(routing_raw, "fail_closed", "routing"),
        ),
    )


def _normalize_legacy_tui_keys(raw_data: dict[str, Any]) -> None:
    """Fill compatibility keys that the older core config loader still expects."""
    if "subscriptions" not in raw_data and isinstance(raw_data.get("subscription"), dict):
        subscription = raw_data["subscription"]
        headers: dict[str, str] = {}
        user_agent = subscription.get("user_agent")
        if isinstance(user_agent, str) and user_agent.strip():
            headers["User-Agent"] = user_agent
        raw_data["subscriptions"] = [
            {
                "name": "primary",
                "url": subscription.get("url", ""),
                "format": "auto",
                "enabled": True,
                "headers": headers,
            }
        ]


def _require_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a required mapping value."""
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"Field '{key}' must be a mapping.")
    return value


def _require_list(data: dict[str, Any], key: str) -> list[Any]:
    """Return a required list value."""
    value = data.get(key)
    if not isinstance(value, list):
        raise ConfigError(f"Field '{key}' must be a list.")
    return value


def _require_str(data: dict[str, Any], key: str, context: str) -> str:
    """Return a required string field."""
    value = data.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"Field '{context}.{key}' must be a string.")
    return value


def _optional_str(data: dict[str, Any], key: str, default: str, context: str) -> str:
    """Return an optional string field with default."""
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, str):
        raise ConfigError(f"Field '{context}.{key}' must be a string.")
    return value


def _require_int(data: dict[str, Any], key: str, context: str) -> int:
    """Return a required integer field."""
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"Field '{context}.{key}' must be an integer.")
    return value


def _require_bool(data: dict[str, Any], key: str, context: str) -> bool:
    """Return a required boolean field."""
    value = data.get(key)
    if not isinstance(value, bool):
        raise ConfigError(f"Field '{context}.{key}' must be a boolean.")
    return value


def _optional_bool(data: dict[str, Any], key: str, default: bool, context: str) -> bool:
    """Return an optional boolean field with default."""
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise ConfigError(f"Field '{context}.{key}' must be a boolean.")
    return value


def _require_str_list(data: dict[str, Any], key: str, context: str) -> list[str]:
    """Return a required list of strings."""
    value = data.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ConfigError(f"Field '{context}.{key}' must be a list of strings.")
    return list(value)


def _require_str_mapping(data: dict[str, Any], key: str, context: str) -> dict[str, str]:
    """Return a required mapping of string keys and values."""
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"Field '{context}.{key}' must be a mapping of strings.")
    result: dict[str, str] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not isinstance(item_value, str):
            raise ConfigError(f"Field '{context}.{key}' must be a mapping of strings.")
        result[item_key] = item_value
    return result
