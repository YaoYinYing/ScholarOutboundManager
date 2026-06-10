"""Pure display view models for the TUI.

These are typed dataclasses built from SessionState or directly from
domain models.  They have no I/O, no mutation, and no Textual dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field


@dataclass(slots=True)
class HomeCard:
    title: str
    rows: list[tuple[str, str]]


@dataclass(slots=True)
class HomeViewModel:
    config_path: str
    user_data_dir: str
    cards: list[HomeCard]
    next_action: str
    wizard_active: bool = False


@dataclass(slots=True)
class SettingsViewModel:
    config_path: str
    user_data_dir: str
    subscription_url_masked: str
    subscription_user_agent: str
    xray_binary_path: str
    xray_binary_exists: bool
    fail_closed: bool
    experimental_hysteria2: bool
    service_name: str
    undo_available: bool
    redacted_diff: str | None
    probe_concurrency: int


@dataclass(slots=True)
class TestingTableRow:
    status_icon: str
    index: int
    region: str
    label: str
    protocol: str
    latency: str
    home: str
    query: str
    stage: str
    markers: str


@dataclass(slots=True)
class TestingTableViewModel:
    columns: list[str]
    rows: list[TestingTableRow]
    empty_message: str = "No candidates available."


@dataclass(slots=True)
class TestingViewModel:
    phase: str
    progress_current: int
    progress_total: int
    job_message: str
    subscription_configured: bool
    last_fetch_status: str
    candidate_count: int
    supported_count: int
    attempted_count: int
    passed_count: int
    failed_count: int
    query_blocked_count: int
    experimental_disabled_count: int
    table: TestingTableViewModel
    inspector: dict[str, str]
    stale_warning: str | None
    can_fetch: bool
    can_probe: bool
    can_retest: bool
    can_cancel: bool


@dataclass(slots=True)
class RouteTableRow:
    enabled: str
    name: str
    candidate: str
    region: str
    protocol: str
    host: str
    port: str
    port_status: str
    validation: str


@dataclass(slots=True)
class RouteTableViewModel:
    columns: list[str]
    rows: list[RouteTableRow]
    empty_message: str = "No routes configured."


@dataclass(slots=True)
class RouteViewModel:
    table: RouteTableViewModel
    selected_index: int
    selected_entry: dict[str, object]
    candidate_options: list[tuple[str, str]]
    candidate_selector_enabled: bool
    apply_available: bool
    service_name: str
    validation_errors: list[str]
    stale_warning: str | None


@dataclass(slots=True)
class LogsViewModel:
    action_rows: list[list[str]]
    snapshot_rows: list[list[str]]
    rollback_warning: list[str]
    last_action_summary: str | None
    snapshot_count: int


def build_home_view_model(state) -> HomeViewModel:
    """Build HomeScreen display model from SessionState."""
    s = state
    cards = [
        HomeCard(
            title="Subscription",
            rows=[
                ("Configured", "yes" if s.subscription_url_configured else "no"),
                ("URL", s.subscription_url_masked),
                ("Last fetch", s.testing_last_fetch_status or "unknown"),
                ("Candidates", str(s.testing_candidate_count)),
                ("Supported", str(s.testing_supported_count)),
            ],
        ),
        HomeCard(
            title="Testing",
            rows=[
                ("Tested", f"{s.testing_attempted_count} / {s.testing_supported_count}"),
                ("Passed", str(s.testing_passed_count)),
                ("Failed", str(s.testing_failed_count)),
                ("Full access", str(s.testing_full_access_count)),
                ("Query blocked", str(s.testing_query_blocked_count)),
                ("Last probe", s.testing_last_probe_status or "unknown"),
            ],
        ),
        HomeCard(
            title="Route",
            rows=[
                ("Routes enabled", f"{sum(1 for e in s.route_entries if e.enabled)} / {len(s.route_entries)}"),
                ("Ports", ", ".join(str(e.listen_port) for e in s.route_entries if e.enabled) or "none"),
                ("Selected", ", ".join(e.candidate_label for e in s.route_entries if e.enabled and e.candidate_label) or "none"),
            ],
        ),
        HomeCard(
            title="Sidecar",
            rows=[
                ("Service", s.sidecar_service_active),
                ("Enabled", s.sidecar_service_enabled),
                ("SOCKS", s.sidecar_socks_status),
                ("Last validation", s.sidecar_last_validation or "never"),
            ],
        ),
    ]
    return HomeViewModel(
        config_path=str(s.config_path),
        user_data_dir=str(s.user_data_paths.root),
        cards=cards,
        next_action=s.next_recommended_action,
    )


def build_testing_view_model(state) -> TestingViewModel:
    """Build TestingScreen display model from SessionState."""
    rows = []
    for r in state.testing_rows:
        rows.append(
            TestingTableRow(
                status_icon=r.status_icon,
                index=r.index,
                region=r.region_hint or "-",
                label=r.label,
                protocol=r.protocol,
                latency=f"{r.latency_ms}ms" if r.latency_ms is not None else "-",
                home=r.home_status,
                query=r.query_status,
                stage=r.stage,
                markers=", ".join(r.markers) if r.markers else "-",
            )
        )

    table = TestingTableViewModel(
        columns=["", "#", "Region", "Label", "Protocol", "Latency", "Home", "Query", "Stage", "Markers"],
        rows=rows,
    )

    # Inspector: selected row detail
    inspector: dict[str, str] = {}
    if state.testing_rows and 0 <= state.testing_selected_index < len(state.testing_rows):
        r = state.testing_rows[state.testing_selected_index]
        inspector = {
            "Label": r.label,
            "Region": r.region_hint or "-",
            "Protocol": r.protocol,
            "Stage": r.stage,
            "Home": r.home_status,
            "Query": r.query_status,
            "Latency": f"{r.latency_ms}ms" if r.latency_ms is not None else "-",
            "Markers": ", ".join(r.markers) if r.markers else "none",
            "Candidate ID": r.candidate_id,
            "Passed": "yes" if r.passed is True else ("no" if r.passed is False else "untested"),
            "Selected for route": "yes" if r.selected_for_route else "no",
        }

    return TestingViewModel(
        phase=state.testing_phase,
        progress_current=state.testing_progress_current,
        progress_total=state.testing_progress_total,
        job_message=state.testing_job_id or "idle",
        subscription_configured=state.subscription_url_configured,
        last_fetch_status=state.testing_last_fetch_status or "unknown",
        candidate_count=state.testing_candidate_count,
        supported_count=state.testing_supported_count,
        attempted_count=state.testing_attempted_count,
        passed_count=state.testing_passed_count,
        failed_count=state.testing_failed_count,
        query_blocked_count=state.testing_query_blocked_count,
        experimental_disabled_count=state.testing_experimental_disabled_count,
        table=table,
        inspector=inspector,
        stale_warning=state.testing_stale_warning,
        can_fetch=state.subscription_url_configured,
        can_probe=state.testing_candidate_count > 0,
        can_retest=state.testing_failed_count > 0,
        can_cancel=state.testing_phase in {"fetching", "probing"},
    )


def build_route_view_model(state) -> RouteViewModel:
    """Build RouteScreen display model from SessionState."""
    rows = []
    for i, e in enumerate(state.route_entries):
        rows.append(
            RouteTableRow(
                enabled="✓" if e.enabled else "✗",
                name=e.name,
                candidate=e.candidate_label or "(not selected)",
                region=e.region_hint or "-",
                protocol=e.protocol,
                host=e.listen_host,
                port=str(e.listen_port),
                port_status=e.port_status,
                validation=e.validation_status,
            )
        )

    table = RouteTableViewModel(
        columns=["On", "Name", "Candidate", "Region", "Protocol", "Host", "Port", "Port status", "Validation"],
        rows=rows,
    )

    selected_entry: dict[str, object] = {}
    if state.route_entries and 0 <= state.route_selected_index < len(state.route_entries):
        e = state.route_entries[state.route_selected_index]
        selected_entry = {
            "route_id": e.route_id,
            "name": e.name,
            "enabled": e.enabled,
            "candidate_id": e.candidate_id,
            "candidate_label": e.candidate_label,
            "listen_host": e.listen_host,
            "listen_port": e.listen_port,
        }

    candidate_options = [
        (f"{o.label} · {o.region_hint or '-'} · {o.protocol} · {o.stage}", o.candidate_id)
        for o in state.route_candidate_options
    ]

    return RouteViewModel(
        table=table,
        selected_index=state.route_selected_index,
        selected_entry=selected_entry,
        candidate_options=candidate_options,
        candidate_selector_enabled=bool(candidate_options) and state.route_stale_warning is None,
        apply_available=state.route_apply_available,
        service_name=state.service_name,
        validation_errors=list(state.route_validation_errors),
        stale_warning=state.route_stale_warning,
    )


def build_logs_view_model(state) -> LogsViewModel:
    """Build LogsScreen display model from SessionState."""
    action_rows = []
    for entry in state.action_history:
        status = "OK" if entry.succeeded else ("Failed" if entry.succeeded is False else "-")
        action_rows.append([
            entry.title or entry.key or "Action",
            status,
            (entry.summary or "")[:60],
        ])

    snapshot_rows = []
    # snapshots are loaded separately via services
    from scholar_outbound_manager.tui.artifact_rollback import list_artifact_snapshots
    snapshots = list_artifact_snapshots(str(state.user_data_paths.snapshot_root))
    for snap in snapshots[:12]:
        snapshot_rows.append([snap.snapshot_id, snap.reason])

    last_summary = None
    if isinstance(state.last_action, dict):
        last_summary = str(state.last_action.get("summary") or state.last_action.get("title") or "")

    return LogsViewModel(
        action_rows=action_rows,
        snapshot_rows=snapshot_rows,
        rollback_warning=[
            "Artifact rollback restores local artifacts only.",
            "It does not undo network effects.",
            "It does not restart sidecar.",
            "It does not modify production Xray/XrayR/x-ui.",
        ],
        last_action_summary=last_summary,
        snapshot_count=state.snapshot_count,
    )
