"""Textual-independent view-model helpers for the optional TUI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from scholar_outbound_manager.selection import CandidateCatalogEntry


class HealthState(str, Enum):
    OK = "ok"
    WARNING = "warning"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RouteSummary:
    """User-facing summary for one outbound route."""

    index: int
    display_label: str
    region: str
    provider: str
    protocol: str
    latency_label: str
    passed: bool
    is_selected: bool
    is_cursor: bool
    stage_label: str
    note: str
    raw_id: str


@dataclass(frozen=True, slots=True)
class OperationImpact:
    """User-facing description of what an operation will touch."""

    confirmation_required: bool
    uses_network: bool
    touches_system: bool
    summary: str
    details: list[str]


@dataclass(frozen=True, slots=True)
class WorkflowSummary:
    """Top-level state rendered by the Overview page."""

    config_state: HealthState
    route_state: HealthState
    selected_route_label: str | None
    selected_route_id: str | None
    route_count: int
    passed_route_count: int
    service_state_label: str
    local_proxy_state_label: str
    next_action_label: str
    next_action_reason: str
    last_action_label: str


@dataclass(frozen=True, slots=True)
class RouteDetail:
    raw_id: str
    display_label: str
    region: str
    protocol: str
    stage_label: str
    passed: bool
    home_status: int | None
    query_status: int | None
    failure_marker_count: int
    failure_markers: list[str]
    artifact_lineage_warning: str | None


@dataclass(frozen=True, slots=True)
class ActivateStep:
    title: str
    status: str
    note: str


@dataclass(frozen=True, slots=True)
class SettingsFieldView:
    title: str
    value: str
    restart_required: bool
    key: str


@dataclass(frozen=True, slots=True)
class PageAction:
    label: str
    key_hint: str
    description: str


@dataclass(frozen=True, slots=True)
class HomeCard:
    title: str
    rows: list[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class SettingsSummary:
    config_path: str
    user_data_dir: str
    subscription_url_masked: str
    subscription_user_agent: str
    xray_binary_path: str
    fail_closed: bool
    experimental_hysteria2: bool
    service_name: str


@dataclass(frozen=True, slots=True)
class TableModel:
    columns: list[str]
    rows: list[list[str]]
    empty_message: str


@dataclass(frozen=True, slots=True)
class LogsSummary:
    action_rows: list[list[str]]
    snapshot_rows: list[list[str]]
    rollback_warning: list[str]


def build_candidate_table_rows(entries: list[CandidateCatalogEntry]) -> list[dict[str, object]]:
    """Build secret-safe table rows for TUI rendering."""
    return [
        {
            "index": entry.index,
            "label": truncate_display_value(entry.label or entry.source_label or "<unnamed>", limit=48),
            "region": entry.region_hint or "Unknown",
            "provider": truncate_display_value(entry.source_name or entry.source_label or "Unknown", limit=18),
            "candidate_id": entry.candidate_id,
            "protocol": entry.protocol,
            "passed": entry.passed,
            "stage": entry.scholar_stage,
            "home_status": entry.home_status,
            "query_status": entry.query_status,
            "failure_marker_count": entry.failure_marker_count,
            "markers": list(entry.failure_markers),
            "tags": list(entry.tags),
            "latency_ms": entry.latency_ms,
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


def build_route_summaries(
    rows: list[dict[str, object]],
    *,
    selected_candidate_id: str | None,
    cursor_candidate_id: str | None,
) -> list[RouteSummary]:
    """Build user-facing route summaries from redacted backend rows."""
    results: list[RouteSummary] = []
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        latency_ms = row.get("latency_ms")
        note = ""
        if candidate_id and candidate_id == selected_candidate_id:
            note = "Selected"
        elif row.get("passed") is True:
            note = "Passed"
        else:
            note = "Needs review"
        results.append(
            RouteSummary(
                index=int(row.get("index") or 0) + 1,
                display_label=truncate_display_value(str(row.get("label") or "<unnamed>"), limit=44),
                region=truncate_display_value(str(row.get("region") or "Unknown"), limit=12),
                provider=truncate_display_value(str(row.get("provider") or "Unknown"), limit=16),
                protocol=str(row.get("protocol") or "unknown"),
                latency_label=_latency_label(latency_ms),
                passed=row.get("passed") is True,
                is_selected=bool(candidate_id and candidate_id == selected_candidate_id),
                is_cursor=bool(candidate_id and candidate_id == cursor_candidate_id),
                stage_label=_stage_label(str(row.get("stage") or "")),
                note=note,
                raw_id=candidate_id,
            )
        )
    return results


def build_route_detail(detail: dict[str, object] | None) -> RouteDetail | None:
    """Build one route detail object for the current cursor route."""
    if not isinstance(detail, dict) or not detail.get("candidate_id"):
        return None
    markers = list(detail.get("failure_markers") or [])
    return RouteDetail(
        raw_id=str(detail.get("candidate_id") or ""),
        display_label=redact_text(str(detail.get("label") or "")),
        region=str(detail.get("region_hint") or "Unknown"),
        protocol=str(detail.get("protocol") or "unknown"),
        stage_label=_stage_label(str(detail.get("stage") or "")),
        passed=detail.get("passed") is True,
        home_status=_coerce_optional_int(detail.get("home_status")),
        query_status=_coerce_optional_int(detail.get("query_status")),
        failure_marker_count=len(markers),
        failure_markers=markers,
        artifact_lineage_warning=_coerce_optional_str(detail.get("artifact_lineage_warning")),
    )


def build_workflow_summary(workflow_state: dict[str, object]) -> WorkflowSummary:
    """Build one Overview page summary from workflow state."""
    preflight = workflow_state.get("preflight", {})
    selection = workflow_state.get("selection", {})
    artifacts = workflow_state.get("artifacts", {})
    control_plane = workflow_state.get("control_plane", {})
    dashboard = workflow_state.get("dashboard", {})
    next_action_label, next_action_reason = resolve_next_action(workflow_state)
    return WorkflowSummary(
        config_state=_config_health(preflight, workflow_state),
        route_state=_route_health(artifacts, selection),
        selected_route_label=_coerce_optional_str(selection.get("selected_candidate_label")),
        selected_route_id=_coerce_optional_str(selection.get("selected_candidate_id")),
        route_count=int(dashboard.get("candidate_count") or 0),
        passed_route_count=int(dashboard.get("passed_count") or 0),
        service_state_label=_service_state_label(control_plane.get("sidecar_state", {})),
        local_proxy_state_label=_proxy_state_label(control_plane.get("sidecar_state", {})),
        next_action_label=next_action_label,
        next_action_reason=next_action_reason,
        last_action_label=_last_action_label(dashboard.get("last_action")),
    )


def build_activate_steps(workflow_state: dict[str, object]) -> list[ActivateStep]:
    """Build the Activate page step list."""
    operation_availability = workflow_state.get("operation_availability", {})
    sidecar_state = workflow_state.get("control_plane", {}).get("sidecar_state", {})
    last_action = workflow_state.get("last_action")
    steps: list[ActivateStep] = []
    steps.append(
        ActivateStep(
            title="Prepare local runtime files",
            status="Ready" if operation_availability.get("sidecar_stage_available") else "Unavailable",
            note="Prepare the local runtime from the selected route without touching production Xray/XrayR/x-ui.",
        )
    )
    restart_status = "Confirmation required" if operation_availability.get("service_restart_available") else "Unavailable"
    if isinstance(last_action, dict) and last_action.get("key") == "service_restart" and last_action.get("succeeded") is True:
        restart_status = "Completed"
    steps.append(
        ActivateStep(
            title="Restart local proxy service",
            status=restart_status,
            note="This touches the managed system service only.",
        )
    )
    validate_status = "Pending"
    if sidecar_state.get("socks_tcp_connect") == "true":
        validate_status = "Ready"
    if isinstance(last_action, dict) and last_action.get("key") == "service_validate" and last_action.get("succeeded") is True:
        validate_status = "Completed"
    steps.append(
        ActivateStep(
            title="Validate local SOCKS proxy",
            status=validate_status,
            note="Live validation checks the managed local SOCKS proxy after preparation.",
        )
    )
    return steps


def build_operation_impact(operation: dict[str, object] | None, *, action_label: str) -> OperationImpact:
    """Build one user-facing operation impact summary."""
    if not isinstance(operation, dict):
        return OperationImpact(False, False, False, action_label, [])
    details: list[str] = []
    if operation.get("requires_confirmation"):
        details.append("Confirmation required")
    if operation.get("network_access"):
        details.append("Uses network")
    if operation.get("systemd_access"):
        details.append("Touches system service")
    risk_note = _coerce_optional_str(operation.get("risk_note"))
    if risk_note:
        details.append(risk_note)
    return OperationImpact(
        confirmation_required=bool(operation.get("requires_confirmation")),
        uses_network=bool(operation.get("network_access")),
        touches_system=bool(operation.get("systemd_access")),
        summary=action_label,
        details=details,
    )


def build_settings_groups(form: dict[str, object]) -> dict[str, list[SettingsFieldView]]:
    """Group allowlisted config fields by purpose."""
    groups: dict[str, list[SettingsFieldView]] = {
        "Connectivity test": [],
        "Local runtime": [],
        "Routing": [],
    }
    for field in form.get("fields", []):
        if not isinstance(field, dict):
            continue
        view = SettingsFieldView(
            title=str(field.get("title") or field.get("key") or "Field"),
            value=_stringify_field_value(field.get("draft_value", field.get("current_value"))),
            restart_required=bool(field.get("requires_restart")),
            key=str(field.get("key") or ""),
        )
        key = str(field.get("key") or "")
        if key.startswith("probe."):
            groups["Connectivity test"].append(view)
        elif key.startswith("xray."):
            groups["Local runtime"].append(view)
        else:
            groups["Routing"].append(view)
    return groups


def build_home_cards(workflow_state: dict[str, object]) -> list[HomeCard]:
    """Build the task-centered Home card set."""
    home = workflow_state.get("home", {})
    return [
        HomeCard(
            title="Subscription",
            rows=[
                ("Configured", "yes" if home.get("subscription_configured") else "no"),
                ("Last fetch", str(home.get("last_fetch_status") or "unknown")),
                ("Candidates", str(home.get("candidate_count") or 0)),
                ("Supported", str(home.get("supported_count") or 0)),
            ],
        ),
        HomeCard(
            title="Testing",
            rows=[
                ("Tested", str(home.get("tested_count") or 0)),
                ("Passed", str(home.get("passed_count") or 0)),
                ("Failed", str(home.get("failed_count") or 0)),
                ("Full access", str(home.get("full_access_count") or 0)),
                ("Query blocked", str(home.get("query_blocked_count") or 0)),
                ("Transport failed", str(home.get("transport_failed_count") or 0)),
            ],
        ),
        HomeCard(
            title="Route",
            rows=[
                ("Entries", str(home.get("route_count") or 0)),
                ("Enabled", str(home.get("enabled_route_count") or 0)),
                ("Selected", str(home.get("selected_candidate_label") or "none")),
                ("Ports", ", ".join(str(port) for port in home.get("active_listen_ports", [])) or "none"),
            ],
        ),
        HomeCard(
            title="Sidecar",
            rows=[
                ("Service", str(home.get("service_active") or "unknown")),
                ("Enabled", str(home.get("service_enabled") or "unknown")),
                ("SOCKS", str(home.get("socks_status") or "unknown")),
                ("Last validation", str(home.get("last_validation") or "unknown")),
            ],
        ),
    ]


def build_settings_summary(workflow_state: dict[str, object]) -> SettingsSummary:
    """Build one Settings page summary."""
    settings = workflow_state.get("settings", {})
    return SettingsSummary(
        config_path=str(settings.get("config_path") or ""),
        user_data_dir=str(settings.get("user_data_dir") or ""),
        subscription_url_masked=str(settings.get("subscription_url_masked") or "Not configured"),
        subscription_user_agent=str(settings.get("subscription_user_agent") or ""),
        xray_binary_path=str(settings.get("xray_binary_path") or ""),
        fail_closed=bool(settings.get("fail_closed")),
        experimental_hysteria2=bool(settings.get("experimental_hysteria2")),
        service_name=str(settings.get("service_name") or ""),
    )


def build_testing_table_model(workflow_state: dict[str, object]) -> TableModel:
    """Build the Testing candidate table model."""
    rows = workflow_state.get("testing", {}).get("candidate_rows", [])
    table_rows: list[list[str]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        table_rows.append(
            [
                "PASS" if row.get("passed") else "REVIEW",
                str(row.get("index")),
                str(row.get("region") or "Unknown"),
                truncate_display_value(str(row.get("label") or ""), limit=24),
                str(row.get("protocol") or "unknown"),
                _latency_label(row.get("latency_ms")),
                str(row.get("home_status") or "-"),
                str(row.get("query_status") or "-"),
                str(row.get("stage") or "-"),
                str(row.get("failure_marker_count") or 0),
            ]
        )
    return TableModel(
        columns=["status", "#", "region", "label", "protocol", "latency", "home", "query", "stage", "markers"],
        rows=table_rows,
        empty_message="No candidate results yet. Use Fetch Subscription or Test Nodes.",
    )


def build_route_table_model(workflow_state: dict[str, object]) -> TableModel:
    """Build the Route table model."""
    route = workflow_state.get("route", {})
    table_rows: list[list[str]] = []
    for entry in route.get("entries", []) if isinstance(route.get("entries"), list) else []:
        if not isinstance(entry, dict):
            continue
        table_rows.append(
            [
                "ON" if entry.get("enabled") else "OFF",
                str(entry.get("name") or "Route"),
                truncate_display_value(str(route.get("selected_candidate_label") or "Unassigned"), limit=24),
                str(entry.get("listen_host") or "127.0.0.1"),
                str(entry.get("listen_port") or "19080"),
                "Pending",
                "Not validated",
            ]
        )
    return TableModel(
        columns=["enabled", "name", "candidate", "host", "port", "port status", "validation"],
        rows=table_rows,
        empty_message="No routes configured yet.",
    )


def build_logs_summary(workflow_state: dict[str, object]) -> LogsSummary:
    """Build the Logs page summary."""
    logs = workflow_state.get("logs_screen", {})
    last_action = logs.get("last_action")
    action_rows: list[list[str]] = []
    if isinstance(last_action, dict):
        action_rows.append(
            [
                str(last_action.get("title") or last_action.get("key") or "Action"),
                "ok" if last_action.get("succeeded") else "review",
                truncate_display_value(str(last_action.get("summary") or ""), limit=60),
            ]
        )
    snapshot_rows = [[
        str(logs.get("latest_snapshot_id") or "none"),
        str(logs.get("latest_snapshot_reason") or "none"),
    ]]
    return LogsSummary(
        action_rows=action_rows,
        snapshot_rows=snapshot_rows,
        rollback_warning=list(logs.get("rollback_warning") or []),
    )


def resolve_next_action(workflow_state: dict[str, object]) -> tuple[str, str]:
    """Resolve one concise user-facing next action and reason."""
    preflight = workflow_state.get("preflight", {})
    artifacts = workflow_state.get("artifacts", {})
    selection = workflow_state.get("selection", {})
    config_form = workflow_state.get("config_form", {})
    control_plane = workflow_state.get("control_plane", {})
    sidecar_state = control_plane.get("sidecar_state", {})
    if not preflight.get("config_exists"):
        return "Fix settings", "The configuration file is missing."
    if not preflight.get("config_valid"):
        errors = list(preflight.get("config_validation_errors") or [])
        return "Fix settings", errors[0] if errors else "The configuration file failed validation."
    if config_form.get("dirty"):
        return "Save settings", "Structured settings changes are pending."
    if not artifacts.get("candidates_exists"):
        return "Fetch routes", "No local route list is available yet."
    if not artifacts.get("probe_summary_exists") or not artifacts.get("passed_candidates_exists"):
        return "Test routes", "Routes exist, but connectivity test results are missing."
    if not selection.get("selected_candidate_id"):
        return "Choose a route", "Routes passed connectivity tests, but no route has been selected."
    if not control_plane.get("pool_state", {}).get("plan_exists") and control_plane.get("command_state", {}).get("operations"):
        return "Prepare local runtime files", "The selected route has not yet been prepared for local use."
    if sidecar_state.get("service_active") == "unknown":
        return "Restart local proxy service", "The managed local proxy service has not been restarted in this workflow yet."
    if sidecar_state.get("socks_tcp_connect") != "true":
        return "Validate local SOCKS proxy", "The local SOCKS proxy has not been validated successfully in this session."
    return "Ready", "The selected route is prepared and the managed local proxy has passed validation."


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


def _coerce_optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _coerce_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _config_health(preflight: dict[str, object], workflow_state: dict[str, object]) -> HealthState:
    if not preflight.get("config_exists") or not preflight.get("config_valid"):
        return HealthState.BLOCKED
    if workflow_state.get("config_form", {}).get("dirty"):
        return HealthState.WARNING
    return HealthState.OK


def _route_health(artifacts: dict[str, object], selection: dict[str, object]) -> HealthState:
    if not artifacts.get("candidates_exists"):
        return HealthState.UNKNOWN
    if not artifacts.get("passed_candidates_exists"):
        return HealthState.WARNING
    if not selection.get("selected_candidate_id"):
        return HealthState.WARNING
    return HealthState.OK


def _service_state_label(sidecar_state: dict[str, object]) -> str:
    value = str(sidecar_state.get("service_active") or "unknown")
    return {
        "true": "Active",
        "false": "Inactive",
        "unknown": "Not checked",
    }.get(value, truncate_display_value(value, limit=24))


def _proxy_state_label(sidecar_state: dict[str, object]) -> str:
    value = str(sidecar_state.get("socks_tcp_connect") or "unknown")
    return {
        "true": "Reachable",
        "false": "Unreachable",
        "unknown": "Not checked",
    }.get(value, truncate_display_value(value, limit=24))


def _last_action_label(last_action: dict[str, object] | None) -> str:
    if not isinstance(last_action, dict) or not last_action:
        return "No action recorded in this session."
    title = str(last_action.get("title") or last_action.get("key") or "Last action")
    summary = _coerce_optional_str(last_action.get("summary"))
    if summary:
        return summary
    return title


def _latency_label(value: object) -> str:
    if isinstance(value, int):
        return f"{value} ms"
    return "-"


def _stage_label(stage: str) -> str:
    if not stage:
        return "Unknown"
    mapping = {
        "full_access": "Passed",
        "home_only": "Home page only",
        "blocked": "Blocked",
        "transport_failed": "Transport failed",
    }
    return mapping.get(stage, stage.replace("_", " ").title())


def _stringify_field_value(value: object) -> str:
    if isinstance(value, bool):
        return "Enabled" if value else "Disabled"
    return truncate_display_value(str(value), limit=40)
