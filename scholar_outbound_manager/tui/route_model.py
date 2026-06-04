"""Typed Route workbench state for the config-centered TUI."""

from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

import yaml

from scholar_outbound_manager.selection import build_candidate_display_label
from scholar_outbound_manager.selection import build_selected_candidate_artifact
from scholar_outbound_manager.selection import extract_candidate_selection_records
from scholar_outbound_manager.selection import infer_probe_passed
from scholar_outbound_manager.selection import select_candidate_by_id
from scholar_outbound_manager.selection import write_selected_candidate_artifact
from scholar_outbound_manager.sidecar_pool import SidecarPoolEntry
from scholar_outbound_manager.sidecar_pool import SidecarPoolPlan
from scholar_outbound_manager.sidecar_pool import write_pool_plan
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.tui.config_centered import DEFAULT_SERVICE_NAME
from scholar_outbound_manager.tui.config_editor import load_config_draft
from scholar_outbound_manager.tui.config_editor import save_config_draft
from scholar_outbound_manager.tui.config_editor import update_config_draft_text
from scholar_outbound_manager.tui.config_centered import summarize_config_centered_state
from scholar_outbound_manager.tui.path_resolver import UserDataPaths
from scholar_outbound_manager.tui.path_resolver import load_raw_config_mapping
from scholar_outbound_manager.tui.port_check import PortCheckResult
from scholar_outbound_manager.tui.port_check import check_route_port
from scholar_outbound_manager.tui.view_model import redact_text


@dataclass(slots=True, frozen=True)
class RouteCandidateOption:
    candidate_id: str
    label: str
    region_hint: str | None
    protocol: str
    stage: str
    home_status: int | None
    query_status: int | None


@dataclass(slots=True, frozen=True)
class RouteEntryDraft:
    route_id: str
    name: str
    enabled: bool
    candidate_id: str | None
    candidate_label: str | None
    region_hint: str | None
    protocol: str | None
    listen_host: str
    listen_port: int
    port_status: str
    validation_status: str
    error: str | None


@dataclass(slots=True, frozen=True)
class RouteWorkbenchState:
    entries: list[RouteEntryDraft]
    selected_index: int
    passed_candidates: list[RouteCandidateOption]
    can_apply: bool
    validation_errors: list[str]
    production_boundary: str
    candidate_selector_enabled: bool
    candidate_selector_message: str | None
    stale_warning: str | None
    current_port_result: PortCheckResult | None


