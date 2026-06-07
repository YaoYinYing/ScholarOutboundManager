"""Structured state builders for the TUI Testing workbench."""

from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scholar_outbound_manager.selection import CandidateCatalogEntry
from scholar_outbound_manager.selection import infer_probe_passed
from scholar_outbound_manager.tui.config_centered import summarize_config_centered_state
from scholar_outbound_manager.tui.path_resolver import UserDataPaths
from scholar_outbound_manager.tui.testing_artifacts import TestingArtifacts
from scholar_outbound_manager.tui.testing_artifacts import load_testing_artifacts
from scholar_outbound_manager.tui.testing_jobs import TestingJobState
from scholar_outbound_manager.tui.testing_jobs import idle_testing_job_state
from scholar_outbound_manager.tui.testing_runtime import TestingSummary


@dataclass(slots=True, frozen=True)
class CandidateTestRow:
    index: int
    candidate_id: str
    label: str
    region_hint: str | None
    protocol: str
    status_icon: str
    supported: bool
    experimental: bool
    attempted: bool
    passed: bool
    latency_ms: int | None
    home_status: int | None
    query_status: int | None
    stage: str | None
    markers: tuple[str, ...]
    selected_for_route: bool


@dataclass(slots=True, frozen=True)
class CandidateInspectorState:
    candidate_id: str | None
    label: str | None
    region_hint: str | None
    protocol: str | None
    scholar_stage: str | None
    home_status: int | None
    query_status: int | None
    latency_ms: int | None
    markers: tuple[str, ...]
    explanation: str
    selected_for_route: bool
    artifact_warning: str | None


@dataclass(slots=True, frozen=True)
class TestingScreenState:
    summary: TestingSummary
    rows: list[CandidateTestRow]
    selected_index: int | None
    inspector: CandidateInspectorState
    job_state: str
    progress_current: int
    progress_total: int
    log_lines: list[str]
    actions: dict[str, bool]
    last_exit_code: int | None
    last_failure_reason: str | None
    artifacts_stale: bool


def build_testing_screen_state(
    *,
    config_path: str,
    user_data_paths: UserDataPaths,
    selected_index: int | None = None,
) -> TestingScreenState:
    """Build the full Testing page state from canonical local artifacts."""

    config_summary = summarize_config_centered_state(config_path)
    selected_route_ids = {
        str(entry.get("candidate_id"))
        for entry in config_summary.route_entries
        if isinstance(entry, dict) and entry.get("candidate_id")
    }
    artifacts = load_testing_artifacts(user_data_paths)
    artifact_warning = artifacts.warnings[0] if artifacts.warnings else None
    rows = build_candidate_test_rows(
        candidates=artifacts.candidates,
        probe_records=artifacts.probe_results_by_candidate_id,
        passed_candidate_ids=artifacts.passed_ids,
        selected_route_ids=selected_route_ids,
        experimental_hysteria2=config_summary.experimental_hysteria2,
        artifacts_stale=artifacts.probe_summary_exists and not artifacts.lineage_consistent,
    )
    clamped_index = _clamp_selected_index(rows, selected_index)
    selected_row = None if clamped_index is None else rows[clamped_index]
    job = _build_testing_job_state(
        summary_exists=artifacts.probe_summary_exists,
        rows=rows,
        candidates_exist=artifacts.candidates_exists,
    )
    summary = _build_testing_summary(
        rows=rows,
        subscription_configured=config_summary.subscription_url_configured,
        artifacts=artifacts,
    )
    inspector = build_candidate_inspector(
        selected_row,
        artifact_warning=artifact_warning,
        empty_state_message=_resolve_empty_state_message(
            config_path=config_path,
            subscription_configured=config_summary.subscription_url_configured,
            summary=summary,
            rows=rows,
            artifacts_stale=bool(artifact_warning),
        ),
    )
    return TestingScreenState(
        summary=summary,
        rows=rows,
        selected_index=clamped_index,
        inspector=inspector,
        job_state=job.status,
        progress_current=job.current,
        progress_total=job.total,
        log_lines=_build_log_lines(user_data_paths, fallback_message=job.message, artifacts_stale=bool(artifact_warning)),
        actions={
            "fetch": config_summary.subscription_url_configured,
            "probe": summary.candidate_count > 0,
            "retest_failed": summary.failed_count > 0,
            "stop": job.can_cancel,
        },
        last_exit_code=_load_last_testing_exit_code(user_data_paths),
        last_failure_reason=_load_last_testing_failure_reason(user_data_paths),
        artifacts_stale=artifact_warning is not None,
    )


def build_candidate_test_rows(
    *,
    candidates: list[CandidateCatalogEntry],
    probe_records: dict[str, dict[str, object]] | None = None,
    passed_candidate_ids: set[str] | None = None,
    selected_route_ids: set[str] | None = None,
    experimental_hysteria2: bool = False,
    artifacts_stale: bool = False,
) -> list[CandidateTestRow]:
    """Build secret-safe candidate test rows from canonical artifacts."""

    probe_records = {} if probe_records is None else dict(probe_records)
    passed_candidate_ids = set() if passed_candidate_ids is None else set(passed_candidate_ids)
    selected_route_ids = set() if selected_route_ids is None else set(selected_route_ids)

    rows: list[CandidateTestRow] = []
    for entry in candidates:
        record = probe_records.get(entry.candidate_id, {})
        probe_payload = record.get("probe_payload")
        if not isinstance(probe_payload, dict):
            probe_payload = {}
        supported = bool(entry.supported)
        experimental_disabled = _is_experimental_disabled(
            entry=entry,
            experimental_hysteria2=experimental_hysteria2,
        )
        attempted = bool(record.get("attempted")) or bool(probe_payload)
        passed = entry.candidate_id in passed_candidate_ids or infer_probe_passed(probe_payload if probe_payload else None)
        stage = _resolve_stage(
            entry=entry,
            probe_payload=probe_payload,
            supported=supported,
            attempted=attempted,
            passed=passed,
            experimental_disabled=experimental_disabled,
            skipped=bool(record.get("skipped")),
            artifacts_stale=artifacts_stale and (attempted or bool(probe_payload)),
        )
        markers = tuple(_resolve_markers(entry=entry, probe_payload=probe_payload, stage=stage))
        rows.append(
            CandidateTestRow(
                index=entry.index,
                candidate_id=entry.candidate_id,
                label=entry.label or entry.source_label or "<unnamed>",
                region_hint=entry.region_hint,
                protocol=entry.protocol,
                status_icon=_status_icon(
                    supported=supported,
                    attempted=attempted,
                    passed=passed,
                    experimental_disabled=experimental_disabled,
                    artifacts_stale=artifacts_stale and (attempted or bool(probe_payload)),
                ),
                supported=supported,
                experimental=experimental_disabled,
                attempted=attempted,
                passed=passed,
                latency_ms=_coerce_optional_int(probe_payload.get("latency_ms")) or entry.latency_ms,
                home_status=_coerce_optional_int(probe_payload.get("home_status")) or entry.home_status,
                query_status=_coerce_optional_int(probe_payload.get("query_status")) or entry.query_status,
                stage=stage,
                markers=markers,
                selected_for_route=entry.candidate_id in selected_route_ids,
            )
        )
    return rows


def build_candidate_inspector(
    row: CandidateTestRow | None,
    *,
    artifact_warning: str | None,
    empty_state_message: str,
) -> CandidateInspectorState:
    """Build the selected candidate inspector state."""

    if row is None:
        return CandidateInspectorState(
            candidate_id=None,
            label=None,
            region_hint=None,
            protocol=None,
            scholar_stage=None,
            home_status=None,
            query_status=None,
            latency_ms=None,
            markers=(),
            explanation=empty_state_message,
            selected_for_route=False,
            artifact_warning=artifact_warning,
        )
    return CandidateInspectorState(
        candidate_id=_short_candidate_id(row.candidate_id),
        label=row.label,
        region_hint=row.region_hint,
        protocol=row.protocol,
        scholar_stage=row.stage,
        home_status=row.home_status,
        query_status=row.query_status,
        latency_ms=row.latency_ms,
        markers=row.markers,
        explanation=explain_probe_failure(
            row.markers,
            row.stage,
            protocol=row.protocol,
            experimental=row.experimental,
            attempted=row.attempted,
            passed=row.passed,
            supported=row.supported,
        ),
        selected_for_route=row.selected_for_route,
        artifact_warning=artifact_warning,
    )


def explain_probe_failure(
    markers: tuple[str, ...],
    stage: str | None,
    *,
    protocol: str | None = None,
    experimental: bool = False,
    attempted: bool = False,
    passed: bool = False,
    supported: bool = True,
) -> str:
    """Return a human-readable explanation for the selected candidate."""

    if stage == "stale":
        return "Probe command succeeded, but artifact lineage is still inconsistent. Check output paths and rerun Test Nodes."
    if experimental and protocol == "hysteria2":
        return "Hysteria2 via Xray is experimental and disabled by default after persistent transport EOF failures."
    if not supported:
        return "This candidate is not supported by the current runtime."
    if passed:
        return "Home and query both passed without failure markers."
    if not attempted:
        return "This candidate has not been tested yet."
    if "google_sorry" in markers:
        return "Google returned an anti-automation challenge. This node should not be used for Scholar query routes."
    if "stage_query_blocked" in markers or stage == "query_blocked":
        return "Scholar home may work, but query access is blocked."
    if "transport_error" in markers or "stage_transport_failed" in markers or stage == "transport_failed":
        return "The proxy transport failed before Scholar could be tested."
    if "http_403" in markers:
        return "Scholar returned HTTP 403."
    if stage == "home_blocked":
        return "Scholar home access is blocked before query validation could succeed."
    if stage == "timeout":
        return "The probe timed out before Scholar access could be classified."
    if stage == "server_error":
        return "Scholar or an upstream proxy returned a server error."
    return "This node needs review before it should be used for Scholar routes."


def testing_screen_state_to_dict(state: TestingScreenState) -> dict[str, object]:
    """Convert the structured testing state into a plain dict for workflow_state."""

    return {
        "summary": asdict(state.summary),
        "rows": [asdict(row) for row in state.rows],
        "selected_index": state.selected_index,
        "inspector": asdict(state.inspector),
        "job_state": state.job_state,
        "progress_current": state.progress_current,
        "progress_total": state.progress_total,
        "log_lines": list(state.log_lines),
        "actions": dict(state.actions),
        "last_exit_code": state.last_exit_code,
        "last_failure_reason": state.last_failure_reason,
        "artifacts_stale": state.artifacts_stale,
    }


def _build_testing_summary(
    *,
    rows: list[CandidateTestRow],
    subscription_configured: bool,
    artifacts: TestingArtifacts,
) -> TestingSummary:
    candidate_count = len(rows)
    supported_count = sum(1 for row in rows if row.supported)
    unsupported_count = sum(1 for row in rows if not row.supported and not row.experimental)
    experimental_disabled_count = sum(1 for row in rows if row.experimental)
    attempted_count = sum(1 for row in rows if row.attempted)
    passed_count = sum(1 for row in rows if row.passed)
    failed_count = sum(1 for row in rows if row.attempted and not row.passed)
    full_access_count = sum(1 for row in rows if row.stage == "full_access")
    query_blocked_count = sum(1 for row in rows if row.stage == "query_blocked")
    transport_failed_count = sum(1 for row in rows if row.stage == "transport_failed")
    skipped_count = sum(1 for row in rows if row.status_icon == "SKIP")
    pending_count = sum(1 for row in rows if row.status_icon == "PEND")
    running_count = sum(1 for row in rows if row.status_icon == "RUN")
    stale_count = sum(1 for row in rows if row.status_icon == "STALE")
    testable_count = sum(1 for row in rows if row.supported and not row.experimental)
    return TestingSummary(
        subscription_configured=subscription_configured,
        fetched_count=candidate_count,
        candidate_count=candidate_count,
        supported_count=supported_count,
        unsupported_count=unsupported_count,
        experimental_disabled_count=experimental_disabled_count,
        attempted_count=attempted_count,
        passed_count=passed_count,
        failed_count=failed_count,
        full_access_count=full_access_count,
        query_blocked_count=query_blocked_count,
        transport_failed_count=transport_failed_count,
        last_fetch_status="ready" if artifacts.candidates_exists else "missing",
        last_probe_status="stale" if artifacts.probe_summary_exists and not artifacts.lineage_consistent else ("ready" if artifacts.probe_summary_exists else "not_tested"),
        total_candidates=candidate_count,
        supported_candidates=supported_count,
        unsupported_candidates=unsupported_count,
        experimental_disabled=experimental_disabled_count,
        testable_candidates=testable_count,
        visible_rows=candidate_count,
        attempted=attempted_count,
        passed=passed_count,
        failed=failed_count,
        skipped=skipped_count,
        pending=pending_count,
        running=running_count,
        stale=stale_count,
        table_scope="all_candidates",
    )


def _build_testing_job_state(
    *,
    summary_exists: bool,
    rows: list[CandidateTestRow],
    candidates_exist: bool,
) -> TestingJobState:
    if summary_exists:
        return idle_testing_job_state(
            message=f"Completed. Tested {sum(1 for row in rows if row.attempted or row.stage == 'stale')} of {sum(1 for row in rows if row.supported)} supported nodes."
        )
    if candidates_exist:
        return idle_testing_job_state(message="Candidates fetched. Press Test Nodes.")
    return idle_testing_job_state(message="Idle. Fetch Subscription to populate candidates.")


def _build_log_lines(user_data_paths: UserDataPaths, *, fallback_message: str, artifacts_stale: bool) -> list[str]:
    journal_path = user_data_paths.action_journal
    if not journal_path.exists():
        return [fallback_message]
    lines: list[str] = []
    for payload in _iter_journal_rows(journal_path):
        operation_key = str(payload.get("operation_key") or "")
        if operation_key not in {"fetch", "probe", "tui_safe_error"}:
            continue
        title = str(payload.get("title") or operation_key or "operation")
        summary = str(payload.get("summary") or "")
        stderr_tail = str(payload.get("redacted_stderr") or "")
        stdout_tail = str(payload.get("redacted_stdout") or "")
        lines.append(f"{title}: {summary or 'completed'}")
        if operation_key == "probe" and payload.get("succeeded") is True and artifacts_stale:
            lines.append("Probe command succeeded, but artifact lineage is still inconsistent.")
        if stdout_tail:
            lines.append(stdout_tail.splitlines()[-1])
        if stderr_tail:
            lines.append(stderr_tail.splitlines()[-1])
        if len(lines) >= 6:
            break
    return lines or [fallback_message]


def _load_last_testing_exit_code(user_data_paths: UserDataPaths) -> int | None:
    for payload in _iter_journal_rows(user_data_paths.action_journal):
        if str(payload.get("operation_key") or "") not in {"fetch", "probe"}:
            continue
        exit_code = payload.get("exit_code")
        if isinstance(exit_code, int):
            return exit_code
    return None


def _load_last_testing_failure_reason(user_data_paths: UserDataPaths) -> str | None:
    for payload in _iter_journal_rows(user_data_paths.action_journal):
        if str(payload.get("operation_key") or "") not in {"fetch", "probe"}:
            continue
        if payload.get("succeeded") is True:
            return None
        summary = payload.get("summary")
        if isinstance(summary, str) and summary:
            return summary
        break
    return None


def _iter_journal_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if not path.exists():
        return rows
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append({str(key): value for key, value in payload.items()})
    return rows


def _clamp_selected_index(rows: list[CandidateTestRow], selected_index: int | None) -> int | None:
    if not rows:
        return None
    if selected_index is None:
        return 0
    return max(0, min(len(rows) - 1, selected_index))


def _resolve_stage(
    *,
    entry: CandidateCatalogEntry,
    probe_payload: dict[str, object],
    supported: bool,
    attempted: bool,
    passed: bool,
    experimental_disabled: bool,
    skipped: bool,
    artifacts_stale: bool,
) -> str | None:
    if experimental_disabled:
        return "experimental_disabled"
    if not supported:
        return "unsupported"
    if artifacts_stale:
        return "stale"
    if passed:
        return "full_access"
    if skipped:
        return "skipped"
    if not attempted:
        return "pending"
    markers = list(probe_payload.get("failure_markers") or [])
    if "stage_query_blocked" in markers or "google_sorry" in markers:
        return "query_blocked"
    if "stage_transport_failed" in markers or _coerce_optional_str(probe_payload.get("error")):
        return "transport_failed"
    if "stage_home_blocked" in markers or _coerce_optional_int(probe_payload.get("home_status")) == 403:
        return "home_blocked"
    if "stage_timeout" in markers or probe_payload.get("timeout") is True:
        return "timeout"
    if any(status is not None and status >= 500 for status in (
        _coerce_optional_int(probe_payload.get("home_status")),
        _coerce_optional_int(probe_payload.get("query_status")),
    )):
        return "server_error"
    if entry.scholar_stage:
        return entry.scholar_stage
    return "review"


def _resolve_markers(
    *,
    entry: CandidateCatalogEntry,
    probe_payload: dict[str, object],
    stage: str | None,
) -> list[str]:
    markers = [str(marker) for marker in probe_payload.get("failure_markers") or [] if isinstance(marker, str)]
    if stage == "experimental_disabled":
        markers.append("disabled")
    if stage == "stale":
        markers.append("stale")
    if not markers:
        markers.extend(entry.failure_markers)
    return markers


def _status_icon(
    *,
    supported: bool,
    attempted: bool,
    passed: bool,
    experimental_disabled: bool,
    artifacts_stale: bool,
) -> str:
    if experimental_disabled:
        return "EXP"
    if not supported:
        return "UNSUP"
    if artifacts_stale:
        return "STALE"
    if passed:
        return "PASS"
    if attempted:
        return "FAIL"
    return "PEND"


def _resolve_empty_state_message(
    *,
    config_path: str,
    subscription_configured: bool,
    summary: TestingSummary,
    rows: list[CandidateTestRow],
    artifacts_stale: bool,
) -> str:
    if not Path(config_path).exists():
        return "No config.yaml found. Open Settings to create one."
    if not subscription_configured:
        return "No subscription URL configured. Open Settings."
    if summary.candidate_count == 0:
        return "No candidates fetched yet. Press Fetch Subscription."
    if artifacts_stale:
        return "Testing artifacts are stale. Run Test Nodes before changing routes."
    if rows and summary.attempted_count == 0:
        return "Candidates fetched. Press Test Nodes."
    if rows and summary.passed_count == 0:
        return "No Scholar-capable nodes passed. Review failure categories."
    return "Passed nodes are ready for Route."


def _is_experimental_disabled(*, entry: CandidateCatalogEntry, experimental_hysteria2: bool) -> bool:
    return entry.protocol == "hysteria2" and not entry.supported and not experimental_hysteria2


def _coerce_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _coerce_optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _short_candidate_id(candidate_id: str) -> str:
    return candidate_id if len(candidate_id) <= 18 else candidate_id[:18] + "..."
