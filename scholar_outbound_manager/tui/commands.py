"""Command previews and command-adapter helpers for the optional TUI."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Callable

from scholar_outbound_manager.tui.view_model import redact_text


@dataclass(slots=True)
class CommandExecutionResult:
    """Represent one redacted command execution result."""

    argv: list[str]
    command_preview: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


RunnerCallable = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(slots=True)
class OperationSpec:
    """Describe one future executable TUI workflow operation."""

    key: str
    title: str
    command: list[str]
    requires_confirmation: bool
    network_access: bool
    systemd_access: bool
    sensitive_outputs: bool
    expected_artifacts: list[str]


def run_command(
    argv: list[str],
    *,
    timeout_seconds: float | None = None,
    runner: RunnerCallable = subprocess.run,
) -> CommandExecutionResult:
    """Run one command without a shell and return redacted output."""
    try:
        completed = runner(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandExecutionResult(
            argv=list(argv),
            command_preview=preview_command(argv),
            exit_code=124,
            stdout=redact_text("" if exc.stdout is None else str(exc.stdout)),
            stderr=redact_text("" if exc.stderr is None else str(exc.stderr)),
            timed_out=True,
        )
    return CommandExecutionResult(
        argv=list(argv),
        command_preview=preview_command(argv),
        exit_code=int(completed.returncode),
        stdout=redact_text(completed.stdout or ""),
        stderr=redact_text(completed.stderr or ""),
        timed_out=False,
    )


def preview_command(argv: list[str]) -> str:
    """Render one copy-friendly command preview."""
    return " ".join(shlex.quote(part) for part in argv)


def build_fetch_command(
    *,
    config_path: str = "config.yaml",
    output_path: str = "candidates.json",
) -> list[str]:
    return [
        "scholar-outbound-manager",
        "fetch",
        "--config",
        config_path,
        "--output",
        output_path,
        "--allow-network-fetch",
    ]


def build_probe_command(
    *,
    config_path: str = "config.yaml",
    candidates_path: str = "candidates.json",
    summary_output: str = "state_data/probe_summary.json",
    passed_candidates_output: str = "state_data/passed_candidates.json",
    parallel_workers: int = 2,
    keep_all_passed: bool = True,
    query: str = "ppr",
    request_timeout: float = 20.0,
    transport_retry_count: int = 2,
    transport_retry_backoff: float = 1.5,
    hysteria2_warmup_attempts: int = 1,
) -> list[str]:
    argv = [
        "scholar-outbound-manager",
        "probe",
        "--config",
        config_path,
        "--candidates",
        candidates_path,
        "--summary-output",
        summary_output,
        "--passed-candidates-output",
        passed_candidates_output,
        "--parallel",
        str(parallel_workers),
    ]
    if keep_all_passed:
        argv.append("--keep-all-passed")
    argv.extend(
        [
            "--query",
            query,
            "--request-timeout",
            _format_float(request_timeout),
            "--transport-retry-count",
            str(transport_retry_count),
            "--transport-retry-backoff",
            _format_float(transport_retry_backoff),
            "--hysteria2-warmup-attempts",
            str(hysteria2_warmup_attempts),
            "--allow-network-probe",
        ]
    )
    return argv


def build_artifact_check_command(
    *,
    candidates_path: str = "candidates.json",
    probe_summary_path: str = "state_data/probe_summary.json",
    passed_candidates_path: str = "state_data/passed_candidates.json",
) -> list[str]:
    return [
        "scholar-outbound-manager",
        "artifact",
        "check",
        "--candidates",
        candidates_path,
        "--probe-summary",
        probe_summary_path,
        "--passed-candidates",
        passed_candidates_path,
    ]


def build_select_command(
    *,
    candidates_path: str = "state_data/passed_candidates.json",
    candidate_index: int = 0,
    output_path: str = "state_data/selected_candidate.json",
) -> list[str]:
    return [
        "scholar-outbound-manager",
        "select",
        "choose",
        "--candidates",
        candidates_path,
        "--candidate-index",
        str(candidate_index),
        "--output",
        output_path,
    ]


def build_service_stage_command(
    *,
    config_path: str = "config.yaml",
    selected_candidate_path: str = "state_data/selected_candidate.json",
    listen_host: str = "127.0.0.1",
    listen_port: int = 19080,
    skip_xray_binary_copy: bool = True,
) -> list[str]:
    argv = [
        "scholar-outbound-manager",
        "sidecar",
        "service-stage",
        "--config",
        config_path,
        "--selected-candidate",
        selected_candidate_path,
        "--listen-host",
        listen_host,
        "--listen-port",
        str(listen_port),
    ]
    if skip_xray_binary_copy:
        argv.append("--skip-xray-binary-copy")
    return argv


def build_pool_stage_command(
    *,
    config_path: str = "config.yaml",
    candidates_path: str = "state_data/passed_candidates.json",
    plan_path: str = "state_data/sidecar_pool_plan.json",
) -> list[str]:
    return [
        "scholar-outbound-manager",
        "sidecar",
        "pool",
        "stage",
        "--config",
        config_path,
        "--candidates",
        candidates_path,
        "--plan",
        plan_path,
        "--skip-xray-binary-copy",
    ]


def build_service_restart_command(*, unit_name: str = "scholar-outbound-sidecar.service") -> list[str]:
    return [
        "scholar-outbound-manager",
        "sidecar",
        "service-restart",
        "--unit-name",
        unit_name,
    ]


def build_service_validate_command(*, unit_name: str = "scholar-outbound-sidecar.service") -> list[str]:
    return [
        "scholar-outbound-manager",
        "sidecar",
        "service-validate",
        "--unit-name",
        unit_name,
    ]


def build_service_snippet_command(
    *,
    listen_host: str = "127.0.0.1",
    listen_port: int = 19080,
    tag: str = "scholar-sidecar-socks-out",
) -> list[str]:
    return [
        "scholar-outbound-manager",
        "sidecar",
        "service-snippet",
        "--listen-host",
        listen_host,
        "--listen-port",
        str(listen_port),
        "--tag",
        tag,
    ]


def build_snippet_warning() -> str:
    return "These snippets are not automatically written to production Xray/XrayR."


def _format_float(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)
