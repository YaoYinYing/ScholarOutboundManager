"""Single-candidate probe orchestration helpers."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Callable

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import ProbeResult
from scholar_outbound_manager.models import XrayConfig
from scholar_outbound_manager.net import wait_for_tcp_endpoint
from scholar_outbound_manager.probe.http_probe import HttpProbeResponse
from scholar_outbound_manager.probe.http_probe import HttpProbeTarget
from scholar_outbound_manager.probe.http_probe import SocksEndpoint
from scholar_outbound_manager.probe.http_probe import probe_http_via_socks
from scholar_outbound_manager.probe.scholar_classifier import build_scholar_home_target
from scholar_outbound_manager.probe.scholar_classifier import build_scholar_probe_result
from scholar_outbound_manager.probe.scholar_classifier import build_scholar_query_target
from scholar_outbound_manager.runtime import prepare_candidate_runtime
from scholar_outbound_manager.xray.process import ManagedXrayProcess
from scholar_outbound_manager.xray.process import XrayCommandResult
from scholar_outbound_manager.xray.process import start_xray
from scholar_outbound_manager.xray.process import test_xray_config


@dataclass(slots=True)
class CandidateProbeOptions:
    """Define options for one candidate probe workflow."""

    query: str = "ppr"
    startup_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 15.0
    xray_test_timeout_seconds: float | None = None
    runtime_config_name: str = "candidate_probe_runtime.json"
    probe_query: bool = True
    transport_retry_count: int = 0
    transport_retry_backoff_seconds: float = 1.0
    hysteria2_warmup_attempts: int = 0
    warmup_url: str = "https://www.gstatic.com/generate_204"


@dataclass(slots=True)
class CandidateProbeSummary:
    """Summarize one completed single-candidate probe workflow."""

    candidate_id: str
    runtime_config_path: str
    local_socks_host: str
    local_socks_port: int
    xray_started: bool
    xray_test_passed: bool | None
    startup_ready: bool
    result: ProbeResult
    attempt_count: int = 1
    transport_retry_count_used: int = 0
    warmup_attempt_count: int = 0
    final_attempt_index: int = 0


HttpProbeCallable = Callable[[HttpProbeTarget, SocksEndpoint, float], HttpProbeResponse]
StartXrayCallable = Callable[[str, str | Path, str | Path | None], ManagedXrayProcess]
TestXrayConfigCallable = Callable[[str, str | Path, float], XrayCommandResult]
WaitForTcpEndpointCallable = Callable[[str, int, float], bool]
SleepCallable = Callable[[float], None]


def probe_candidate(
    candidate: CandidateProxy,
    xray_config: XrayConfig,
    candidate_id: str,
    options: CandidateProbeOptions | None = None,
    http_probe: HttpProbeCallable = probe_http_via_socks,
    *,
    start_xray_func: StartXrayCallable = start_xray,
    test_xray_config_func: TestXrayConfigCallable = test_xray_config,
    wait_for_tcp_endpoint_func: WaitForTcpEndpointCallable = wait_for_tcp_endpoint,
    sleep_func: SleepCallable = time.sleep,
) -> CandidateProbeSummary:
    """Probe one candidate through runtime preparation, Xray startup, and Scholar requests."""
    probe_options = options or CandidateProbeOptions()
    _validate_probe_options(probe_options)

    try:
        runtime_summary = prepare_candidate_runtime(
            candidate=candidate,
            xray_config=xray_config,
            config_name=probe_options.runtime_config_name,
        )
    except ValueError as exc:
        return _summary_from_failure(
            candidate_id=candidate_id,
            runtime_config_path=str(Path(xray_config.runtime_dir) / probe_options.runtime_config_name),
            local_socks_host=xray_config.local_socks_host,
            local_socks_port=xray_config.local_socks_port,
            error=f"runtime preparation failed: {exc}",
            failure_markers=["runtime_prepare_failed"],
        )

    runtime_config_path = runtime_summary["runtime_config_path"]
    local_socks_host = runtime_summary["local_socks_host"]
    local_socks_port = runtime_summary["local_socks_port"]
    pid_file_path = _build_managed_xray_pid_file_path(xray_config.runtime_dir, candidate_id)

    if probe_options.xray_test_timeout_seconds is not None:
        test_result = test_xray_config_func(
            xray_config.binary_path,
            runtime_config_path,
            probe_options.xray_test_timeout_seconds,
        )
        if test_result.returncode != 0 or test_result.timed_out or test_result.error is not None:
            failure_detail = _describe_xray_config_test_failure(test_result)
            return _summary_from_failure(
                candidate_id=candidate_id,
                runtime_config_path=runtime_config_path,
                local_socks_host=local_socks_host,
                local_socks_port=local_socks_port,
                xray_test_passed=False,
                error=f"xray config test failed: {failure_detail}",
                failure_markers=["xray_config_test_failed"],
            )
        xray_test_passed: bool | None = True
    else:
        xray_test_passed = None

    try:
        managed_process = start_xray_func(
            xray_config.binary_path,
            runtime_config_path,
            pid_file_path=pid_file_path,
        )
    except (OSError, ValueError) as exc:
        return _summary_from_failure(
            candidate_id=candidate_id,
            runtime_config_path=runtime_config_path,
            local_socks_host=local_socks_host,
            local_socks_port=local_socks_port,
            xray_test_passed=xray_test_passed,
            error=f"xray start failed: {exc}",
            failure_markers=["xray_start_failed"],
        )

    startup_ready = False
    try:
        startup_ready = wait_for_tcp_endpoint_func(
            local_socks_host,
            local_socks_port,
            probe_options.startup_timeout_seconds,
        )
        if not startup_ready:
            return _summary_from_failure(
                candidate_id=candidate_id,
                runtime_config_path=runtime_config_path,
                local_socks_host=local_socks_host,
                local_socks_port=local_socks_port,
                xray_started=True,
                xray_test_passed=xray_test_passed,
                startup_ready=False,
                error="SOCKS endpoint was not ready before the startup timeout expired.",
                failure_markers=["socks_startup_timeout"],
                timeout=True,
            )

        socks_endpoint = SocksEndpoint(local_socks_host, local_socks_port)
        warmup_attempt_count = _run_optional_warmup(
            candidate=candidate,
            socks_endpoint=socks_endpoint,
            options=probe_options,
            http_probe=http_probe,
        )
        result, attempt_count, retries_used, final_attempt_index = _probe_with_transport_retries(
            candidate=candidate,
            candidate_id=candidate_id,
            socks_endpoint=socks_endpoint,
            options=probe_options,
            http_probe=http_probe,
            sleep_func=sleep_func,
        )
        return CandidateProbeSummary(
            candidate_id=candidate_id,
            runtime_config_path=runtime_config_path,
            local_socks_host=local_socks_host,
            local_socks_port=local_socks_port,
            xray_started=True,
            xray_test_passed=xray_test_passed,
            startup_ready=True,
            result=result,
            attempt_count=attempt_count,
            transport_retry_count_used=retries_used,
            warmup_attempt_count=warmup_attempt_count,
            final_attempt_index=final_attempt_index,
        )
    except Exception as exc:  # noqa: BLE001
        return _summary_from_failure(
            candidate_id=candidate_id,
            runtime_config_path=runtime_config_path,
            local_socks_host=local_socks_host,
            local_socks_port=local_socks_port,
            xray_started=True,
            xray_test_passed=xray_test_passed,
            startup_ready=startup_ready,
            error=f"probe exception: {exc}",
            failure_markers=["probe_exception"],
        )
    finally:
        managed_process.terminate()


def _validate_probe_options(options: CandidateProbeOptions) -> None:
    """Validate single-candidate probe options."""
    if options.startup_timeout_seconds <= 0:
        raise ValueError("startup_timeout_seconds must be greater than 0.")
    if options.request_timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds must be greater than 0.")
    if options.xray_test_timeout_seconds is not None and options.xray_test_timeout_seconds <= 0:
        raise ValueError("xray_test_timeout_seconds must be greater than 0.")
    if options.transport_retry_count < 0:
        raise ValueError("transport_retry_count must be greater than or equal to 0.")
    if options.transport_retry_backoff_seconds < 0:
        raise ValueError("transport_retry_backoff_seconds must be greater than or equal to 0.")
    if options.hysteria2_warmup_attempts < 0:
        raise ValueError("hysteria2_warmup_attempts must be greater than or equal to 0.")
    if not options.warmup_url:
        raise ValueError("warmup_url must not be empty.")
    _validate_runtime_config_name(options.runtime_config_name)


def is_transport_retryable_probe_result(result: ProbeResult) -> bool:
    """Return whether one probe result is safe to retry inside the same process."""
    non_retryable_markers = {
        "stage_query_blocked",
        "stage_home_blocked",
        "google_sorry",
        "automated_queries",
        "http_403",
        "http_429",
    }
    if any(marker in non_retryable_markers for marker in result.failure_markers):
        return False
    if "stage_transport_failed" in result.failure_markers:
        return True
    if "transport_error" in result.failure_markers:
        return True
    if result.timeout:
        return True
    error_text = (result.error or "").lower()
    return any(
        needle in error_text
        for needle in (
            "tls/ssl connection has been closed",
            "eof",
            "connection reset",
            "timed out",
            "timeout",
        )
    )


def _validate_runtime_config_name(config_name: str) -> None:
    """Validate that a runtime config name is a plain file name."""
    if not config_name:
        raise ValueError("runtime_config_name must not be empty.")
    config_path = Path(config_name)
    if config_path.is_absolute():
        raise ValueError("runtime_config_name must not be an absolute path.")
    if config_name in {".", ".."}:
        raise ValueError("runtime_config_name must be a file name.")
    if "/" in config_name or "\\" in config_name:
        raise ValueError("runtime_config_name must not contain path separators.")


def _build_managed_xray_pid_file_path(runtime_dir: str | Path, candidate_id: str) -> Path:
    """Build one sanitized managed Xray pid-file path under the runtime directory."""
    safe_candidate_id = re.sub(r"[^0-9A-Za-z]+", "_", candidate_id).strip("_")
    if not safe_candidate_id:
        safe_candidate_id = "candidate"
    return Path(runtime_dir) / f"managed_xray_{safe_candidate_id}.pid.json"


def _run_optional_warmup(
    *,
    candidate: CandidateProxy,
    socks_endpoint: SocksEndpoint,
    options: CandidateProbeOptions,
    http_probe: HttpProbeCallable,
) -> int:
    """Run optional warm-up requests through the active SOCKS tunnel."""
    if candidate.protocol.lower() != "hysteria2":
        return 0
    if options.hysteria2_warmup_attempts <= 0:
        return 0

    warmup_target = HttpProbeTarget(url=options.warmup_url, max_body_bytes=0)
    warmup_attempt_count = 0
    for _ in range(options.hysteria2_warmup_attempts):
        http_probe(warmup_target, socks_endpoint, options.request_timeout_seconds)
        warmup_attempt_count += 1
    return warmup_attempt_count


def _probe_with_transport_retries(
    *,
    candidate: CandidateProxy,
    candidate_id: str,
    socks_endpoint: SocksEndpoint,
    options: CandidateProbeOptions,
    http_probe: HttpProbeCallable,
    sleep_func: SleepCallable,
) -> tuple[ProbeResult, int, int, int]:
    """Run the Scholar probe and retry only transport failures in-process."""
    passed_result: ProbeResult | None = None
    last_result: ProbeResult | None = None
    attempt_count = 0
    retries_used = 0
    final_attempt_index = 0

    for attempt_index in range(options.transport_retry_count + 1):
        attempt_count += 1
        current_result = _run_scholar_attempt(
            candidate_id=candidate_id,
            socks_endpoint=socks_endpoint,
            options=options,
            http_probe=http_probe,
        )
        last_result = current_result
        final_attempt_index = attempt_index

        if _probe_result_passed(current_result):
            passed_result = current_result
            break

        if attempt_index >= options.transport_retry_count:
            break
        if not is_transport_retryable_probe_result(current_result):
            break

        retries_used += 1
        if options.transport_retry_backoff_seconds > 0:
            sleep_func(options.transport_retry_backoff_seconds)

    return passed_result or last_result or _unexpected_empty_attempt_result(candidate_id), attempt_count, retries_used, final_attempt_index


def _run_scholar_attempt(
    *,
    candidate_id: str,
    socks_endpoint: SocksEndpoint,
    options: CandidateProbeOptions,
    http_probe: HttpProbeCallable,
) -> ProbeResult:
    """Run one home/query Scholar attempt through the active SOCKS tunnel."""
    home_response = http_probe(
        build_scholar_home_target(),
        socks_endpoint,
        options.request_timeout_seconds,
    )
    query_response = None
    if options.probe_query:
        query_response = http_probe(
            build_scholar_query_target(options.query),
            socks_endpoint,
            options.request_timeout_seconds,
        )
    return build_scholar_probe_result(candidate_id, home_response, query_response)


def _probe_result_passed(result: ProbeResult) -> bool:
    """Return whether one result satisfies the conservative passed predicate."""
    allowed_statuses = {200, 301, 302, 303, 307, 308}
    failing_stage_markers = {
        "stage_home_blocked",
        "stage_query_blocked",
        "stage_transport_failed",
        "stage_timeout",
        "stage_server_error",
    }
    if result.blocked or result.timeout or result.error is not None:
        return False
    if result.home_status not in allowed_statuses:
        return False
    if result.query_status is None:
        return False
    if result.query_status not in allowed_statuses:
        return False
    if any(marker in failing_stage_markers for marker in result.failure_markers):
        return False
    if result.failure_markers:
        return False
    return True


def _unexpected_empty_attempt_result(candidate_id: str) -> ProbeResult:
    """Build one defensive result when no attempt result was produced."""
    return ProbeResult(
        candidate_id=candidate_id,
        home_status=None,
        query_status=None,
        blocked=False,
        timeout=False,
        error="probe exception: no attempt result was produced",
        failure_markers=["probe_exception"],
        latency_ms=None,
        checked_at=_utc_now_iso8601(),
    )


def _summary_from_failure(
    *,
    candidate_id: str,
    runtime_config_path: str,
    local_socks_host: str,
    local_socks_port: int,
    error: str,
    failure_markers: list[str],
    xray_started: bool = False,
    xray_test_passed: bool | None = None,
    startup_ready: bool = False,
    timeout: bool = False,
) -> CandidateProbeSummary:
    """Build one failed candidate probe summary with a synthetic ProbeResult."""
    result = ProbeResult(
        candidate_id=candidate_id,
        home_status=None,
        query_status=None,
        blocked=False,
        timeout=timeout,
        error=error,
        failure_markers=list(failure_markers),
        latency_ms=None,
        checked_at=_utc_now_iso8601(),
    )
    return CandidateProbeSummary(
        candidate_id=candidate_id,
        runtime_config_path=runtime_config_path,
        local_socks_host=local_socks_host,
        local_socks_port=local_socks_port,
        xray_started=xray_started,
        xray_test_passed=xray_test_passed,
        startup_ready=startup_ready,
        result=result,
    )


def _describe_xray_config_test_failure(result: XrayCommandResult) -> str:
    """Build a compact description of an Xray config test failure."""
    parts: list[str] = []
    if result.returncode is not None:
        parts.append(f"returncode={result.returncode}")
    if result.timed_out:
        parts.append("timed_out=True")
    if result.error:
        parts.append(result.error)
    if not parts:
        parts.append("unknown xray config test failure")
    return ", ".join(parts)


def _utc_now_iso8601() -> str:
    """Return the current UTC timestamp in ISO 8601 format with a Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
