"""Tests for Xray process and command wrappers."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from scholar_outbound_manager.xray.process import ManagedXrayProcess
from scholar_outbound_manager.xray.process import build_xray_run_command
from scholar_outbound_manager.xray.process import start_xray
from scholar_outbound_manager.xray.process import test_xray_config


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


def test_start_xray_starts_fake_long_running_process(tmp_path) -> None:
    """Start a fake long-running process without waiting for completion."""
    fake_binary = _write_fake_binary(tmp_path, mode="loop")
    managed = start_xray(str(fake_binary), tmp_path / "runtime.json")
    try:
        assert isinstance(managed, ManagedXrayProcess)
        assert managed.process.poll() is None
    finally:
        managed.terminate()


def test_managed_xray_process_terminate_stops_process(tmp_path) -> None:
    """Terminate a managed fake process cleanly."""
    fake_binary = _write_fake_binary(tmp_path, mode="loop")
    managed = start_xray(str(fake_binary), tmp_path / "runtime.json")

    managed.terminate(timeout_seconds=1.0)

    assert managed.process.poll() is not None


def test_managed_xray_process_terminate_is_idempotent(tmp_path) -> None:
    """Allow repeated termination calls without errors."""
    fake_binary = _write_fake_binary(tmp_path, mode="loop")
    managed = start_xray(str(fake_binary), tmp_path / "runtime.json")

    managed.terminate(timeout_seconds=1.0)
    managed.terminate(timeout_seconds=1.0)

    assert managed.process.poll() is not None


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
