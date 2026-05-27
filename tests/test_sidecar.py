"""Tests for isolated Scholar sidecar runtime helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import XrayConfig
from scholar_outbound_manager.sidecar import SidecarRuntimeOptions
from scholar_outbound_manager.sidecar import build_socks_outbound_snippet
from scholar_outbound_manager.sidecar import inspect_sidecar_runtime
from scholar_outbound_manager.sidecar import prepare_sidecar_runtime
from scholar_outbound_manager.sidecar import start_sidecar_runtime
from scholar_outbound_manager.sidecar import stop_sidecar_runtime
from scholar_outbound_manager.xray.process import ManagedXrayProcess
from scholar_outbound_manager.xray.process import XrayCommandResult


def test_prepare_sidecar_runtime_writes_runtime_config(tmp_path) -> None:
    """Prepare and persist one sidecar runtime config."""
    summary = prepare_sidecar_runtime(
        candidate=_make_vless_candidate(),
        xray_config=_make_xray_config(tmp_path),
        options=SidecarRuntimeOptions(),
        candidate_id="candidate-001",
    )

    assert Path(summary.runtime_config_path).exists()
    assert Path(summary.metadata_file_path).exists()
    assert summary.started is False


def test_prepare_sidecar_runtime_uses_requested_fixed_port(tmp_path) -> None:
    """Bind the sidecar SOCKS inbound to the requested fixed port."""
    summary = prepare_sidecar_runtime(
        candidate=_make_vless_candidate(),
        xray_config=_make_xray_config(tmp_path),
        options=SidecarRuntimeOptions(listen_port=19081),
    )

    runtime_config = json.loads(Path(summary.runtime_config_path).read_text(encoding="utf-8"))
    assert runtime_config["inbounds"][0]["listen"] == "127.0.0.1"
    assert runtime_config["inbounds"][0]["port"] == 19081


def test_prepare_sidecar_runtime_uses_candidate_outbound_protocol(tmp_path) -> None:
    """Write the selected candidate outbound into the sidecar runtime config."""
    summary = prepare_sidecar_runtime(
        candidate=_make_trojan_candidate(),
        xray_config=_make_xray_config(tmp_path),
        options=SidecarRuntimeOptions(),
    )

    runtime_config = json.loads(Path(summary.runtime_config_path).read_text(encoding="utf-8"))
    assert runtime_config["outbounds"][0]["protocol"] == "trojan"


def test_prepare_sidecar_runtime_supports_hysteria2_candidate(tmp_path) -> None:
    """Write a Hysteria2-backed outbound into the sidecar runtime config."""
    summary = prepare_sidecar_runtime(
        candidate=_make_hysteria2_candidate(),
        xray_config=_make_xray_config(tmp_path),
        options=SidecarRuntimeOptions(),
    )

    runtime_config = json.loads(Path(summary.runtime_config_path).read_text(encoding="utf-8"))
    assert runtime_config["outbounds"][0]["protocol"] == "hysteria"


def test_prepare_sidecar_metadata_excludes_sensitive_fields(tmp_path) -> None:
    """Keep sidecar metadata free of candidate secrets."""
    summary = prepare_sidecar_runtime(
        candidate=_make_vless_candidate(),
        xray_config=_make_xray_config(tmp_path),
        options=SidecarRuntimeOptions(),
        candidate_id="candidate-001",
    )

    rendered = Path(summary.metadata_file_path).read_text(encoding="utf-8")
    assert "raw_uri" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "PASSWORD_PLACEHOLDER" not in rendered


def test_build_socks_outbound_snippet_returns_socks_outbound() -> None:
    """Build one production-reference SOCKS outbound snippet."""
    snippet = build_socks_outbound_snippet("127.0.0.1", 19080)

    assert snippet["protocol"] == "socks"
    assert snippet["settings"]["servers"][0]["port"] == 19080


def test_start_sidecar_runtime_calls_start_xray_with_pid_file_path(tmp_path, monkeypatch) -> None:
    """Start the sidecar with explicit pid-file ownership."""
    summary = prepare_sidecar_runtime(
        candidate=_make_vless_candidate(),
        xray_config=_make_xray_config(tmp_path),
        options=SidecarRuntimeOptions(),
    )
    observed: dict[str, object] = {}

    def fake_test(binary_path, config_path, timeout_seconds):
        del binary_path, config_path, timeout_seconds
        return XrayCommandResult(
            command=["fake-xray"],
            returncode=0,
            stdout="",
            stderr="",
            timed_out=False,
            error=None,
        )

    def fake_start(binary_path, config_path, *, pid_file_path=None):
        observed["binary_path"] = binary_path
        observed["config_path"] = str(config_path)
        observed["pid_file_path"] = str(pid_file_path)
        return _FakeManagedProcess()

    monkeypatch.setattr("scholar_outbound_manager.sidecar.test_xray_config", fake_test)
    monkeypatch.setattr("scholar_outbound_manager.sidecar.start_xray", fake_start)
    monkeypatch.setattr(
        "scholar_outbound_manager.sidecar.wait_for_tcp_endpoint",
        lambda host, port, timeout_seconds: True,
    )

    started = start_sidecar_runtime(_make_xray_config(tmp_path), summary)

    assert started.started is True
    assert observed["pid_file_path"] == summary.pid_file_path


def test_start_sidecar_runtime_waits_for_tcp_readiness(tmp_path, monkeypatch) -> None:
    """Wait for the sidecar SOCKS endpoint before reporting success."""
    summary = prepare_sidecar_runtime(
        candidate=_make_vless_candidate(),
        xray_config=_make_xray_config(tmp_path),
        options=SidecarRuntimeOptions(),
    )
    wait_calls: list[tuple[str, int, float]] = []

    monkeypatch.setattr(
        "scholar_outbound_manager.sidecar.test_xray_config",
        lambda *args, **kwargs: XrayCommandResult(
            command=["fake-xray"],
            returncode=0,
            stdout="",
            stderr="",
            timed_out=False,
            error=None,
        ),
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.sidecar.start_xray",
        lambda *args, **kwargs: _FakeManagedProcess(),
    )

    def fake_wait(host, port, timeout_seconds):
        wait_calls.append((host, port, timeout_seconds))
        return True

    monkeypatch.setattr("scholar_outbound_manager.sidecar.wait_for_tcp_endpoint", fake_wait)

    start_sidecar_runtime(_make_xray_config(tmp_path), summary)

    assert wait_calls == [("127.0.0.1", 19080, 5.0)]


def test_start_sidecar_runtime_does_not_access_scholar(tmp_path, monkeypatch) -> None:
    """Keep sidecar start local-only without Scholar probes."""
    summary = prepare_sidecar_runtime(
        candidate=_make_vless_candidate(),
        xray_config=_make_xray_config(tmp_path),
        options=SidecarRuntimeOptions(),
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.sidecar.test_xray_config",
        lambda *args, **kwargs: XrayCommandResult(
            command=["fake-xray"],
            returncode=0,
            stdout="",
            stderr="",
            timed_out=False,
            error=None,
        ),
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.sidecar.start_xray",
        lambda *args, **kwargs: _FakeManagedProcess(),
    )
    monkeypatch.setattr(
        "scholar_outbound_manager.sidecar.wait_for_tcp_endpoint",
        lambda *args, **kwargs: True,
    )

    started = start_sidecar_runtime(_make_xray_config(tmp_path), summary)

    assert started.error is None


def test_inspect_sidecar_runtime_uses_pid_file_only(tmp_path, monkeypatch) -> None:
    """Inspect the sidecar through pid-file ownership checks only."""
    pid_file_path = tmp_path / "scholar_sidecar.pid.json"
    pid_file_path.write_text("{}", encoding="utf-8")
    observed: dict[str, object] = {}

    def fake_is_alive(pid_file_path_arg, *, expected_binary_path, expected_config_path=None):
        observed["pid_file_path"] = str(pid_file_path_arg)
        observed["expected_binary_path"] = str(expected_binary_path)
        observed["expected_config_path"] = None if expected_config_path is None else str(expected_config_path)
        return True

    monkeypatch.setattr("scholar_outbound_manager.sidecar.is_managed_xray_process_alive", fake_is_alive)

    inspection = inspect_sidecar_runtime(
        pid_file_path,
        expected_binary_path=tmp_path / "xray",
        expected_config_path=tmp_path / "runtime.json",
    )

    assert inspection == {
        "pid_file_exists": True,
        "alive": True,
        "ownership_matched": True,
    }
    assert observed["pid_file_path"] == str(pid_file_path)


def test_stop_sidecar_runtime_only_calls_managed_pid_termination(tmp_path, monkeypatch) -> None:
    """Stop the sidecar only through managed pid-file ownership."""
    observed: dict[str, object] = {}

    def fake_terminate(pid_file_path, *, expected_binary_path, expected_config_path=None, timeout_seconds=3.0):
        observed["pid_file_path"] = str(pid_file_path)
        observed["expected_binary_path"] = str(expected_binary_path)
        observed["expected_config_path"] = None if expected_config_path is None else str(expected_config_path)
        observed["timeout_seconds"] = timeout_seconds
        return True

    monkeypatch.setattr(
        "scholar_outbound_manager.sidecar.terminate_managed_xray_from_pid_file",
        fake_terminate,
    )

    stopped = stop_sidecar_runtime(
        tmp_path / "managed.pid.json",
        expected_binary_path=tmp_path / "xray",
        expected_config_path=tmp_path / "runtime.json",
    )

    assert stopped is True
    assert observed["pid_file_path"] == str(tmp_path / "managed.pid.json")


def test_prepare_sidecar_runtime_rejects_invalid_listen_port(tmp_path) -> None:
    """Reject non-positive fixed sidecar ports."""
    with pytest.raises(ValueError, match="listen_port"):
        prepare_sidecar_runtime(
            candidate=_make_vless_candidate(),
            xray_config=_make_xray_config(tmp_path),
            options=SidecarRuntimeOptions(listen_port=0),
        )


def test_prepare_sidecar_runtime_rejects_runtime_config_name_with_separator(tmp_path) -> None:
    """Reject path separators in the sidecar runtime config name."""
    with pytest.raises(ValueError, match="runtime_config_name"):
        prepare_sidecar_runtime(
            candidate=_make_vless_candidate(),
            xray_config=_make_xray_config(tmp_path),
            options=SidecarRuntimeOptions(runtime_config_name="nested/runtime.json"),
        )


class _FakeManagedProcess:
    """Minimal managed process fake for sidecar tests."""

    def __init__(self) -> None:
        self.process = type("PopenLike", (), {"pid": 4321})()
        self.terminate_called = False

    def terminate(self, timeout_seconds: float = 5.0) -> None:
        del timeout_seconds
        self.terminate_called = True


def _make_vless_candidate(**overrides: object) -> CandidateProxy:
    candidate_data: dict[str, object] = {
        "source_name": "fixture-source",
        "raw_name": "node",
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
        "path": "/ws",
        "host": "cdn.example.invalid",
        "extra": {},
        "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
        "supported": True,
    }
    candidate_data.update(overrides)
    return CandidateProxy(**candidate_data)


def _make_trojan_candidate(**overrides: object) -> CandidateProxy:
    return _make_vless_candidate(
        protocol="trojan",
        user_id=None,
        password="PASSWORD_PLACEHOLDER",
        flow=None,
        security="tls",
        public_key=None,
        short_id=None,
        raw_uri=None,
        **overrides,
    )


def _make_hysteria2_candidate(**overrides: object) -> CandidateProxy:
    return _make_vless_candidate(
        protocol="hysteria2",
        user_id=None,
        password="HY2_PASSWORD_PLACEHOLDER",
        encryption=None,
        flow=None,
        network=None,
        security="hysteria",
        server_name="hy2.example.invalid",
        fingerprint=None,
        public_key=None,
        short_id=None,
        alpn=None,
        raw_uri=None,
        address="hy2.example.invalid",
        extra={"skip_cert_verify": True},
        **overrides,
    )


def _make_xray_config(tmp_path: Path) -> XrayConfig:
    return XrayConfig(
        binary_path="fake-xray",
        runtime_dir=str(tmp_path / "runtime"),
        local_socks_host="127.0.0.1",
        local_socks_port=1081,
    )
