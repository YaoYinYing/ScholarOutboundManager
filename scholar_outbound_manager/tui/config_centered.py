"""Config-centered TUI helpers for template creation and summary extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scholar_outbound_manager.tui.config_editor import build_redacted_config_preview
from scholar_outbound_manager.tui.path_resolver import DEFAULT_USER_DATA_DIR
from scholar_outbound_manager.tui.path_resolver import load_raw_config_mapping
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths


DEFAULT_SERVICE_NAME = "scholar-outbound-sidecar.service"
DEFAULT_USER_AGENT = "Clash.Meta"
DEFAULT_XRAY_BINARY_PATH = ".runtime/xray/xray"


@dataclass(slots=True, frozen=True)
class FirstRunWizardState:
    """Describe the initial config-creation flow."""

    active: bool
    config_path: str
    user_data_dir: str
    xray_binary_path: str
    subscription_url_configured: bool
    step_titles: tuple[str, ...]
    redacted_preview: str


@dataclass(slots=True, frozen=True)
class ConfigCenteredSummary:
    """Review-safe config-centered summary for the TUI."""

    config_path: str
    user_data_dir: str
    subscription_url_configured: bool
    subscription_user_agent: str
    xray_binary_path: str
    route_entries: list[dict[str, object]]
    fail_closed: bool
    experimental_hysteria2: bool
    service_name: str
    selected_ports: list[int]


def build_first_run_wizard_state(config_path: str | Path) -> FirstRunWizardState:
    """Build the first-run wizard state for a missing config."""
    preview = render_config_template(config_path)
    return FirstRunWizardState(
        active=not Path(config_path).exists(),
        config_path=str(Path(config_path)),
        user_data_dir=DEFAULT_USER_DATA_DIR,
        xray_binary_path=DEFAULT_XRAY_BINARY_PATH,
        subscription_url_configured=False,
        step_titles=("Config path", "Subscription", "User data dir", "Runtime", "Save"),
        redacted_preview=build_redacted_config_preview(preview),
    )


def write_config_template(
    config_path: str | Path,
    *,
    subscription_url: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
    user_data_dir: str = DEFAULT_USER_DATA_DIR,
    xray_binary_path: str = DEFAULT_XRAY_BINARY_PATH,
) -> Path:
    """Write one safe starter config compatible with existing CLI modules."""
    target = Path(config_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_config_template(
        target,
        subscription_url=subscription_url,
        user_agent=user_agent,
        user_data_dir=user_data_dir,
        xray_binary_path=xray_binary_path,
    )
    temp_path = target.with_suffix(target.suffix + ".tmp")
    temp_path.write_text(rendered, encoding="utf-8")
    temp_path.replace(target)
    return target


def render_config_template(
    config_path: str | Path,
    *,
    subscription_url: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
    user_data_dir: str = DEFAULT_USER_DATA_DIR,
    xray_binary_path: str = DEFAULT_XRAY_BINARY_PATH,
) -> str:
    """Render one starter config template."""
    del config_path
    payload: dict[str, Any] = {
        "schema_version": 1,
        "subscription": {
            "url": subscription_url,
            "user_agent": user_agent,
        },
        "subscriptions": [
            {
                "name": "primary",
                "url": subscription_url,
                "format": "auto",
                "enabled": True,
                "headers": {
                    "User-Agent": user_agent,
                },
            }
        ],
        "user_data_dir": user_data_dir,
        "filters": {
            "include_keywords": [],
            "exclude_keywords": ["warp", "ipv6"],
            "deprioritize_keywords": [],
        },
        "probe": {
            "query": "ppr",
            "timeout_seconds": 15,
            "concurrency": 4,
            "cache_ttl_hours": 24,
            "failure_backoff_hours": 48,
            "allow_network_probe": True,
        },
        "xray": {
            "binary_path": xray_binary_path,
            "runtime_dir": ".runtime",
            "local_socks_host": "127.0.0.1",
            "local_socks_port": 19080,
        },
        "sidecar": {
            "listen_host": "127.0.0.1",
            "service_name": DEFAULT_SERVICE_NAME,
        },
        "route": {
            "mode": "single",
            "entries": [
                {
                    "name": "Scholar",
                    "candidate_id": None,
                    "listen_host": "127.0.0.1",
                    "listen_port": 19080,
                    "enabled": True,
                }
            ],
        },
        "output": {
            "outbounds_path": "generated/google_scholar_outbounds.json",
            "routes_path": "generated/google_scholar_routes.json",
            "manifest_path": "generated/google_scholar_manifest.json",
            "history_dir": f"{user_data_dir}/history",
        },
        "generation": {
            "tag_prefix": "google-scholar-node-",
            "max_passed_nodes": 3,
            "fallback_blackhole_tag": "google-scholar-unavailable",
            "previous_output_max_age_hours": 168,
        },
        "routing": {
            "mode": "dedicated_inbound",
            "inbound_tags": ["google-scholar-in"],
            "fail_closed": True,
        },
        "experimental": {
            "enable_hysteria2": False,
        },
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def summarize_config_centered_state(config_path: str | Path) -> ConfigCenteredSummary:
    """Read raw config YAML and return one review-safe summary."""
    raw = load_raw_config_mapping(config_path)
    paths = resolve_user_data_paths(config_path)
    subscription = raw.get("subscription")
    subscriptions = raw.get("subscriptions")
    subscription_url_configured = False
    subscription_user_agent = DEFAULT_USER_AGENT
    if isinstance(subscription, dict):
        subscription_url_configured = isinstance(subscription.get("url"), str) and bool(str(subscription.get("url")).strip())
        if isinstance(subscription.get("user_agent"), str) and str(subscription.get("user_agent")).strip():
            subscription_user_agent = str(subscription.get("user_agent"))
    if not subscription_url_configured and isinstance(subscriptions, list) and subscriptions:
        first = subscriptions[0]
        if isinstance(first, dict):
            subscription_url_configured = isinstance(first.get("url"), str) and bool(str(first.get("url")).strip())
            headers = first.get("headers")
            if isinstance(headers, dict) and isinstance(headers.get("User-Agent"), str) and str(headers.get("User-Agent")).strip():
                subscription_user_agent = str(headers["User-Agent"])

    xray = raw.get("xray")
    xray_binary_path = DEFAULT_XRAY_BINARY_PATH
    if isinstance(xray, dict) and isinstance(xray.get("binary_path"), str) and str(xray.get("binary_path")).strip():
        xray_binary_path = str(xray["binary_path"])

    routing = raw.get("routing")
    fail_closed = True
    if isinstance(routing, dict) and isinstance(routing.get("fail_closed"), bool):
        fail_closed = bool(routing["fail_closed"])

    experimental = raw.get("experimental")
    experimental_hysteria2 = False
    if isinstance(experimental, dict) and isinstance(experimental.get("enable_hysteria2"), bool):
        experimental_hysteria2 = bool(experimental["enable_hysteria2"])

    sidecar = raw.get("sidecar")
    service_name = DEFAULT_SERVICE_NAME
    if isinstance(sidecar, dict) and isinstance(sidecar.get("service_name"), str) and str(sidecar.get("service_name")).strip():
        service_name = str(sidecar["service_name"])

    route_entries = _extract_route_entries(raw)
    selected_ports = [
        int(entry["listen_port"])
        for entry in route_entries
        if isinstance(entry.get("listen_port"), int)
    ]
    return ConfigCenteredSummary(
        config_path=str(Path(config_path)),
        user_data_dir=str(paths.root),
        subscription_url_configured=subscription_url_configured,
        subscription_user_agent=subscription_user_agent,
        xray_binary_path=xray_binary_path,
        route_entries=route_entries,
        fail_closed=fail_closed,
        experimental_hysteria2=experimental_hysteria2,
        service_name=service_name,
        selected_ports=selected_ports,
    )


def _extract_route_entries(raw: dict[str, Any]) -> list[dict[str, object]]:
    route = raw.get("route")
    if isinstance(route, dict) and isinstance(route.get("entries"), list):
        rows: list[dict[str, object]] = []
        for index, entry in enumerate(route["entries"]):
            if not isinstance(entry, dict):
                continue
            rows.append(
                {
                    "name": str(entry.get("name") or f"Route {index + 1}"),
                    "candidate_id": entry.get("candidate_id"),
                    "listen_host": str(entry.get("listen_host") or "127.0.0.1"),
                    "listen_port": _coerce_int(entry.get("listen_port"), default=19080 + index),
                    "enabled": bool(entry.get("enabled", True)),
                }
            )
        if rows:
            return rows

    xray = raw.get("xray")
    listen_host = "127.0.0.1"
    listen_port = 19080
    if isinstance(xray, dict):
        if isinstance(xray.get("local_socks_host"), str) and str(xray.get("local_socks_host")).strip():
            listen_host = str(xray["local_socks_host"])
        listen_port = _coerce_int(xray.get("local_socks_port"), default=19080)
    return [
        {
            "name": "Scholar",
            "candidate_id": None,
            "listen_host": listen_host,
            "listen_port": listen_port,
            "enabled": True,
        }
    ]


def _coerce_int(value: object, *, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default