def build_passed_candidate_options(passed_candidates_path: Path) -> list[RouteCandidateOption]:
    """Build safe candidate options from the passed-candidates artifact."""

    try:
        payload = json.loads(passed_candidates_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    options: list[RouteCandidateOption] = []
    for record in extract_candidate_selection_records(payload):
        if not record.candidate.supported:
            continue
        if not infer_probe_passed(record.probe_payload):
            continue
        probe = record.probe_payload or {}
        label = build_candidate_display_label(record.candidate_payload)
        options.append(
            RouteCandidateOption(
                candidate_id=record.candidate_id,
                label=redact_text(label),
                region_hint=_infer_region_hint(record.candidate_payload, label),
                protocol=record.candidate.protocol,
                stage=str(probe.get("scholar_stage") or "full_access"),
                home_status=_coerce_optional_int(probe.get("home_status")),
                query_status=_coerce_optional_int(probe.get("query_status")),
            )
        )
    return options


def build_route_workbench_state(
    *,
    config_path: str,
    user_data_paths: UserDataPaths,
    selected_index: int = 0,
    port_results: dict[str, PortCheckResult] | None = None,
    route_entries: list[dict[str, object]] | None = None,
) -> RouteWorkbenchState:
    """Build the full typed Route workbench state."""

    config_summary = summarize_config_centered_state(config_path)
    artifact_warning = _load_artifact_warning(user_data_paths)
    options = build_passed_candidate_options(user_data_paths.passed_candidates) if artifact_warning is None else []
    if artifact_warning is not None:
        candidate_selector_message = artifact_warning
    elif not options:
        candidate_selector_message = "No passed candidates available. Run Test Nodes first."
    else:
        candidate_selector_message = None
    option_by_id = {option.candidate_id: option for option in options}
    raw_entries = (
        [dict(entry) for entry in route_entries]
        if isinstance(route_entries, list) and route_entries
        else load_route_entries_from_config_or_selected_routes(config_path, user_data_paths=user_data_paths)
    )
    entries: list[RouteEntryDraft] = []
    port_results = {} if port_results is None else dict(port_results)
    for index, raw_entry in enumerate(raw_entries):
        candidate_id = _coerce_optional_str(raw_entry.get("candidate_id"))
        option = option_by_id.get(candidate_id or "")
        error = None
        if candidate_id and option is None:
            error = "stale candidate"
        route_id = str(raw_entry.get("route_id") or f"route-{index + 1}")
        port_result = port_results.get(route_id)
        entries.append(
            RouteEntryDraft(
                route_id=route_id,
                name=str(raw_entry.get("name") or f"Route {index + 1}"),
                enabled=bool(raw_entry.get("enabled", True)),
                candidate_id=candidate_id,
                candidate_label=option.label if option is not None else _coerce_optional_str(raw_entry.get("candidate_label")),
                region_hint=option.region_hint if option is not None else None,
                protocol=option.protocol if option is not None else None,
                listen_host=str(raw_entry.get("listen_host") or "127.0.0.1"),
                listen_port=_coerce_port(raw_entry.get("listen_port"), default=19080 + index),
                port_status=port_result.status if port_result is not None else "unknown",
                validation_status="stale" if error else "ready",
                error=error,
            )
        )
    if not entries:
        entries = [_default_entry()]
    selected_index = max(0, min(len(entries) - 1, selected_index))
    validation_errors = _validate_route_entries(entries, artifact_warning=artifact_warning)
    return RouteWorkbenchState(
        entries=entries,
        selected_index=selected_index,
        passed_candidates=options,
        can_apply=not validation_errors,
        validation_errors=validation_errors,
        production_boundary="Only ScholarOutboundManager sidecar is managed. Production Xray/XrayR/x-ui is never modified.",
        candidate_selector_enabled=artifact_warning is None and bool(options),
        candidate_selector_message=candidate_selector_message,
        stale_warning=artifact_warning,
        current_port_result=port_results.get(entries[selected_index].route_id),
    )


def load_route_entries_from_config_or_selected_routes(
    config_path: str,
    *,
    user_data_paths: UserDataPaths,
) -> list[dict[str, object]]:
    """Load route entries from config.yaml and optional selected-routes artifact."""

    raw = load_raw_config_mapping(config_path)
    route = raw.get("route")
    route_entries = route.get("entries") if isinstance(route, dict) else None
    entries: list[dict[str, object]] = []
    if isinstance(route_entries, list):
        for index, entry in enumerate(route_entries):
            if not isinstance(entry, dict):
                continue
            entries.append(
                {
                    "route_id": str(entry.get("route_id") or f"route-{index + 1}"),
                    "name": str(entry.get("name") or "Scholar"),
                    "enabled": bool(entry.get("enabled", True)),
                    "candidate_id": entry.get("candidate_id"),
                    "listen_host": str(entry.get("listen_host") or "127.0.0.1"),
                    "listen_port": _coerce_port(entry.get("listen_port"), default=19080 + index),
                }
            )
    if entries:
        _merge_selected_route_labels(entries, user_data_paths.selected_routes)
        return entries
    return [asdict(_default_entry())]


def save_route_entries_to_config_or_selected_routes(
    config_path: str,
    *,
    user_data_paths: UserDataPaths,
    entries: list[RouteEntryDraft],
) -> str:
    """Persist route entries to config.yaml plus local route artifacts."""

    raw = load_raw_config_mapping(config_path)
    raw["route"] = raw.get("route") if isinstance(raw.get("route"), dict) else {}
    route_mapping = dict(raw["route"])
    route_mapping["entries"] = [
        {
            "route_id": entry.route_id,
            "name": entry.name,
            "candidate_id": entry.candidate_id,
            "listen_host": entry.listen_host,
            "listen_port": entry.listen_port,
            "enabled": entry.enabled,
        }
        for entry in entries
    ]
    raw["route"] = route_mapping

    original = load_config_draft(config_path)
    rendered = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
    updated = update_config_draft_text(original, rendered)
    save_config_draft(updated, undo_journal_path=user_data_paths.undo_journal)

    enabled_entries = [entry for entry in entries if entry.enabled]
    _write_selected_routes_artifact(user_data_paths.selected_routes, enabled_entries)
    _write_selected_candidate_artifact_if_available(user_data_paths.selected_candidate, user_data_paths.passed_candidates, enabled_entries)
    _write_pool_plan_if_available(user_data_paths.pool_plan, enabled_entries)
    return "Route draft saved to config.yaml and local route artifacts were refreshed."


def update_route_entry_candidate(
    state: RouteWorkbenchState,
    *,
    entry_index: int,
    candidate_id: str,
) -> RouteWorkbenchState:
    """Return a new state with one route entry candidate updated."""

    options = {option.candidate_id: option for option in state.passed_candidates}
    option = options.get(candidate_id)
    if option is None:
        raise ValueError("Selected passed candidate is not available.")
    entries = list(state.entries)
    current = entries[entry_index]
    entries[entry_index] = RouteEntryDraft(
        route_id=current.route_id,
        name=current.name,
        enabled=current.enabled,
        candidate_id=option.candidate_id,
        candidate_label=option.label,
        region_hint=option.region_hint,
        protocol=option.protocol,
        listen_host=current.listen_host,
        listen_port=current.listen_port,
        port_status=current.port_status,
        validation_status="ready",
        error=None,
    )
    validation_errors = _validate_route_entries(entries, artifact_warning=state.stale_warning)
    return RouteWorkbenchState(
        entries=entries,
        selected_index=state.selected_index,
        passed_candidates=state.passed_candidates,
        can_apply=not validation_errors,
        validation_errors=validation_errors,
        production_boundary=state.production_boundary,
        candidate_selector_enabled=state.candidate_selector_enabled,
        candidate_selector_message=state.candidate_selector_message,
        stale_warning=state.stale_warning,
        current_port_result=state.current_port_result,
    )


def add_route_entry(state: RouteWorkbenchState) -> RouteWorkbenchState:
    entries = list(state.entries)
    next_port = _next_port(entries)
    entries.append(
        RouteEntryDraft(
            route_id=f"route-{len(entries) + 1}",
            name=f"Route {len(entries) + 1}",
            enabled=True,
            candidate_id=None,
            candidate_label=None,
            region_hint=None,
            protocol=None,
            listen_host="127.0.0.1",
            listen_port=next_port,
            port_status="unknown",
            validation_status="draft",
            error=None,
        )
    )
    validation_errors = _validate_route_entries(entries, artifact_warning=state.stale_warning)
    return RouteWorkbenchState(
        entries=entries,
        selected_index=len(entries) - 1,
        passed_candidates=state.passed_candidates,
        can_apply=not validation_errors,
        validation_errors=validation_errors,
        production_boundary=state.production_boundary,
        candidate_selector_enabled=state.candidate_selector_enabled,
        candidate_selector_message=state.candidate_selector_message,
        stale_warning=state.stale_warning,
        current_port_result=None,
    )


def delete_route_entry(state: RouteWorkbenchState) -> tuple[RouteWorkbenchState, str | None]:
    if len(state.entries) <= 1:
        return state, "At least one route must remain configured."
    entries = list(state.entries)
    del entries[state.selected_index]
    selected_index = max(0, min(state.selected_index, len(entries) - 1))
    validation_errors = _validate_route_entries(entries, artifact_warning=state.stale_warning)
    return (
        RouteWorkbenchState(
            entries=entries,
            selected_index=selected_index,
            passed_candidates=state.passed_candidates,
            can_apply=not validation_errors,
            validation_errors=validation_errors,
            production_boundary=state.production_boundary,
            candidate_selector_enabled=state.candidate_selector_enabled,
            candidate_selector_message=state.candidate_selector_message,
            stale_warning=state.stale_warning,
            current_port_result=None,
        ),
        None,
    )


def check_selected_route_port(
    state: RouteWorkbenchState,
    *,
    managed_service_name: str,
    runtime_metadata_path: Path | None = None,
) -> RouteWorkbenchState:
    entry = state.entries[state.selected_index]
    result = check_route_port(
        entry.listen_host,
        entry.listen_port,
        managed_service_name=managed_service_name or DEFAULT_SERVICE_NAME,
        runtime_metadata_path=runtime_metadata_path,
    )
    entries = list(state.entries)
    entries[state.selected_index] = RouteEntryDraft(
        route_id=entry.route_id,
        name=entry.name,
        enabled=entry.enabled,
        candidate_id=entry.candidate_id,
        candidate_label=entry.candidate_label,
        region_hint=entry.region_hint,
        protocol=entry.protocol,
        listen_host=entry.listen_host,
        listen_port=entry.listen_port,
        port_status=result.status,
        validation_status="ready" if result.reusable else "blocked",
        error=None if result.reusable else result.message,
    )
    validation_errors = _validate_route_entries(entries, artifact_warning=state.stale_warning)
    return RouteWorkbenchState(
        entries=entries,
        selected_index=state.selected_index,
        passed_candidates=state.passed_candidates,
        can_apply=not validation_errors,
        validation_errors=validation_errors,
        production_boundary=state.production_boundary,
        candidate_selector_enabled=state.candidate_selector_enabled,
        candidate_selector_message=state.candidate_selector_message,
        stale_warning=state.stale_warning,
        current_port_result=result,
    )


def route_workbench_state_to_dict(state: RouteWorkbenchState) -> dict[str, object]:
    return {
        "entries": [asdict(entry) for entry in state.entries],
        "selected_index": state.selected_index,
        "passed_candidates": [asdict(option) for option in state.passed_candidates],
        "can_apply": state.can_apply,
        "validation_errors": list(state.validation_errors),
        "production_boundary": state.production_boundary,
        "candidate_selector_enabled": state.candidate_selector_enabled,
        "candidate_selector_message": state.candidate_selector_message,
        "stale_warning": state.stale_warning,
        "current_port_result": None if state.current_port_result is None else asdict(state.current_port_result),
    }


def _default_entry() -> RouteEntryDraft:
    return RouteEntryDraft(
        route_id="route-1",
        name="Scholar",
        enabled=True,
        candidate_id=None,
        candidate_label=None,
        region_hint=None,
        protocol=None,
        listen_host="127.0.0.1",
        listen_port=19080,
        port_status="unknown",
        validation_status="draft",
        error=None,
    )


def _load_artifact_warning(user_data_paths: UserDataPaths) -> str | None:
    try:
        probe_payload = json.loads(user_data_paths.probe_summary.read_text(encoding="utf-8"))
        candidates_payload = json.loads(user_data_paths.candidates.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(probe_payload, dict) or not isinstance(candidates_payload, dict):
        return None
    from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash

    probe_hash = str(probe_payload.get("source_candidates_hash") or "")
    candidate_hash = compute_artifact_hash(candidates_payload)
    if probe_hash and probe_hash != candidate_hash:
        return "Testing artifacts are stale. Run Test Nodes before changing routes."
    return None


def _validate_route_entries(entries: list[RouteEntryDraft], *, artifact_warning: str | None) -> list[str]:
    errors: list[str] = []
    if artifact_warning:
        errors.append(artifact_warning)
    enabled_entries = [entry for entry in entries if entry.enabled]
    if not enabled_entries:
        errors.append("At least one route must remain enabled.")
    seen_ports: set[tuple[str, int]] = set()
    for entry in enabled_entries:
        if not entry.candidate_id:
            errors.append(f"{entry.name} is missing a passed candidate.")
        if entry.error:
            errors.append(f"{entry.name}: {entry.error}")
        if entry.listen_port <= 0 or entry.listen_port > 65535:
            errors.append(f"{entry.name} has an invalid listen port.")
        key = (entry.listen_host, entry.listen_port)
        if key in seen_ports:
            errors.append(f"{entry.name} reuses a duplicate listen port.")
        seen_ports.add(key)
        if entry.port_status == "occupied_by_external_process":
            errors.append(f"{entry.name} uses a port occupied by another process.")
    return errors


def _merge_selected_route_labels(entries: list[dict[str, object]], selected_routes_path: Path) -> None:
    try:
        payload = json.loads(selected_routes_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    routes = payload.get("routes")
    if not isinstance(routes, list):
        return
    labels_by_id = {
        str(route.get("candidate_id")): route
        for route in routes
        if isinstance(route, dict) and route.get("candidate_id")
    }
    for entry in entries:
        route = labels_by_id.get(str(entry.get("candidate_id") or ""))
        if route:
            entry["candidate_label"] = route.get("candidate_label")


def _write_selected_routes_artifact(path: Path, entries: list[RouteEntryDraft]) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "created_at": _utc_now_iso8601(),
            "routes": [
                {
                    "route_id": entry.route_id,
                    "name": entry.name,
                    "enabled": entry.enabled,
                    "candidate_id": entry.candidate_id,
                    "candidate_label": entry.candidate_label,
                    "region_hint": entry.region_hint,
                    "protocol": entry.protocol,
                    "listen_host": entry.listen_host,
                    "listen_port": entry.listen_port,
                }
                for entry in entries
            ],
        },
    )


def _write_selected_candidate_artifact_if_available(path: Path, passed_candidates_path: Path, entries: list[RouteEntryDraft]) -> None:
    first = next((entry for entry in entries if entry.enabled and entry.candidate_id), None)
    if first is None:
        return
    try:
        payload = json.loads(passed_candidates_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    record = select_candidate_by_id(payload, str(first.candidate_id))
    artifact = build_selected_candidate_artifact(record, selection_method="candidate_id")
    write_selected_candidate_artifact(path, artifact)


def _write_pool_plan_if_available(path: Path, entries: list[RouteEntryDraft]) -> None:
    enabled = [entry for entry in entries if entry.enabled and entry.candidate_id]
    plan_entries = [
        SidecarPoolEntry(
            pool_index=index,
            candidate_id=str(entry.candidate_id),
            candidate_protocol=str(entry.protocol or "unknown"),
            listen_host=entry.listen_host,
            listen_port=entry.listen_port,
            inbound_tag=f"scholar-sidecar-socks-in-{index}",
            outbound_tag=f"scholar-sidecar-out-{index}",
            socks_tag=f"scholar-sidecar-socks-out-{index}",
        )
        for index, entry in enumerate(enabled)
    ]
    plan = SidecarPoolPlan(
        created_at=_utc_now_iso8601(),
        listen_host=enabled[0].listen_host if enabled else "127.0.0.1",
        base_port=enabled[0].listen_port if enabled else 19080,
        count=len(plan_entries),
        entries=plan_entries,
    )
    write_pool_plan(path, plan)


def _next_port(entries: list[RouteEntryDraft]) -> int:
    ports = [entry.listen_port for entry in entries]
    return max(ports, default=19079) + 1


def _coerce_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _coerce_port(value: object, *, default: int) -> int:
    port = _coerce_optional_int(value)
    if port is None or port <= 0 or port > 65535:
        return default
    return port


def _coerce_optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _infer_region_hint(candidate_payload: dict[str, Any], label: str) -> str | None:
    extra = candidate_payload.get("extra")
    if isinstance(extra, dict):
        region = extra.get("region_hint")
        if isinstance(region, str) and region:
            return region
    upper = label.upper()
    if "US" in upper or "美国" in label:
        return "US"
    if "JP" in upper or "日本" in label:
        return "JP"
    if "HK" in upper or "香港" in label:
        return "HK"
    return None


def _utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "RouteCandidateOption",
    "RouteEntryDraft",
    "RouteWorkbenchState",
    "add_route_entry",
    "build_passed_candidate_options",
    "build_route_workbench_state",
    "check_selected_route_port",
    "delete_route_entry",
    "load_route_entries_from_config_or_selected_routes",
    "route_workbench_state_to_dict",
    "save_route_entries_to_config_or_selected_routes",
    "update_route_entry_candidate",
]
