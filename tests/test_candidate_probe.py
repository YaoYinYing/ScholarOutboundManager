"""Tests for single-candidate probe orchestration."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import XrayConfig
from scholar_outbound_manager.probe.candidate_probe import CandidateProbeOptions
from scholar_outbound_manager.probe.candidate_probe import probe_candidate
from scholar_outbound_manager.probe.http_probe import HttpProbeResponse
from scholar_outbound_manager.probe.http_probe import SocksEndpoint
from scholar_outbound_manager.xray.process import XrayCommandResult


def test_probe_candidate_success_path(capsys, tmp_path) -> None:
    """Run the successful single-candidate probe workflow."""
    fake_process = _FakeManagedProcess()
    captured_calls: list[tuple[str, str, int, float]] = []
    start_calls: list[tuple[str, str, str | None]] = []

    def fake_http_probe(target, socks, timeout_seconds):
        captured_calls.append((target.url, socks.host, socks.port, timeout_seconds))
        return _make_response(url=target.url, status_code=200, body_prefix="ok", elapsed_ms=10)

    def fake_start(binary_path, config_path, pid_file_path=None):
        start_calls.append((binary_path, str(config_path), None if pid_file_path is None else str(pid_file_path)))
        return fake_process

    summary = probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
        http_probe=fake_http_probe,
        start_xray_func=fake_start,
        wait_for_tcp_endpoint_func=lambda host, port, timeout_seconds: True,
    )
    captured = capsys.readouterr()

    assert summary.result.blocked is False
    assert summary.result.home_status == 200
    assert summary.result.query_status == 200
    assert summary.xray_started is True
    assert summary.startup_ready is True
    assert fake_process.terminate_called is True
    assert start_calls == [
        (
            "fake-xray",
            str(tmp_path / "runtime" / "candidate_probe_runtime.json"),
            str(tmp_path / "runtime" / "managed_xray_candidate_1.pid.json"),
        )
    ]
    assert captured_calls[0][1] == summary.local_socks_host
    assert captured_calls[0][2] == summary.local_socks_port
    assert captured.out == ""
    assert captured.err == ""


def test_probe_candidate_can_skip_query_probe(tmp_path) -> None:
    """Skip the query probe when requested."""
    fake_process = _FakeManagedProcess()
    call_urls: list[str] = []

    def fake_http_probe(target, socks, timeout_seconds):
        del socks, timeout_seconds
        call_urls.append(target.url)
        return _make_response(url=target.url, status_code=200, body_prefix="ok", elapsed_ms=10)

    summary = probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
        options=CandidateProbeOptions(probe_query=False),
        http_probe=fake_http_probe,
        start_xray_func=lambda binary_path, config_path, pid_file_path=None: fake_process,
        wait_for_tcp_endpoint_func=lambda host, port, timeout_seconds: True,
    )

    assert summary.result.query_status is None
    assert len(call_urls) == 1


def test_probe_candidate_runs_xray_config_test_when_enabled(tmp_path) -> None:
    """Run and record a successful Xray config test before probing."""
    fake_process = _FakeManagedProcess()
    test_calls: list[tuple[str, str, float]] = []

    def fake_test(binary_path, config_path, timeout_seconds):
        test_calls.append((binary_path, str(config_path), timeout_seconds))
        return XrayCommandResult(
            command=["fake-xray"],
            returncode=0,
            stdout="",
            stderr="",
            timed_out=False,
            error=None,
        )

    summary = probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
        options=CandidateProbeOptions(xray_test_timeout_seconds=2.0),
        http_probe=lambda target, socks, timeout_seconds: _make_response(url=target.url),
        start_xray_func=lambda binary_path, config_path, pid_file_path=None: fake_process,
        test_xray_config_func=fake_test,
        wait_for_tcp_endpoint_func=lambda host, port, timeout_seconds: True,
    )

    assert summary.xray_test_passed is True
    assert len(test_calls) == 1


def test_probe_candidate_stops_after_xray_config_test_failure(tmp_path) -> None:
    """Do not start Xray after a failed config test."""
    start_calls: list[tuple[str, str, str | None]] = []

    summary = probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
        options=CandidateProbeOptions(xray_test_timeout_seconds=2.0),
        start_xray_func=lambda binary_path, config_path, pid_file_path=None: start_calls.append((binary_path, str(config_path), None if pid_file_path is None else str(pid_file_path))) or _FakeManagedProcess(),
        test_xray_config_func=lambda binary_path, config_path, timeout_seconds: XrayCommandResult(
            command=["fake-xray"],
            returncode=1,
            stdout="",
            stderr="bad",
            timed_out=False,
            error="invalid config",
        ),
    )

    assert summary.xray_started is False
    assert summary.xray_test_passed is False
    assert "xray_config_test_failed" in summary.result.failure_markers
    assert start_calls == []


def test_probe_candidate_reports_xray_start_failure(tmp_path) -> None:
    """Report Xray start failures as structured probe results."""
    summary = probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
        start_xray_func=lambda binary_path, config_path, pid_file_path=None: (_ for _ in ()).throw(OSError("spawn failed")),
    )

    assert summary.xray_started is False
    assert "xray_start_failed" in summary.result.failure_markers


def test_probe_candidate_reports_socks_startup_timeout_and_terminates(tmp_path) -> None:
    """Terminate Xray when the SOCKS endpoint never becomes ready."""
    fake_process = _FakeManagedProcess()

    summary = probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
        start_xray_func=lambda binary_path, config_path, pid_file_path=None: fake_process,
        wait_for_tcp_endpoint_func=lambda host, port, timeout_seconds: False,
    )

    assert fake_process.terminate_called is True
    assert summary.result.timeout is True
    assert "socks_startup_timeout" in summary.result.failure_markers


def test_probe_candidate_reports_probe_exception_and_terminates(tmp_path) -> None:
    """Terminate Xray when the HTTP probe callable raises an exception."""
    fake_process = _FakeManagedProcess()

    summary = probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
        http_probe=lambda target, socks, timeout_seconds: (_ for _ in ()).throw(RuntimeError("boom")),
        start_xray_func=lambda binary_path, config_path, pid_file_path=None: fake_process,
        wait_for_tcp_endpoint_func=lambda host, port, timeout_seconds: True,
    )

    assert fake_process.terminate_called is True
    assert "probe_exception" in summary.result.failure_markers


def test_probe_candidate_reports_runtime_prepare_failure(tmp_path) -> None:
    """Return a structured failure when runtime preparation fails."""
    summary = probe_candidate(
        candidate=_make_candidate(public_key=None),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
    )

    assert summary.xray_started is False
    assert "runtime_prepare_failed" in summary.result.failure_markers


def test_probe_candidate_terminates_on_home_blocked_response(tmp_path) -> None:
    """Terminate Xray even when the home probe indicates blocking."""
    fake_process = _FakeManagedProcess()

    summary = probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
        http_probe=lambda target, socks, timeout_seconds: _make_response(
            url=target.url,
            status_code=403,
            body_prefix="forbidden",
        ),
        start_xray_func=lambda binary_path, config_path, pid_file_path=None: fake_process,
        wait_for_tcp_endpoint_func=lambda host, port, timeout_seconds: True,
    )

    assert fake_process.terminate_called is True
    assert summary.result.blocked is True


def test_probe_candidate_terminates_on_query_blocked_response(tmp_path) -> None:
    """Terminate Xray when the query probe indicates blocking."""
    fake_process = _FakeManagedProcess()

    def fake_http_probe(target, socks, timeout_seconds):
        if "/scholar?" in target.url:
            return _make_response(url=target.url, status_code=403, body_prefix="captcha")
        return _make_response(url=target.url, status_code=200, body_prefix="ok")

    summary = probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
        http_probe=fake_http_probe,
        start_xray_func=lambda binary_path, config_path, pid_file_path=None: fake_process,
        wait_for_tcp_endpoint_func=lambda host, port, timeout_seconds: True,
    )

    assert fake_process.terminate_called is True
    assert summary.result.blocked is True


def test_probe_candidate_merges_scholar_failure_markers(tmp_path) -> None:
    """Merge home and query Scholar classifier markers."""
    fake_process = _FakeManagedProcess()

    def fake_http_probe(target, socks, timeout_seconds):
        if "/scholar?" in target.url:
            return _make_response(url=target.url, status_code=403, body_prefix="captcha", elapsed_ms=20)
        return _make_response(url=target.url, status_code=200, body_prefix="Our systems have detected unusual traffic", elapsed_ms=10)

    summary = probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
        http_probe=fake_http_probe,
        start_xray_func=lambda binary_path, config_path, pid_file_path=None: fake_process,
        wait_for_tcp_endpoint_func=lambda host, port, timeout_seconds: True,
    )

    assert summary.result.failure_markers == [
        "unusual_traffic",
        "captcha",
        "http_403",
        "stage_home_blocked",
    ]
    assert summary.result.latency_ms == 30


def test_probe_candidate_summary_excludes_sensitive_values(tmp_path) -> None:
    """Keep sensitive candidate values out of the summary."""
    fake_process = _FakeManagedProcess()
    summary = probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
        http_probe=lambda target, socks, timeout_seconds: _make_response(url=target.url),
        start_xray_func=lambda binary_path, config_path, pid_file_path=None: fake_process,
        wait_for_tcp_endpoint_func=lambda host, port, timeout_seconds: True,
    )

    rendered = str(asdict(summary))
    assert "raw_uri" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered


def test_probe_candidate_sanitizes_pid_file_path_under_runtime_dir(tmp_path) -> None:
    """Place the managed pid file under runtime_dir with a sanitized candidate id."""
    fake_process = _FakeManagedProcess()
    start_calls: list[str] = []

    def fake_start(binary_path, config_path, pid_file_path=None):
        del binary_path, config_path
        start_calls.append(str(pid_file_path))
        return fake_process

    probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate/1:unsafe name",
        http_probe=lambda target, socks, timeout_seconds: _make_response(url=target.url),
        start_xray_func=fake_start,
        wait_for_tcp_endpoint_func=lambda host, port, timeout_seconds: True,
    )

    assert start_calls == [str(tmp_path / "runtime" / "managed_xray_candidate_1_unsafe_name.pid.json")]


def test_probe_candidate_rejects_invalid_startup_timeout(tmp_path) -> None:
    """Reject non-positive startup timeouts."""
    with pytest.raises(ValueError, match="startup_timeout_seconds"):
        probe_candidate(
            candidate=_make_candidate(),
            xray_config=_make_xray_config(tmp_path),
            candidate_id="candidate-1",
            options=CandidateProbeOptions(startup_timeout_seconds=0),
        )


def test_probe_candidate_rejects_invalid_request_timeout(tmp_path) -> None:
    """Reject non-positive request timeouts."""
    with pytest.raises(ValueError, match="request_timeout_seconds"):
        probe_candidate(
            candidate=_make_candidate(),
            xray_config=_make_xray_config(tmp_path),
            candidate_id="candidate-1",
            options=CandidateProbeOptions(request_timeout_seconds=0),
        )


def test_probe_candidate_rejects_invalid_xray_test_timeout(tmp_path) -> None:
    """Reject non-positive Xray test timeouts."""
    with pytest.raises(ValueError, match="xray_test_timeout_seconds"):
        probe_candidate(
            candidate=_make_candidate(),
            xray_config=_make_xray_config(tmp_path),
            candidate_id="candidate-1",
            options=CandidateProbeOptions(xray_test_timeout_seconds=0),
        )


def test_probe_candidate_rejects_invalid_runtime_config_name(tmp_path) -> None:
    """Reject runtime config names with path separators."""
    with pytest.raises(ValueError, match="runtime_config_name"):
        probe_candidate(
            candidate=_make_candidate(),
            xray_config=_make_xray_config(tmp_path),
            candidate_id="candidate-1",
            options=CandidateProbeOptions(runtime_config_name="nested/runtime.json"),
        )


def test_probe_candidate_checked_at_uses_utc_z_suffix(tmp_path) -> None:
    """Generate ProbeResult timestamps with a Z suffix."""
    fake_process = _FakeManagedProcess()
    summary = probe_candidate(
        candidate=_make_candidate(),
        xray_config=_make_xray_config(tmp_path),
        candidate_id="candidate-1",
        http_probe=lambda target, socks, timeout_seconds: _make_response(url=target.url),
        start_xray_func=lambda binary_path, config_path, pid_file_path=None: fake_process,
        wait_for_tcp_endpoint_func=lambda host, port, timeout_seconds: True,
    )

    assert summary.result.checked_at.endswith("Z")


def _make_candidate(**overrides: object) -> CandidateProxy:
    """Construct one placeholder candidate for candidate probe tests."""
    candidate_data: dict[str, object] = {
        "source_name": "fixture-source",
        "raw_name": "US Scholar IPv4",
        "protocol": "vless",
        "address": "example.invalid",
        "port": 443,
        "user_id": "00000000-0000-0000-0000-000000000000",
        "encryption": "none",
        "flow": "xtls-rprx-vision",
        "network": "tcp",
        "security": "reality",
        "server_name": "www.cloudflare.com",
        "fingerprint": "chrome",
        "public_key": "PUBLIC_KEY_PLACEHOLDER",
        "short_id": "SHORT_ID_PLACEHOLDER",
        "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
        "supported": True,
        "unsupported_reason": None,
    }
    candidate_data.update(overrides)
    return CandidateProxy(**candidate_data)


def _make_xray_config(tmp_path: Path) -> XrayConfig:
    """Construct one Xray config rooted in the pytest temporary directory."""
    return XrayConfig(
        binary_path="fake-xray",
        runtime_dir=str(tmp_path / "runtime"),
        local_socks_host="127.0.0.1",
        local_socks_port=1081,
    )


def _make_response(
    *,
    url: str,
    status_code: int | None = 200,
    body_prefix: str = "",
    headers: dict[str, str] | None = None,
    error: str | None = None,
    timed_out: bool = False,
    elapsed_ms: int | None = 10,
) -> HttpProbeResponse:
    """Construct one HTTP probe response for orchestration tests."""
    return HttpProbeResponse(
        url=url,
        status_code=status_code,
        reason="OK" if status_code == 200 else None,
        headers={} if headers is None else headers,
        body_prefix=body_prefix,
        elapsed_ms=elapsed_ms,
        timed_out=timed_out,
        error=error,
    )


class _FakeManagedProcess:
    """Minimal managed process fake for candidate probe tests."""

    def __init__(self) -> None:
        self.terminate_called = False

    def terminate(self, timeout_seconds: float = 5.0) -> None:
        del timeout_seconds
        self.terminate_called = True
