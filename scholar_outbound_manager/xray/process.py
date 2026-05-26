"""Process helpers for local Xray execution."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from scholar_outbound_manager.state.atomic_write import atomic_write_json


@dataclass(slots=True)
class XrayCommandResult:
    """Represent one completed Xray command invocation."""

    command: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    error: str | None


@dataclass(slots=True)
class ManagedXrayProcess:
    """Represent one managed long-running Xray process."""

    command: list[str]
    process: subprocess.Popen[str]
    binary_path: str
    config_path: str
    pid_file_path: str | None = None

    def terminate(self, timeout_seconds: float = 5.0) -> None:
        """Terminate the managed process and wait until it exits."""
        try:
            if self.process.poll() is not None:
                self.process.wait(timeout=timeout_seconds)
                return

            self.process.terminate()
            try:
                self.process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        finally:
            _remove_pid_file(self.pid_file_path)


def build_xray_run_command(
    binary_path: str,
    config_path: str | Path,
    test_only: bool = False,
) -> list[str]:
    """Build one Xray command line for runtime execution or config testing."""
    if not binary_path:
        raise ValueError("binary_path must not be empty.")
    if not config_path:
        raise ValueError("config_path must not be empty.")

    command = [binary_path, "run", "-config", str(config_path)]
    if test_only:
        command.append("-test")
    return command


def test_xray_config(
    binary_path: str,
    config_path: str | Path,
    timeout_seconds: float = 10.0,
) -> XrayCommandResult:
    """Run an Xray config test command and capture the result."""
    command = build_xray_run_command(binary_path, config_path, test_only=True)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return XrayCommandResult(
            command=command,
            returncode=None,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            timed_out=True,
            error=f"Command timed out after {timeout_seconds} seconds.",
        )
    except FileNotFoundError:
        return XrayCommandResult(
            command=command,
            returncode=None,
            stdout="",
            stderr="",
            timed_out=False,
            error=f"Xray binary was not found: {binary_path}",
        )
    except OSError as exc:
        return XrayCommandResult(
            command=command,
            returncode=None,
            stdout="",
            stderr="",
            timed_out=False,
            error=str(exc),
        )

    return XrayCommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        timed_out=False,
        error=None,
    )


test_xray_config.__test__ = False


def start_xray(
    binary_path: str,
    config_path: str | Path,
    *,
    pid_file_path: str | Path | None = None,
) -> ManagedXrayProcess:
    """Start one long-running Xray process without waiting for completion."""
    resolved_binary_path = str(Path(binary_path).resolve())
    resolved_config_path = str(Path(config_path).resolve())
    resolved_pid_file_path = None if pid_file_path is None else str(Path(pid_file_path).resolve())
    command = build_xray_run_command(resolved_binary_path, resolved_config_path, test_only=False)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if resolved_pid_file_path is not None:
        write_managed_pid_file(
            resolved_pid_file_path,
            pid=process.pid,
            binary_path=resolved_binary_path,
            config_path=resolved_config_path,
        )
    return ManagedXrayProcess(
        command=command,
        process=process,
        binary_path=resolved_binary_path,
        config_path=resolved_config_path,
        pid_file_path=resolved_pid_file_path,
    )


def write_managed_pid_file(
    pid_file_path: str | Path,
    *,
    pid: int,
    binary_path: str | Path,
    config_path: str | Path,
) -> None:
    """Write one project-managed Xray pid file atomically."""
    atomic_write_json(
        pid_file_path,
        {
            "schema_version": 1,
            "pid": pid,
            "binary_path": str(Path(binary_path).resolve()),
            "config_path": str(Path(config_path).resolve()),
        },
    )


def read_managed_pid_file(path: str | Path) -> dict[str, object] | None:
    """Read one managed pid file if it exists and is valid JSON."""
    pid_path = Path(path)
    if not pid_path.exists():
        return None
    try:
        payload = json.loads(pid_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): value for key, value in payload.items()}


def is_managed_xray_process_alive(
    pid_file_path: str | Path,
    *,
    expected_binary_path: str | Path,
    expected_config_path: str | Path | None = None,
) -> bool:
    """Check whether one managed pid file still points at the expected Xray process."""
    payload = read_managed_pid_file(pid_file_path)
    if payload is None:
        return False

    pid = payload.get("pid")
    if not isinstance(pid, int):
        return False

    resolved_binary_path = str(Path(expected_binary_path).resolve())
    resolved_config_path = (
        None if expected_config_path is None else str(Path(expected_config_path).resolve())
    )
    pid_binary_path = _normalize_payload_path(payload.get("binary_path"))
    pid_config_path = _normalize_payload_path(payload.get("config_path"))
    if pid_binary_path != resolved_binary_path:
        return False
    if resolved_config_path is not None and pid_config_path != resolved_config_path:
        return False

    process_alive = _pid_exists(pid)
    if not process_alive:
        return False

    proc_binary_path = _read_proc_exe_path(pid)
    if proc_binary_path is not None and proc_binary_path != resolved_binary_path:
        return False

    if resolved_config_path is None:
        return True

    proc_cmdline = _read_proc_cmdline(pid)
    if proc_cmdline is not None:
        return resolved_config_path in proc_cmdline
    return pid_config_path == resolved_config_path


def terminate_managed_xray_from_pid_file(
    pid_file_path: str | Path,
    *,
    expected_binary_path: str | Path,
    expected_config_path: str | Path | None = None,
    timeout_seconds: float = 3.0,
) -> bool:
    """Terminate one managed Xray process only when pid-file ownership matches."""
    pid_path = Path(pid_file_path)
    payload = read_managed_pid_file(pid_path)
    if payload is None:
        return False

    pid = payload.get("pid")
    if not isinstance(pid, int):
        _remove_pid_file(pid_path)
        return False

    resolved_binary_path = str(Path(expected_binary_path).resolve())
    resolved_config_path = (
        None if expected_config_path is None else str(Path(expected_config_path).resolve())
    )
    pid_binary_path = _normalize_payload_path(payload.get("binary_path"))
    pid_config_path = _normalize_payload_path(payload.get("config_path"))
    if pid_binary_path != resolved_binary_path:
        return False
    if resolved_config_path is not None and pid_config_path != resolved_config_path:
        return False
    if not _pid_exists(pid):
        _remove_pid_file(pid_path)
        return False

    proc_binary_path = _read_proc_exe_path(pid)
    if proc_binary_path is not None and proc_binary_path != resolved_binary_path:
        return False

    if resolved_config_path is not None:
        proc_cmdline = _read_proc_cmdline(pid)
        if proc_cmdline is not None and resolved_config_path not in proc_cmdline:
            return False

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _remove_pid_file(pid_path)
        return False
    except PermissionError:
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            _remove_pid_file(pid_path)
            return True
        time.sleep(0.05)

    if _pid_exists(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            _remove_pid_file(pid_path)
            return True
        time.sleep(0.05)

    return False


def _normalize_payload_path(value: object) -> str | None:
    """Normalize one pid-file path payload to a resolved absolute string."""
    if not isinstance(value, str) or not value:
        return None
    return str(Path(value).resolve())


def _pid_exists(pid: int) -> bool:
    """Check whether one pid exists without scanning other processes."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_proc_exe_path(pid: int) -> str | None:
    """Read one process executable path from /proc when available."""
    proc_exe = Path("/proc") / str(pid) / "exe"
    if not proc_exe.exists():
        return None
    try:
        return str(proc_exe.resolve())
    except OSError:
        return None


def _read_proc_cmdline(pid: int) -> list[str] | None:
    """Read one process command line from /proc when available."""
    proc_cmdline = Path("/proc") / str(pid) / "cmdline"
    if not proc_cmdline.exists():
        return None
    try:
        raw_bytes = proc_cmdline.read_bytes()
    except OSError:
        return None
    if not raw_bytes:
        return []
    return [
        chunk.decode("utf-8", errors="replace")
        for chunk in raw_bytes.split(b"\0")
        if chunk
    ]


def _remove_pid_file(pid_file_path: str | Path | None) -> None:
    """Best-effort removal for one managed pid file."""
    if pid_file_path is None:
        return
    try:
        Path(pid_file_path).unlink(missing_ok=True)
    except OSError:
        pass
