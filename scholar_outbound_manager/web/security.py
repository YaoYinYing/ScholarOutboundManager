"""Security helpers and middleware-like logic for the optional web panel."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


@dataclass(slots=True)
class SecurityDecision:
    """Represent one request-security decision."""

    allowed: bool
    status_code: int
    message: str | None = None


def ensure_bind_allowed(host: str, *, allow_public_bind: bool) -> None:
    """Refuse public bind hosts unless explicitly allowed."""
    if is_local_host(host):
        return
    if not allow_public_bind:
        raise ValueError("Public bind is refused unless --allow-public-bind is provided.")


def ensure_not_running_as_root(*, allow_root_process: bool, geteuid=os.geteuid) -> None:
    """Refuse root process execution unless explicitly allowed."""
    if geteuid() == 0 and not allow_root_process:
        raise ValueError("Running the web panel as root is refused by default.")


def is_local_host(host: str) -> bool:
    """Return whether one host is loopback-like."""
    return host in LOCAL_HOSTS


def require_secure_request(
    *,
    scheme: str,
    host: str,
    allow_insecure_localhost_http: bool,
    trusted_proxy_headers: bool,
    forwarded_proto: str | None = None,
) -> SecurityDecision:
    """Decide whether the incoming request satisfies HTTPS or localhost rules."""
    effective_scheme = scheme
    if trusted_proxy_headers and forwarded_proto:
        effective_scheme = forwarded_proto
    if effective_scheme == "https":
        return SecurityDecision(True, 200)
    if is_local_host(host) and allow_insecure_localhost_http:
        return SecurityDecision(True, 200)
    return SecurityDecision(False, 403, "HTTPS is required unless accessed via localhost.")


def validate_content_type(content_type: str | None, *, expected: str) -> bool:
    """Validate incoming Content-Type against an allowlist."""
    if content_type is None:
        return False
    normalized = content_type.split(";", 1)[0].strip().lower()
    if expected == "json":
        return normalized == "application/json"
    if expected == "form":
        return normalized in {"application/x-www-form-urlencoded", "multipart/form-data"}
    return False


def ensure_path_under_root(path: str | Path, *, allowed_root: str | Path) -> None:
    """Ensure one path resolves under an approved root."""
    resolved = Path(path).resolve()
    root = Path(allowed_root).resolve()
    if root not in {resolved, *resolved.parents}:
        raise ValueError("path must resolve under the approved root.")


def security_headers(*, authenticated: bool) -> dict[str, str]:
    """Build the baseline response security headers."""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        "X-Frame-Options": "DENY",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }
    if authenticated:
        headers["Cache-Control"] = "no-store"
    return headers
