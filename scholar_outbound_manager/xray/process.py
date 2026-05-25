"""Process helpers for local Xray execution."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


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
    config_path: Path

    def terminate(self, timeout_seconds: float = 5.0) -> None:
        """Terminate the managed process and wait until it exits."""
        if self.process.poll() is not None:
            self.process.wait(timeout=timeout_seconds)
            return

        self.process.terminate()
        try:
            self.process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


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
) -> ManagedXrayProcess:
    """Start one long-running Xray process without waiting for completion."""
    command = build_xray_run_command(binary_path, config_path, test_only=False)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return ManagedXrayProcess(
        command=command,
        process=process,
        config_path=Path(config_path),
    )
