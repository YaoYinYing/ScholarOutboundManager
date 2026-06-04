"""Persistent Route draft storage under user_data_dir."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from datetime import timezone
from typing import Any

from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.tui.path_resolver import UserDataPaths


def load_route_draft_entries(user_data_paths: UserDataPaths) -> list[dict[str, object]]:
    """Load persisted route draft entries from selected_routes.json."""
    try:
        payload = json.loads(user_data_paths.selected_routes.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    routes = payload.get("routes")
    if not isinstance(routes, list):
        return []
    entries: list[dict[str, object]] = []
    for index, route in enumerate(routes):
        if not isinstance(route, dict):
            continue
        entries.append(
            {
                "route_id": str(route.get("route_id") or f"route-{index + 1}"),
                "name": str(route.get("name") or f"Route {index + 1}"),
                "enabled": bool(route.get("enabled", True)),
                "candidate_id": route.get("candidate_id"),
                "candidate_label": route.get("candidate_label"),
                "region_hint": route.get("region_hint"),
                "protocol": route.get("protocol"),
                "listen_host": str(route.get("listen_host") or "127.0.0.1"),
                "listen_port": int(route.get("listen_port") or (19080 + index)),
                "port_status": str(route.get("port_status") or "unknown"),
                "validation_status": str(route.get("validation_status") or "draft"),
                "error": route.get("error"),
            }
        )
    return entries


def save_route_draft_entries(entries: list[Any], user_data_paths: UserDataPaths) -> None:
    """Persist route draft entries without mutating config.yaml."""
    atomic_write_json(
        user_data_paths.selected_routes,
        {
            "schema_version": 1,
            "created_at": _utc_now_iso8601(),
            "routes": [asdict(entry) for entry in entries],
        },
    )


def _utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
