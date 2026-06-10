"""Minimal display utilities for redaction and text formatting.

These are kept as a compatibility shim for the modules that remain from
the pre-TUI-8 architecture (action_runner, commands, config_editor, config_form).
"""

from __future__ import annotations

import re


def truncate_display_value(value: str, *, limit: int = 48) -> str:
    """Truncate one human-readable display value for dense TUI rendering."""
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def redact_text(value: str) -> str:
    """Redact secret-like transport and identity material from free text."""
    redacted = value
    patterns = [
        (r"(vless|vmess|trojan|ss|hysteria2)://[^\s\"']+", "<REDACTED_URI>"),
        (r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<UUID>"),
        (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<IP>"),
        (
            r'(?i)"(public[_ -]?key|password|token|auth|obfs-password|server_name|servername|sni|host|address|user_id|raw_uri|path)"\s*:\s*"[^"]*"',
            r'"\1": "<REDACTED>"',
        ),
        (
            r"(?i)\b(public[_ -]?key|password|token|auth|obfs-password|server_name|servername|sni|host|address|user_id|raw_uri|path)\b\s*[:=]\s*\S+",
            r"\1=<REDACTED>",
        ),
        (
            r"(?i)\b(public[_ -]?key|password|token|auth|obfs-password|server_name|servername|sni|host|address|user_id|raw_uri|path)\b",
            "<REDACTED_FIELD>",
        ),
        (r"\b[a-z0-9.-]+\.(?:invalid|example|com|net|org)\b", "<HOST>"),
    ]
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted
