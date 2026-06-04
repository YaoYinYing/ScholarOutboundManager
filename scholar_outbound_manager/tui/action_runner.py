"""ActionRunner abstractions and review-safe action journaling for the TUI."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Protocol

from scholar_outbound_manager.tui.artifact_rollback import create_artifact_snapshot
from scholar_outbound_manager.tui.commands import OperationSpec
from scholar_outbound_manager.tui.commands import preview_command
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ACTION_JOURNAL_PATH
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_ARTIFACT_SNAPSHOT_ROOT
from scholar_outbound_manager.tui.view_model import redact_text


SAFE_FAILURE_EXIT_CODE = 126
TIMEOUT_EXIT_CODE = 124


@dataclass(slots=True)
class ActionResult:
    key: str
    title: str
    command: list[str]
    started_at: str
    finished_at: str | None
    exit_code: int | None
    succeeded: bool
    stdout: str
    stderr: str
    redacted_stdout: str
    redacted_stderr: str
    summary: str
    expected_artifacts: list[str]
    warnings: list[str]
    snapshot_id: str | None = None
    rollback_hint: str | None = None


@dataclass(slots=True)
class ActionRunOptions:
    cwd: str | None = None
    timeout_seconds: float | None = None
    env: dict[str, str] | None = None
    allow_network: bool = False
    allow_systemd: bool = False
    allow_sensitive_artifact_write: bool = False
    snapshot_root: str | None = DEFAULT_TUI_ARTIFACT_SNAPSHOT_ROOT
    artifact_paths: dict[str, str] | None = None


class ActionRunner(Protocol):
    def run(self, spec: OperationSpec, options: ActionRunOptions) -> ActionResult:
        ...


class SubprocessActionRunner:
    """Execute one workflow operation through subprocess with safe redaction."""

    def run(self, spec: OperationSpec, options: ActionRunOptions) -> ActionResult:
        started_at = _utc_now_iso8601()
        gate_error = _gate_operation(spec, options)
        if gate_error is not None:
            return _failed_result(spec, started_at=started_at, exit_code=SAFE_FAILURE_EXIT_CODE, stderr=gate_error)
        snapshot_id = _maybe_snapshot(spec, options)
        env = None if options.env is None else {**os.environ, **options.env}
        try:
            completed = subprocess.run(
                spec.command,
                capture_output=True,
                text=True,
                timeout=options.timeout_seconds,
                cwd=options.cwd,
                env=env,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = "" if exc.stdout is None else str(exc.stdout)
            stderr = "" if exc.stderr is None else str(exc.stderr)
            return _build_result(
                spec,
                started_at=started_at,
                finished_at=_utc_now_iso8601(),
                exit_code=TIMEOUT_EXIT_CODE,
                stdout=stdout,
                stderr=stderr,
                warnings=["Operation timed out before completion."],
                snapshot_id=snapshot_id,
            )
        return _build_result(
            spec,
            started_at=started_at,
            finished_at=_utc_now_iso8601(),
            exit_code=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            warnings=[],
            snapshot_id=snapshot_id,
        )


class FakeActionRunner:
    """Return canned action results for tests without spawning subprocesses."""

    def __init__(self, canned_results: dict[str, ActionResult] | None = None) -> None:
        self._canned_results = {} if canned_results is None else dict(canned_results)

    def run(self, spec: OperationSpec, options: ActionRunOptions) -> ActionResult:
        del options
        canned = self._canned_results.get(spec.key)
        if canned is not None:
            return canned
        started_at = _utc_now_iso8601()
        return _build_result(
            spec,
            started_at=started_at,
            finished_at=started_at,
            exit_code=0,
            stdout="",
            stderr="",
            warnings=[],
        )


def redact_action_output(text: str) -> str:
    """Redact action output before exposing it to the TUI or its journal."""
    return redact_text(text)


def append_action_journal(
    result: ActionResult,
    *,
    journal_path: str | Path = DEFAULT_TUI_ACTION_JOURNAL_PATH,
) -> None:
    """Append one review-safe action journal row."""
    path = Path(journal_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "created_at": result.finished_at or result.started_at,
        "operation_key": result.key,
        "title": result.title,
        "command_preview": preview_command(result.command, max_length=None),
        "exit_code": result.exit_code,
        "succeeded": result.succeeded,
        "summary": result.summary,
        "redacted_stdout": result.redacted_stdout,
        "redacted_stderr": result.redacted_stderr,
        "expected_artifacts": list(result.expected_artifacts),
        "warnings": list(result.warnings),
        "snapshot_id": result.snapshot_id,
        "rollback_hint": result.rollback_hint,
    }
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(rendered)
        handle.write("\n")


def load_last_action(
    journal_path: str | Path = DEFAULT_TUI_ACTION_JOURNAL_PATH,
) -> dict[str, object] | None:
    """Load the last review-safe action journal entry if present."""
    path = Path(journal_path)
    if not path.exists():
        return None
    last_payload: dict[str, object] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            last_payload = {str(key): value for key, value in payload.items()}
    if last_payload is None:
        return None
    return {
        "key": last_payload.get("operation_key"),
        "title": last_payload.get("title"),
        "exit_code": last_payload.get("exit_code"),
        "succeeded": last_payload.get("succeeded"),
        "summary": str(last_payload.get("summary") or _legacy_summary_from_payload(last_payload)),
        "redacted_stdout_tail": _tail(str(last_payload.get("redacted_stdout") or "")),
        "redacted_stderr_tail": _tail(str(last_payload.get("redacted_stderr") or "")),
        "warnings": list(last_payload.get("warnings") or []),
        "snapshot_id": last_payload.get("snapshot_id"),
        "rollback_hint": last_payload.get("rollback_hint"),
    }


def _gate_operation(spec: OperationSpec, options: ActionRunOptions) -> str | None:
    if spec.network_access and not options.allow_network:
        return "Network operation refused without explicit allow_network confirmation."
    if spec.systemd_access and not options.allow_systemd:
        return "Systemd operation refused without explicit allow_systemd confirmation."
    if spec.sensitive_outputs and not options.allow_sensitive_artifact_write:
        return "Sensitive artifact write refused without explicit allow_sensitive_artifact_write confirmation."
    return None


def _build_result(
    spec: OperationSpec,
    *,
    started_at: str,
    finished_at: str,
    exit_code: int,
    stdout: str,
    stderr: str,
    warnings: list[str],
    snapshot_id: str | None = None,
) -> ActionResult:
    redacted_stdout = redact_action_output(stdout)
    redacted_stderr = redact_action_output(stderr)
    succeeded = exit_code in spec.success_exit_codes
    rollback_hint = None if succeeded or snapshot_id is None else "Use artifact rollback to restore previous local artifacts. This does not undo network or systemd side effects."
    return ActionResult(
        key=spec.key,
        title=spec.title,
        command=list(spec.command),
        started_at=started_at,
        finished_at=finished_at,
        exit_code=exit_code,
        succeeded=succeeded,
        stdout=stdout,
        stderr=stderr,
        redacted_stdout=redacted_stdout,
        redacted_stderr=redacted_stderr,
        summary=_summarize(spec, exit_code=exit_code, success=succeeded),
        expected_artifacts=list(spec.expected_artifacts),
        warnings=list(warnings),
        snapshot_id=snapshot_id,
        rollback_hint=rollback_hint,
    )


def _failed_result(
    spec: OperationSpec,
    *,
    started_at: str,
    exit_code: int,
    stderr: str,
) -> ActionResult:
    finished_at = _utc_now_iso8601()
    return _build_result(
        spec,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=exit_code,
        stdout="",
        stderr=stderr,
        warnings=[stderr],
    )


def _maybe_snapshot(spec: OperationSpec, options: ActionRunOptions) -> str | None:
    if spec.key not in {"fetch", "probe", "select", "pool_stage"}:
        return None
    if options.snapshot_root is None:
        return None
    snapshot = create_artifact_snapshot(
        reason=f"pre_{spec.key}",
        snapshot_root=options.snapshot_root,
        candidates_path=(options.artifact_paths or {}).get("candidates", "candidates.json"),
        probe_summary_path=(options.artifact_paths or {}).get("probe_summary", "state_data/probe_summary.json"),
        passed_candidates_path=(options.artifact_paths or {}).get("passed_candidates", "state_data/passed_candidates.json"),
        selected_candidate_path=(options.artifact_paths or {}).get("selected_candidate", "state_data/selected_candidate.json"),
        pool_plan_path=(options.artifact_paths or {}).get("pool_plan", "state_data/sidecar_pool_plan.json"),
    )
    return snapshot.snapshot_id


def _summarize(spec: OperationSpec, *, exit_code: object, success: bool) -> str:
    if success:
        return f"{spec.title} completed successfully."
    if exit_code == TIMEOUT_EXIT_CODE:
        if spec.key == "probe":
            return "Probe timed out or was interrupted. Artifacts may be stale. Run Test Nodes again or increase testing timeout."
        if spec.key == "fetch":
            return "Fetch timed out or was interrupted. Run Fetch Subscription again."
        return f"{spec.title} timed out or was interrupted."
    return f"{spec.title} failed with exit code {exit_code}."


def _legacy_summary_from_payload(payload: dict[str, object]) -> str:
    title = str(payload.get("title") or payload.get("operation_key") or "Action")
    exit_code = payload.get("exit_code")
    success = bool(payload.get("succeeded") is True)
    spec = OperationSpec(
        key=str(payload.get("operation_key") or "legacy"),
        title=title,
        command=["internal", "legacy_action"],
        requires_confirmation=False,
        network_access=False,
        systemd_access=False,
        sensitive_outputs=False,
        expected_artifacts=[],
    )
    return _summarize(spec, exit_code=exit_code, success=success)


def _tail(text: str, limit: int = 400) -> str:
    return text[-limit:] if len(text) > limit else text


def _utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
