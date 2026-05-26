"""Local runtime environment inspection helpers."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


_PROXY_ENV_VAR_NAMES = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]


@dataclass(slots=True)
class RuntimeEnvironmentInspection:
    """Represent a local-only probe environment inspection."""

    platform: str
    system_proxy_detected: bool
    proxy_env_vars: list[str]
    tun_hint_detected: bool
    trust_level: str
    warnings: list[str]


def inspect_runtime_environment() -> RuntimeEnvironmentInspection:
    """Inspect local environment hints without accessing the network."""
    platform_name = sys.platform
    proxy_env_vars = [
        name for name in _PROXY_ENV_VAR_NAMES if os.environ.get(name)
    ]
    system_proxy_detected = bool(proxy_env_vars)

    tun_hint_detected = False
    warnings: list[str] = []
    trust_level = "vps_candidate"

    if platform_name == "darwin":
        tun_hint_detected = True
        trust_level = "development_only"
        warnings.append(
            "macOS/TUN routing cannot be excluded from Python alone. Run final Scholar probe on VPS."
        )
    elif system_proxy_detected:
        trust_level = "development_only"

    if system_proxy_detected:
        warnings.append(
            "Proxy environment variables are present. Local probe results should be treated as development-only."
        )

    return RuntimeEnvironmentInspection(
        platform=platform_name,
        system_proxy_detected=system_proxy_detected,
        proxy_env_vars=proxy_env_vars,
        tun_hint_detected=tun_hint_detected,
        trust_level=trust_level,
        warnings=warnings,
    )


def format_runtime_environment_inspection(
    inspection: RuntimeEnvironmentInspection,
) -> str:
    """Format a runtime environment inspection for CLI output."""
    lines = [
        "Runtime environment:",
        f"platform: {inspection.platform}",
        f"system_proxy_detected: {'true' if inspection.system_proxy_detected else 'false'}",
        f"tun_hint_detected: {'true' if inspection.tun_hint_detected else 'false'}",
        f"trust_level: {inspection.trust_level}",
    ]
    if inspection.proxy_env_vars:
        lines.append("proxy_env_vars:")
        for name in inspection.proxy_env_vars:
            lines.append(f"  - {name}")
    if inspection.warnings:
        lines.append("warnings:")
        for warning in inspection.warnings:
            lines.append(f"  - {warning}")
    return "\n".join(lines)
