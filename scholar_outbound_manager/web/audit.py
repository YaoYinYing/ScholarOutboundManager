"""Audit logging for the optional web panel."""

from __future__ import annotations

import re
from pathlib import Path


def write_auth_log(
    path: str | Path,
    *,
    event: str,
    user: str | None,
    src: str,
    reason: str | None = None,
    ts: str,
) -> str:
    """Write one fail2ban-friendly auth log line."""
    safe_user = _sanitize_token(user or "anonymous")
    safe_src = _sanitize_token(src)
    safe_reason = _sanitize_reason(reason or "")
    line = f"SOMWEB_AUTH event={_sanitize_token(event)} user={safe_user} src={safe_src}"
    if safe_reason:
        line += f" reason={safe_reason}"
    line += f" ts={_sanitize_token(ts)}"

    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return line


def _sanitize_token(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.:@+-]", "_", value)
    return sanitized[:128]


def _sanitize_reason(value: str) -> str:
    lowered = value.lower()
    banned = (
        "password",
        "totp",
        "session",
        "vless://",
        "vmess://",
        "trojan://",
        "ss://",
        "hysteria2://",
        "public_key",
        "auth",
        "token",
    )
    if any(needle in lowered for needle in banned):
        return "redacted"
    return _sanitize_token(value)
