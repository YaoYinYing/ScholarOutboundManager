"""Tests for Xray process and command wrappers."""

from __future__ import annotations

import os
from pathlib import Path

from scholar_outbound_manager.xray.process import ManagedXrayProcess
from scholar_outbound_manager.xray.process import build_xray_run_command
from scholar_outbound_manager.xray.process import is_managed_xray_process_alive
from scholar_outbound_manager.xray.process import read_managed_pid_file
from scholar_outbound_manager.xray.process import start_xray
from scholar_outbound_manager.xray.process import terminate_managed_xray_from_pid_file
from scholar_outbound_manager.xray.process import test_xray_config
from scholar_outbound_manager.xray.process import write_managed_pid_file


def test_build_xray_run_command_builds_default_command(tmp_path) -> None:
    """Build the default Xray run command."""
    command = build_xray_run_command("xray", tmp_path / "runtime.json")

    assert command == ["xray", "run", "-config", str(tmp_path / "runtime.json")]


def test_build_xray_run_command_adds_test_flag(tmp_path) -> None:
    """Append the test flag when requested."""
    command = build_xray_run_command("xray", tmp_path / "runtime.json", test_only=True)

    assert command[-1] == "-test"


def test_build_xray_run_command_requires_binary_path(tmp_path) -> None:
    """Reject empty binary paths."""
    import pytest

    with pytest.raises(ValueError, match="binary_path"):
        build_xray_run_command("", tmp_path / "runtime.json")


def test_build_xray_run_command_requires_config_path() -> None:
    """Reject empty config paths."""
    import pytest

    with pytest.raises(ValueError, match="config_path"):
        build_xray_run_command("xray", "")


def test_test_xray_config_captures_success(tmp_path) -> None:
    """Capture a successful fake Xray config test."""
    fake_binary = _write_fake_binary(tmp_path)
    result = test_xray_config(str(fake_binary), tmp_path / "runtime.json")

    assert result.returncode == 0
    assert result.timed_out is False
    assert result.error is None
    assert "mode=success" in result.stdout


def test_test_xray_config_captures_failure(tmp_path) -> None:
    """Capture a failed fake Xray config test."""
    fake_binary = _write_fake_binary(tmp_path, mode="fail")
    result = test_xray_config(str(fake_binary), tmp_path / "runtime.json")

    assert result.returncode == 9
    assert result.timed_out is False
    assert "mode=fail" in result.stderr


def test_test_xray_config_reports_timeout(tmp_path) -> None:
    """Return a timeout result instead of raising an exception."""
    fake_binary = _write_fake_binary(tmp_path, mode="sleep")
    result = test_xray_config(
        str(fake_binary),
        tmp_path / "runtime.json",
        timeout_seconds=0.2,
    )

    assert result.returncode is None
    assert result.timed_out is True
    assert result.error is not None
    assert "timed out" in result.error.lower()


def test_test_xray_config_reports_missing_binary(tmp_path) -> None:
    """Return a readable error when the binary does not exist."""
    missing_binary = tmp_path / "missing-xray"
    result = test_xray_config(str(missing_binary), tmp_path / "runtime.json")

    assert result.returncode is None
    assert result.timed_out is False
    assert result.error is not None
    assert str(missing_binary) in result.error


def test_start_xray_starts_fake_long_running_process_and_writes_pid_file(tmp_path) -> None:
    """Start a fake long-running process and record managed ownership."""
    fake_binary = _write_fake_binary(tmp_path, mode="loop")
    pid_file_path = tmp_path / "managed.pid.json"
    managed = start_xray(
        str(fake_binary),
        tmp_path / "runtime.json",
        pid_file_path=pid_file_path,
    )
    try:
        assert isinstance(managed, ManagedXrayProcess)
        assert managed.process.poll() is None
        assert managed.binary_path == str(fake_binary.resolve())
        assert managed.config_path == str((tmp_path / "runtime.json").resolve())
        assert managed.pid_file_path == str(pid_file_path.resolve())

        payload = read_managed_pid_file(pid_file_path)
        assert payload is not None
        assert payload["pid"] == managed.process.pid
        assert payload["binary_path"] == str(fake_binary.resolve())
        assert payload["config_path"] == str((tmp_path / "runtime.json").resolve())
    finally:
        managed.terminate()


