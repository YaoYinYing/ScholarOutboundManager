"""Tests for TUI action runner abstractions and review-safe journaling."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scholar_outbound_manager.tui.action_runner import ActionResult
from scholar_outbound_manager.tui.action_runner import ActionRunOptions
from scholar_outbound_manager.tui.action_runner import FakeActionRunner
from scholar_outbound_manager.tui.action_runner import SubprocessActionRunner
from scholar_outbound_manager.tui.action_runner import append_action_journal
from scholar_outbound_manager.tui.commands import OperationSpec


def test_fake_action_runner_returns_canned_success() -> None:
    """Allow tests to inject canned action results without subprocesses."""
    canned = ActionResult(
        key="fetch",
        title="Fetch Candidates",
        command=["cmd"],
        started_at="2026-06-02T00:00:00Z",
        finished_at="2026-06-02T00:00:01Z",
        exit_code=0,
        succeeded=True,
        stdout="raw",
        stderr="",
        redacted_stdout="redacted",
        redacted_stderr="",
        summary="ok",
        expected_artifacts=["candidates.json"],
        warnings=[],
    )

    result = FakeActionRunner({"fetch": canned}).run(_spec("fetch"), ActionRunOptions())

    assert result.succeeded is True
    assert result.redacted_stdout == "redacted"


def test_subprocess_action_runner_can_run_harmless_local_command() -> None:
    """Run one harmless local Python command through the real subprocess runner."""
    spec = OperationSpec(
        key="local",
        title="Local Print",
        command=[sys.executable, "-c", "print('hello')"],
        requires_confirmation=False,
        network_access=False,
        systemd_access=False,
        sensitive_outputs=False,
        expected_artifacts=[],
    )

    result = SubprocessActionRunner().run(spec, ActionRunOptions())

    assert result.succeeded is True
    assert "hello" in result.redacted_stdout


def test_subprocess_action_runner_captures_exit_code_and_stderr() -> None:
    """Capture failing exit codes and stderr text."""
    spec = OperationSpec(
        key="fail",
        title="Failing Command",
        command=[sys.executable, "-c", "import sys; sys.stderr.write('oops\\n'); raise SystemExit(3)"],
        requires_confirmation=False,
        network_access=False,
        systemd_access=False,
        sensitive_outputs=False,
        expected_artifacts=[],
    )

    result = SubprocessActionRunner().run(spec, ActionRunOptions())

    assert result.succeeded is False
    assert result.exit_code == 3
    assert "oops" in result.redacted_stderr


def test_subprocess_action_runner_timeout_returns_failed_result() -> None:
    """Timeouts should produce a failed action result instead of hanging."""
    spec = OperationSpec(
        key="timeout",
        title="Timeout Command",
        command=[sys.executable, "-c", "import time; time.sleep(1)"],
        requires_confirmation=False,
        network_access=False,
        systemd_access=False,
        sensitive_outputs=False,
        expected_artifacts=[],
    )

    result = SubprocessActionRunner().run(spec, ActionRunOptions(timeout_seconds=0.01))

    assert result.succeeded is False
    assert result.exit_code == 124


def test_subprocess_action_runner_redacts_stdout_and_stderr() -> None:
    """Review-safe fields must hide secret-bearing output."""
    spec = OperationSpec(
        key="redact",
        title="Redact Output",
        command=[
            sys.executable,
            "-c",
            "import sys; print('https://example.invalid/subscription-token vless://secret@example.invalid'); "
            "sys.stderr.write('uuid=00000000-0000-0000-0000-000000000000 password=PASSWORD auth=AUTH token=TOKEN')",
        ],
        requires_confirmation=False,
        network_access=False,
        systemd_access=False,
        sensitive_outputs=False,
        expected_artifacts=[],
    )

    result = SubprocessActionRunner().run(spec, ActionRunOptions())

    assert "subscription-token" not in result.redacted_stdout
    assert "vless://" not in result.redacted_stdout
    assert "00000000-0000-0000-0000-000000000000" not in result.redacted_stderr
    assert "PASSWORD" not in result.redacted_stderr
    assert "AUTH" not in result.redacted_stderr
    assert "TOKEN" not in result.redacted_stderr


def test_action_journal_writes_only_redacted_output(tmp_path: Path) -> None:
    """The TUI action journal should remain review-safe."""
    result = ActionResult(
        key="probe",
        title="Probe Candidates",
        command=["scholar-outbound-manager", "probe"],
        started_at="2026-06-02T00:00:00Z",
        finished_at="2026-06-02T00:00:01Z",
        exit_code=0,
        succeeded=True,
        stdout="https://example.invalid/subscription-token",
        stderr="vless://secret@example.invalid password=PASSWORD",
        redacted_stdout="<REDACTED_URL>",
        redacted_stderr="<REDACTED_URI> password=<REDACTED>",
        summary="ok",
        expected_artifacts=["state_data/probe_summary.json"],
        warnings=[],
    )

    journal_path = tmp_path / "state_data" / "tui" / "action_journal.jsonl"
    append_action_journal(result, journal_path=journal_path)

    payload = json.loads(journal_path.read_text(encoding="utf-8").strip())
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert "subscription-token" not in rendered
    assert "vless://" not in rendered
    assert "PASSWORD" not in rendered
    assert "<REDACTED_URL>" in rendered


def test_subprocess_action_runner_blocks_network_without_explicit_allow() -> None:
    """Network actions should fail closed unless the caller explicitly allows them."""
    result = SubprocessActionRunner().run(_spec("fetch"), ActionRunOptions())

    assert result.succeeded is False
    assert result.exit_code == 126


def _spec(key: str) -> OperationSpec:
    return OperationSpec(
        key=key,
        title=key.title(),
        command=["echo", key],
        requires_confirmation=True,
        network_access=(key == "fetch"),
        systemd_access=False,
        sensitive_outputs=False,
        expected_artifacts=[],
    )
