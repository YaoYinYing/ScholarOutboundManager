"""Textual-independent view-model helpers for the optional TUI."""

from __future__ import annotations

import re

from scholar_outbound_manager.selection import CandidateCatalogEntry


def build_candidate_table_rows(entries: list[CandidateCatalogEntry]) -> list[dict[str, object]]:
    """Build secret-safe table rows for TUI rendering."""
    return [
        {
            "index": entry.index,
            "label": truncate_display_value(entry.label or entry.source_label or "<unnamed>", limit=48),
            "region": entry.region_hint,
            "candidate_id": entry.candidate_id,
            "protocol": entry.protocol,
            "passed": entry.passed,
            "stage": entry.scholar_stage,
            "home_status": entry.home_status,
            "query_status": entry.query_status,
            "failure_marker_count": entry.failure_marker_count,
            "markers": list(entry.failure_markers),
            "tags": list(entry.tags),
        }
        for entry in entries
    ]


def build_candidate_detail(
    row: dict[str, object],
    *,
    selected_candidate_id: str | None,
    artifact_lineage_warning: str | None,
) -> dict[str, object]:
    """Build one selected candidate detail view without secret-bearing fields."""
    return {
        "candidate_id": row.get("candidate_id"),
        "label": redact_text(str(row.get("label") or "")),
        "region_hint": row.get("region"),
        "protocol": row.get("protocol"),
        "passed": row.get("passed"),
        "stage": row.get("stage"),
        "home_status": row.get("home_status"),
        "query_status": row.get("query_status"),
        "failure_markers": list(row.get("markers") or []),
        "selected": row.get("candidate_id") == selected_candidate_id,
        "artifact_lineage_warning": artifact_lineage_warning,
    }


def truncate_display_value(value: str, *, limit: int = 48) -> str:
    """Truncate one human-readable display value for dense TUI rendering."""
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def build_dashboard_model(payload: dict[str, object]) -> dict[str, object]:
    """Build one redacted dashboard model."""
    return {
        "repo_status": payload.get("repo_status"),
        "current_git_commit": payload.get("current_git_commit"),
        "venv_detected": payload.get("venv_detected"),
        "config_exists": payload.get("config_exists"),
        "config_dirty": payload.get("config_dirty"),
        "config_valid": payload.get("config_valid"),
        "undo_available": payload.get("undo_available"),
        "xray_binary_exists": payload.get("xray_binary_exists"),
        "service_active": payload.get("service_active"),
        "service_enabled": payload.get("service_enabled"),
        "socks_tcp_connect": payload.get("socks_tcp_connect"),
        "last_scholar_validation": payload.get("last_scholar_validation"),
        "candidate_count": payload.get("candidate_count"),
        "passed_count": payload.get("passed_count"),
        "selected_candidate_label": redact_text(str(payload.get("selected_candidate_label") or "")),
        "current_sidecar_port": payload.get("current_sidecar_port"),
    }


def build_pool_plan_rows(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Build redacted pool-plan rows."""
    rows: list[dict[str, object]] = []
    for entry in entries:
        rows.append(
            {
                "listen_port": entry.get("listen_port"),
                "candidate_id": entry.get("candidate_id"),
                "label": redact_text(str(entry.get("label") or entry.get("candidate_label") or "")),
                "protocol": entry.get("protocol"),
            }
        )
    return rows


def build_snippet_view(snippets: list[dict[str, object]], *, warning: str) -> dict[str, object]:
    """Build one copy-friendly snippet view without secrets."""
    import json

    rendered = redact_text(json.dumps(snippets, indent=2, ensure_ascii=False, sort_keys=True))
    return {
        "warning": warning,
        "rendered": rendered,
    }


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