def test_managed_xray_process_terminate_stops_process_and_removes_pid_file(tmp_path) -> None:
    """Terminate a managed fake process cleanly."""
    fake_binary = _write_fake_binary(tmp_path, mode="loop")
    pid_file_path = tmp_path / "managed.pid.json"
    managed = start_xray(
        str(fake_binary),
        tmp_path / "runtime.json",
        pid_file_path=pid_file_path,
    )

    managed.terminate(timeout_seconds=1.0)

    assert managed.process.poll() is not None
    assert not pid_file_path.exists()


def test_managed_xray_process_terminate_is_idempotent(tmp_path) -> None:
    """Allow repeated termination calls without errors."""
    fake_binary = _write_fake_binary(tmp_path, mode="loop")
    pid_file_path = tmp_path / "managed.pid.json"
    managed = start_xray(
        str(fake_binary),
        tmp_path / "runtime.json",
        pid_file_path=pid_file_path,
    )

    managed.terminate(timeout_seconds=1.0)
    managed.terminate(timeout_seconds=1.0)

    assert managed.process.poll() is not None
    assert not pid_file_path.exists()


def test_managed_xray_process_terminate_does_not_call_pkill_or_killall(tmp_path, monkeypatch) -> None:
    """Keep termination scoped to the managed Popen object."""
    fake_binary = _write_fake_binary(tmp_path, mode="loop")
    managed = start_xray(str(fake_binary), tmp_path / "runtime.json")

    def fail_popen(*args, **kwargs):
        raise AssertionError("terminate() must not spawn pkill/killall")

    monkeypatch.setattr("subprocess.Popen", fail_popen)
    managed.terminate(timeout_seconds=1.0)

    assert managed.process.poll() is not None


def test_is_managed_xray_process_alive_returns_true_for_matching_process(tmp_path) -> None:
    """Return true when pid-file ownership matches the live process."""
    fake_binary = _write_fake_binary(tmp_path, mode="loop")
    pid_file_path = tmp_path / "managed.pid.json"
    managed = start_xray(
        str(fake_binary),
        tmp_path / "runtime.json",
        pid_file_path=pid_file_path,
    )
    try:
        assert is_managed_xray_process_alive(
            pid_file_path,
            expected_binary_path=fake_binary,
            expected_config_path=tmp_path / "runtime.json",
        ) is True
    finally:
        managed.terminate()


def test_is_managed_xray_process_alive_rejects_mismatched_binary_path(tmp_path) -> None:
    """Reject pid-file ownership when the expected binary path differs."""
    fake_binary = _write_fake_binary(tmp_path, mode="loop")
    wrong_binary = _write_fake_binary(tmp_path, mode="success")
    pid_file_path = tmp_path / "managed.pid.json"
    managed = start_xray(
        str(fake_binary),
        tmp_path / "runtime.json",
        pid_file_path=pid_file_path,
    )
    try:
        assert is_managed_xray_process_alive(
            pid_file_path,
            expected_binary_path=wrong_binary,
            expected_config_path=tmp_path / "runtime.json",
        ) is False
    finally:
        managed.terminate()


def test_is_managed_xray_process_alive_rejects_mismatched_config_path(tmp_path) -> None:
    """Reject pid-file ownership when the expected config path differs."""
    fake_binary = _write_fake_binary(tmp_path, mode="loop")
    pid_file_path = tmp_path / "managed.pid.json"
    managed = start_xray(
        str(fake_binary),
        tmp_path / "runtime.json",
        pid_file_path=pid_file_path,
    )
    try:
        assert is_managed_xray_process_alive(
            pid_file_path,
            expected_binary_path=fake_binary,
            expected_config_path=tmp_path / "other-runtime.json",
        ) is False
    finally:
        managed.terminate()


def test_is_managed_xray_process_alive_returns_false_when_pid_file_missing(tmp_path) -> None:
    """Return false when the pid file does not exist."""
    assert is_managed_xray_process_alive(
        tmp_path / "missing.pid.json",
        expected_binary_path=tmp_path / "fake-xray",
    ) is False


