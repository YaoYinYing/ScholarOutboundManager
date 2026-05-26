"""Helpers for isolated long-running Scholar SOCKS sidecar runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import XrayConfig
from scholar_outbound_manager.net import wait_for_tcp_endpoint
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.xray.outbound_builder import build_xray_outbound
from scholar_outbound_manager.xray.process import is_managed_xray_process_alive
from scholar_outbound_manager.xray.process import start_xray
from scholar_outbound_manager.xray.process import terminate_managed_xray_from_pid_file
from scholar_outbound_manager.xray.process import test_xray_config
from scholar_outbound_manager.xray.runtime_config import build_runtime_config_from_outbound
from scholar_outbound_manager.xray.runtime_config import write_runtime_config


@dataclass(slots=True)
class SidecarRuntimeOptions:
    """Define long-running Scholar SOCKS sidecar runtime options."""

    listen_host: str = "127.0.0.1"
    listen_port: int = 19080
    runtime_config_name: str = "scholar_sidecar_runtime.json"
    inbound_tag: str = "scholar-sidecar-socks-in"
    outbound_tag: str = "scholar-sidecar-out"
    pid_file_name: str = "scholar_sidecar.pid.json"
    metadata_file_name: str = "scholar_sidecar.status.json"


@dataclass(slots=True)
class SidecarRuntimeSummary:
    """Summarize one prepared or started sidecar runtime."""

    runtime_config_path: str
    pid_file_path: str
    metadata_file_path: str
    listen_host: str
    listen_port: int
    outbound_tag: str
    inbound_tag: str
    candidate_id: str | None
    candidate_protocol: str
    started: bool
    config_test_passed: bool | None
    error: str | None


def prepare_sidecar_runtime(
    candidate: CandidateProxy,
    xray_config: XrayConfig,
    options: SidecarRuntimeOptions,
    candidate_id: str | None = None,
) -> SidecarRuntimeSummary:
    """Prepare one isolated sidecar runtime config and safe metadata without starting Xray."""
    _validate_sidecar_options(options)
    outbound = build_xray_outbound(candidate, options.outbound_tag)
    runtime_config = build_runtime_config_from_outbound(
        outbound=outbound,
        listen_host=options.listen_host,
        listen_port=options.listen_port,
        inbound_tag=options.inbound_tag,
    )

    runtime_dir = Path(xray_config.runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_config_path = runtime_dir / options.runtime_config_name
    pid_file_path = runtime_dir / options.pid_file_name
    metadata_file_path = runtime_dir / options.metadata_file_name
    write_runtime_config(runtime_config_path, runtime_config)

    summary = SidecarRuntimeSummary(
        runtime_config_path=str(runtime_config_path),
        pid_file_path=str(pid_file_path),
        metadata_file_path=str(metadata_file_path),
        listen_host=options.listen_host,
        listen_port=options.listen_port,
        outbound_tag=options.outbound_tag,
        inbound_tag=options.inbound_tag,
        candidate_id=candidate_id,
        candidate_protocol=candidate.protocol,
        started=False,
        config_test_passed=None,
        error=None,
    )
    _write_sidecar_metadata(summary)
    return summary


def build_socks_outbound_snippet(
    listen_host: str,
    listen_port: int,
    tag: str = "scholar-sidecar-socks-out",
) -> dict[str, object]:
    """Build one production reference SOCKS outbound snippet for the sidecar."""
    if not listen_host:
        raise ValueError("listen_host must not be empty.")
    if listen_port <= 0:
        raise ValueError("listen_port must be greater than 0.")
    if not tag:
        raise ValueError("tag must not be empty.")
    return {
        "tag": tag,
        "protocol": "socks",
        "settings": {
            "servers": [
                {
                    "address": listen_host,
                    "port": listen_port,
                }
            ]
        },
    }


def start_sidecar_runtime(
    xray_config: XrayConfig,
    summary: SidecarRuntimeSummary,
    *,
    test_config_timeout_seconds: float | None = 10.0,
) -> SidecarRuntimeSummary:
    """Start one prepared sidecar runtime and wait for local SOCKS readiness."""
    if test_config_timeout_seconds is not None and test_config_timeout_seconds <= 0:
        raise ValueError("test_config_timeout_seconds must be greater than 0.")

    if test_config_timeout_seconds is not None:
        test_result = test_xray_config(
            binary_path=xray_config.binary_path,
            config_path=summary.runtime_config_path,
            timeout_seconds=test_config_timeout_seconds,
        )
        if test_result.returncode != 0 or test_result.timed_out or test_result.error is not None:
            failed_summary = _replace_summary(
                summary,
                started=False,
                config_test_passed=False,
                error="xray config test failed.",
            )
            _write_sidecar_metadata(failed_summary)
            return failed_summary
        config_test_passed: bool | None = True
    else:
        config_test_passed = None

    managed_process = start_xray(
        xray_config.binary_path,
        summary.runtime_config_path,
        pid_file_path=summary.pid_file_path,
    )
    try:
        ready = wait_for_tcp_endpoint(
            summary.listen_host,
            summary.listen_port,
            5.0,
        )
        if not ready:
            raise RuntimeError("SOCKS endpoint was not ready before the startup timeout expired.")

        started_summary = _replace_summary(
            summary,
            started=True,
            config_test_passed=config_test_passed,
            error=None,
        )
        _write_sidecar_metadata(started_summary, pid=managed_process.process.pid, started=True)
        return started_summary
    except Exception as exc:  # noqa: BLE001
        managed_process.terminate()
        failed_summary = _replace_summary(
            summary,
            started=False,
            config_test_passed=config_test_passed,
            error=str(exc),
        )
        _write_sidecar_metadata(failed_summary)
        return failed_summary


def inspect_sidecar_runtime(
    pid_file_path: str | Path,
    *,
    expected_binary_path: str | Path,
    expected_config_path: str | Path | None = None,
) -> dict[str, object]:
    """Inspect one managed sidecar runtime strictly through its pid file."""
    pid_path = Path(pid_file_path)
    alive = is_managed_xray_process_alive(
        pid_path,
        expected_binary_path=expected_binary_path,
        expected_config_path=expected_config_path,
    )
    return {
        "pid_file_exists": pid_path.exists(),
        "alive": alive,
        "ownership_matched": alive,
    }


def stop_sidecar_runtime(
    pid_file_path: str | Path,
    *,
    expected_binary_path: str | Path,
    expected_config_path: str | Path | None = None,
) -> bool:
    """Stop one managed sidecar runtime when pid-file ownership matches."""
    return terminate_managed_xray_from_pid_file(
        pid_file_path,
        expected_binary_path=expected_binary_path,
        expected_config_path=expected_config_path,
    )


def _validate_sidecar_options(options: SidecarRuntimeOptions) -> None:
    """Validate one set of sidecar runtime options."""
    if not options.listen_host:
        raise ValueError("listen_host must not be empty.")
    if options.listen_port <= 0:
        raise ValueError("listen_port must be greater than 0.")
    for name, value in (
        ("runtime_config_name", options.runtime_config_name),
        ("pid_file_name", options.pid_file_name),
        ("metadata_file_name", options.metadata_file_name),
    ):
        _validate_plain_file_name(value, name)


def _validate_plain_file_name(value: str, field_name: str) -> None:
    """Validate that one sidecar file name is a plain file name."""
    if not value:
        raise ValueError(f"{field_name} must not be empty.")
    path = Path(value)
    if path.is_absolute() or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"{field_name} must be a plain file name.")


def _write_sidecar_metadata(
    summary: SidecarRuntimeSummary,
    *,
    pid: int | None = None,
    started: bool | None = None,
) -> None:
    """Write one safe sidecar metadata record."""
    payload: dict[str, object] = {
        "schema_version": 1,
        "candidate_id": summary.candidate_id,
        "candidate_protocol": summary.candidate_protocol,
        "listen_host": summary.listen_host,
        "listen_port": summary.listen_port,
        "runtime_config_path": summary.runtime_config_path,
        "pid_file_path": summary.pid_file_path,
        "outbound_tag": summary.outbound_tag,
        "inbound_tag": summary.inbound_tag,
        "prepared_at": _utc_now_iso8601(),
    }
    if started:
        payload["started"] = True
        payload["pid"] = pid
        payload["started_at"] = _utc_now_iso8601()
    else:
        payload["started"] = summary.started
    atomic_write_json(summary.metadata_file_path, payload)


def _replace_summary(
    summary: SidecarRuntimeSummary,
    *,
    started: bool,
    config_test_passed: bool | None,
    error: str | None,
) -> SidecarRuntimeSummary:
    """Build one updated sidecar summary without mutating the original instance."""
    return SidecarRuntimeSummary(
        runtime_config_path=summary.runtime_config_path,
        pid_file_path=summary.pid_file_path,
        metadata_file_path=summary.metadata_file_path,
        listen_host=summary.listen_host,
        listen_port=summary.listen_port,
        outbound_tag=summary.outbound_tag,
        inbound_tag=summary.inbound_tag,
        candidate_id=summary.candidate_id,
        candidate_protocol=summary.candidate_protocol,
        started=started,
        config_test_passed=config_test_passed,
        error=error,
    )


def _utc_now_iso8601() -> str:
    """Return one UTC timestamp with a Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