def test_is_managed_xray_process_alive_uses_proc_checks_when_available(tmp_path, monkeypatch) -> None:
    """Accept a matching live process when /proc ownership matches expectations."""
    fake_binary = _write_fake_binary(tmp_path, mode="success")
    pid_file_path = tmp_path / "managed.pid.json"
    write_managed_pid_file(
        pid_file_path,
        pid=1234,
        binary_path=fake_binary,
        config_path=tmp_path / "runtime.json",
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.xray.process._pid_exists",
        lambda pid: True,
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.xray.process._read_proc_exe_path",
        lambda pid: str(fake_binary.resolve()),
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.xray.process._read_proc_cmdline",
        lambda pid: ["xray", "run", "-config", str((tmp_path / "runtime.json").resolve())],
    )

    assert is_managed_xray_process_alive(
        pid_file_path,
        expected_binary_path=fake_binary,
        expected_config_path=tmp_path / "runtime.json",
    ) is True


def test_is_managed_xray_process_alive_returns_false_for_proc_binary_mismatch(tmp_path, monkeypatch) -> None:
    """Reject a live pid when /proc reports the wrong executable path."""
    fake_binary = _write_fake_binary(tmp_path, mode="success")
    wrong_binary = _write_fake_binary(tmp_path, mode="fail")
    pid_file_path = tmp_path / "managed.pid.json"
    write_managed_pid_file(
        pid_file_path,
        pid=1234,
        binary_path=fake_binary,
        config_path=tmp_path / "runtime.json",
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.xray.process._pid_exists",
        lambda pid: True,
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.xray.process._read_proc_exe_path",
        lambda pid: str(wrong_binary.resolve()),
    )

    assert is_managed_xray_process_alive(
        pid_file_path,
        expected_binary_path=fake_binary,
        expected_config_path=tmp_path / "runtime.json",
    ) is False


def test_terminate_managed_xray_from_pid_file_does_not_kill_mismatched_binary(tmp_path) -> None:
    """Refuse to kill a live process when binary ownership does not match."""
    fake_binary = _write_fake_binary(tmp_path, mode="loop")
    wrong_binary = _write_fake_binary(tmp_path, mode="success")
    pid_file_path = tmp_path / "managed.pid.json"
    managed = start_xray(
        str(fake_binary),
        tmp_path / "runtime.json",
        pid_file_path=pid_file_path,
    )
    try:
        terminated = terminate_managed_xray_from_pid_file(
            pid_file_path,
            expected_binary_path=wrong_binary,
            expected_config_path=tmp_path / "runtime.json",
            timeout_seconds=0.2,
        )
        assert terminated is False
        assert managed.process.poll() is None
        assert pid_file_path.exists()
    finally:
        managed.terminate()


def test_terminate_managed_xray_from_pid_file_does_not_kill_mismatched_proc_binary(
    tmp_path,
    monkeypatch,
) -> None:
    """Refuse termination when /proc ownership does not match the expected binary."""
    fake_binary = _write_fake_binary(tmp_path, mode="success")
    pid_file_path = tmp_path / "managed.pid.json"
    write_managed_pid_file(
        pid_file_path,
        pid=1234,
        binary_path=fake_binary,
        config_path=tmp_path / "runtime.json",
    )
    kill_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "scholar_outbound_manager.xray.process._pid_exists",
        lambda pid: True,
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.xray.process._read_proc_exe_path",
        lambda pid: str((tmp_path / "other-xray").resolve()),
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.xray.process.os.kill",
        lambda pid, sig: kill_calls.append((pid, sig)),
    )

    terminated = terminate_managed_xray_from_pid_file(
        pid_file_path,
        expected_binary_path=fake_binary,
        expected_config_path=tmp_path / "runtime.json",
        timeout_seconds=0.1,
    )

    assert terminated is False
    assert kill_calls == []
    assert pid_file_path.exists()


def test_terminate_managed_xray_from_pid_file_removes_stale_pid_file_when_pid_missing(tmp_path) -> None:
    """Delete stale pid metadata when the process no longer exists."""
    fake_binary = _write_fake_binary(tmp_path, mode="success")
    pid_file_path = tmp_path / "managed.pid.json"
    write_managed_pid_file(
        pid_file_path,
        pid=999999,
        binary_path=fake_binary,
        config_path=tmp_path / "runtime.json",
    )

    terminated = terminate_managed_xray_from_pid_file(
        pid_file_path,
        expected_binary_path=fake_binary,
        expected_config_path=tmp_path / "runtime.json",
        timeout_seconds=0.2,
    )

    assert terminated is False
    assert not pid_file_path.exists()


def test_terminate_managed_xray_from_pid_file_kills_only_matching_pid(tmp_path, monkeypatch) -> None:
    """Terminate the owned live process and remove its pid file."""
    fake_binary = _write_fake_binary(tmp_path, mode="loop")
    pid_file_path = tmp_path / "managed.pid.json"
    write_managed_pid_file(
        pid_file_path,
        pid=1234,
        binary_path=fake_binary,
        config_path=tmp_path / "runtime.json",
    )
    pid_state = {"alive": True}
    kill_calls: list[tuple[int, int]] = []

    def fake_pid_exists(pid: int) -> bool:
        del pid
        return pid_state["alive"]

    def fake_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        pid_state["alive"] = False

    monkeypatch.setattr(
        "scholar_outbound_manager.xray.process._pid_exists",
        fake_pid_exists,
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.xray.process._read_proc_exe_path",
        lambda pid: str(fake_binary.resolve()),
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.xray.process._read_proc_cmdline",
        lambda pid: ["xray", "run", "-config", str((tmp_path / "runtime.json").resolve())],
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.xray.process.os.kill",
        fake_kill,
    )

    terminated = terminate_managed_xray_from_pid_file(
        pid_file_path,
        expected_binary_path=fake_binary,
        expected_config_path=tmp_path / "runtime.json",
        timeout_seconds=1.0,
    )
    assert terminated is True
    assert kill_calls == [(1234, 15)]
    assert not pid_file_path.exists()


def test_read_managed_pid_file_returns_none_for_invalid_json(tmp_path) -> None:
    """Treat invalid pid-file JSON as absent ownership metadata."""
    pid_file_path = tmp_path / "managed.pid.json"
    pid_file_path.write_text("{invalid", encoding="utf-8")

    assert read_managed_pid_file(pid_file_path) is None


def test_helpers_do_not_print_stdout_or_stderr(tmp_path, capsys) -> None:
    """Keep pid-file helpers silent."""
    pid_file_path = tmp_path / "managed.pid.json"
    write_managed_pid_file(
        pid_file_path,
        pid=123,
        binary_path=tmp_path / "xray",
        config_path=tmp_path / "runtime.json",
    )
    read_managed_pid_file(pid_file_path)
    is_managed_xray_process_alive(
        pid_file_path,
        expected_binary_path=tmp_path / "xray",
        expected_config_path=tmp_path / "runtime.json",
    )
    pid_file_path.unlink()
    write_managed_pid_file(
        pid_file_path,
        pid=999999,
        binary_path=tmp_path / "xray",
        config_path=tmp_path / "runtime.json",
    )
    terminate_managed_xray_from_pid_file(
        pid_file_path,
        expected_binary_path=tmp_path / "xray",
        expected_config_path=tmp_path / "runtime.json",
        timeout_seconds=0.1,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def _write_fake_binary(tmp_path: Path, mode: str = "success") -> Path:
    """Write one fake Xray binary script for subprocess tests."""
    script_path = tmp_path / f"fake-xray-{mode}.py"
    script_path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "import signal",
                "import sys",
                "import time",
                "",
                f"MODE = {mode!r}",
                "",
                "def _handle_term(signum, frame):",
                "    raise SystemExit(0)",
                "",
                "signal.signal(signal.SIGTERM, _handle_term)",
                "",
                "if MODE == 'success':",
                "    print('mode=success stdout')",
                "    raise SystemExit(0)",
                "if MODE == 'fail':",
                "    print('mode=fail stderr', file=sys.stderr)",
                "    raise SystemExit(9)",
                "if MODE == 'sleep':",
                "    time.sleep(1.0)",
                "    raise SystemExit(0)",
                "if MODE == 'loop':",
                "    while True:",
                "        time.sleep(0.1)",
                "raise SystemExit(3)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    os.chmod(script_path, 0o755)
    return script_path
