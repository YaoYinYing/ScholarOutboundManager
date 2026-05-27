"""Tests for production systemd sidecar helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import XrayConfig
from scholar_outbound_manager.sidecar_pool import build_sidecar_pool_plan
from scholar_outbound_manager.systemd_sidecar import SystemdCommandResult
from scholar_outbound_manager.systemd_sidecar import SystemdSidecarOptions
from scholar_outbound_manager.systemd_sidecar import all_command_results_ok
from scholar_outbound_manager.systemd_sidecar import build_ensure_system_user_commands
from scholar_outbound_manager.systemd_sidecar import build_systemd_sidecar_paths
from scholar_outbound_manager.systemd_sidecar import ensure_system_user
from scholar_outbound_manager.systemd_sidecar import install_systemd_unit
from scholar_outbound_manager.systemd_sidecar import render_sidecar_systemd_unit
from scholar_outbound_manager.systemd_sidecar import render_socks_outbound_snippet_for_sidecar
from scholar_outbound_manager.systemd_sidecar import run_systemctl
from scholar_outbound_manager.systemd_sidecar import stage_single_xray_pool_files
from scholar_outbound_manager.systemd_sidecar import stage_systemd_sidecar_files
from scholar_outbound_manager.systemd_sidecar import summarize_command_results
from scholar_outbound_manager.systemd_sidecar import validate_system_user_name
from scholar_outbound_manager.systemd_sidecar import validate_systemd_unit_name


def test_validate_systemd_unit_name_accepts_service_name() -> None:
    """Accept a normal service unit name."""
    validate_systemd_unit_name("scholar-outbound-sidecar.service")


def test_validate_systemd_unit_name_rejects_path_separator() -> None:
    """Reject path traversal in a unit name."""
    with pytest.raises(ValueError, match="path separators"):
        validate_systemd_unit_name("../bad.service")


def test_validate_system_user_name_accepts_service_name() -> None:
    """Accept a dedicated system user name."""
    validate_system_user_name("scholar-sidecar")


def test_validate_system_user_name_rejects_root() -> None:
    """Reject root as the dedicated production helper account."""
    with pytest.raises(ValueError, match="root"):
        validate_system_user_name("root")


def test_build_systemd_sidecar_paths_returns_expected_defaults() -> None:
    """Build the default production staging paths."""
    paths = build_systemd_sidecar_paths(SystemdSidecarOptions())

    assert paths.unit_path == "/etc/systemd/system/scholar-outbound-sidecar.service"
    assert paths.xray_binary_path == "/opt/scholar-outbound-manager/xray/xray"
    assert paths.runtime_config_path == "/etc/scholar-outbound-manager/scholar_sidecar_runtime.json"
    assert paths.metadata_path == "/var/lib/scholar-outbound-manager/scholar_sidecar.metadata.json"


def test_render_sidecar_systemd_unit_contains_user_execstart_restart_and_hardening() -> None:
    """Render a unit with dedicated user, direct ExecStart, and hardening settings."""
    options = SystemdSidecarOptions()
    paths = build_systemd_sidecar_paths(options)
    unit_text = render_sidecar_systemd_unit(options, paths)

    assert "User=scholar-sidecar" in unit_text
    assert "ExecStart=/opt/scholar-outbound-manager/xray/xray run -config /etc/scholar-outbound-manager/scholar_sidecar_runtime.json" in unit_text
    assert "Restart=on-failure" in unit_text
    assert "NoNewPrivileges=true" in unit_text
    assert "ProtectSystem=full" in unit_text
    assert unit_text.endswith("\n")


def test_render_sidecar_systemd_unit_excludes_candidate_secrets() -> None:
    """Keep the unit text free of runtime credentials."""
    unit_text = render_sidecar_systemd_unit(
        SystemdSidecarOptions(),
        build_systemd_sidecar_paths(SystemdSidecarOptions()),
    )

    lowered = unit_text.lower()
    assert "00000000-0000-0000-0000-000000000000" not in lowered
    assert "public_key_placeholder" not in lowered
    assert "password_placeholder" not in lowered
    assert "raw_uri" not in lowered


def test_stage_systemd_sidecar_files_writes_runtime_config_and_metadata(tmp_path, monkeypatch) -> None:
    """Stage production files into custom paths without leaking candidate secrets."""
    options = SystemdSidecarOptions(
        install_root=str(tmp_path / "opt"),
        config_dir=str(tmp_path / "etc"),
        state_dir=str(tmp_path / "var"),
        service_user="scholar-sidecar",
        service_group="scholar-sidecar",
    )
    source_binary = tmp_path / "source-xray"
    source_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    source_binary.chmod(0o755)
    monkeypatch.setattr(shutil, "chown", lambda *args, **kwargs: None)

    paths = stage_systemd_sidecar_files(
        candidate=_make_candidate(),
        candidate_id="candidate-001",
        xray_config=_make_xray_config(tmp_path),
        options=options,
        source_xray_binary_path=source_binary,
    )

    runtime_config = json.loads(Path(paths.runtime_config_path).read_text(encoding="utf-8"))
    metadata_text = Path(paths.metadata_path).read_text(encoding="utf-8")
    assert Path(paths.xray_binary_path).exists()
    assert runtime_config["inbounds"][0]["port"] == 19080
    assert runtime_config["outbounds"][0]["protocol"] == "vless"
    assert "00000000-0000-0000-0000-000000000000" not in metadata_text
    assert "PUBLIC_KEY_PLACEHOLDER" not in metadata_text
    assert "vless://" not in metadata_text


def test_stage_single_xray_pool_files_checks_ports_before_writing(tmp_path, monkeypatch) -> None:
    """Reject occupied pool ports before writing the sensitive runtime config."""
    options = SystemdSidecarOptions(
        install_root=str(tmp_path / "opt"),
        config_dir=str(tmp_path / "etc"),
        state_dir=str(tmp_path / "var"),
        service_user="scholar-sidecar",
        service_group="scholar-sidecar",
    )
    source_binary = tmp_path / "source-xray"
    source_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    source_binary.chmod(0o755)
    monkeypatch.setattr(shutil, "chown", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "scholar_outbound_manager.systemd_sidecar.check_pool_ports_available",
        lambda plan: {0: False},
    )
    plan = build_sidecar_pool_plan(_passed_candidates_payload(), max_count=1)

    with pytest.raises(ValueError, match="not available"):
        stage_single_xray_pool_files(
            payload=_passed_candidates_payload(),
            plan=plan,
            xray_config=_make_xray_config(tmp_path),
            options=options,
            source_xray_binary_path=source_binary,
        )


def test_stage_single_xray_pool_files_writes_redacted_metadata(tmp_path, monkeypatch) -> None:
    """Stage one multi-port runtime and keep metadata free of candidate secrets."""
    options = SystemdSidecarOptions(
        install_root=str(tmp_path / "opt"),
        config_dir=str(tmp_path / "etc"),
        state_dir=str(tmp_path / "var"),
        service_user="scholar-sidecar",
        service_group="scholar-sidecar",
    )
    source_binary = tmp_path / "source-xray"
    source_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    source_binary.chmod(0o755)
    monkeypatch.setattr(shutil, "chown", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "scholar_outbound_manager.systemd_sidecar.check_pool_ports_available",
        lambda plan: {entry.pool_index: True for entry in plan.entries},
    )
    plan = build_sidecar_pool_plan(_passed_candidates_payload(), max_count=1)

    paths = stage_single_xray_pool_files(
        payload=_passed_candidates_payload(),
        plan=plan,
        xray_config=_make_xray_config(tmp_path),
        options=options,
        source_xray_binary_path=source_binary,
    )

    metadata_text = Path(paths.metadata_path).read_text(encoding="utf-8")
    runtime_config = json.loads(Path(paths.runtime_config_path).read_text(encoding="utf-8"))
    assert runtime_config["inbounds"][0]["port"] == plan.entries[0].listen_port
    assert "PUBLIC_KEY_PLACEHOLDER" not in metadata_text
    assert "PASSWORD_PLACEHOLDER" not in metadata_text
    assert "00000000-0000-0000-0000-000000000000" not in metadata_text


def test_ensure_system_user_runs_expected_flow() -> None:
    """Check and create the system user/group only when they are missing."""
    commands_seen: list[list[str]] = []
    responses = {
        ("getent", "group", "scholar-sidecar"): subprocess.CompletedProcess(
            ["getent", "group", "scholar-sidecar"], 2, "", ""
        ),
        ("groupadd", "--system", "scholar-sidecar"): subprocess.CompletedProcess(
            ["groupadd", "--system", "scholar-sidecar"], 0, "", ""
        ),
        ("id", "-u", "scholar-sidecar"): subprocess.CompletedProcess(
            ["id", "-u", "scholar-sidecar"], 2, "", ""
        ),
        (
            "useradd",
            "--system",
            "--gid",
            "scholar-sidecar",
            "--home-dir",
            "/var/lib/scholar-outbound-manager",
            "--shell",
            "/usr/sbin/nologin",
            "scholar-sidecar",
        ): subprocess.CompletedProcess(
            [
                "useradd",
                "--system",
                "--gid",
                "scholar-sidecar",
                "--home-dir",
                "/var/lib/scholar-outbound-manager",
                "--shell",
                "/usr/sbin/nologin",
                "scholar-sidecar",
            ],
            0,
            "",
            "",
        ),
    }

    def fake_runner(command, capture_output, text, check):
        del capture_output, text, check
        commands_seen.append(list(command))
        return responses[tuple(command)]

    results = ensure_system_user(SystemdSidecarOptions(), runner=fake_runner)

    assert [result.command for result in results] == commands_seen
    assert any(command[:2] == ["groupadd", "--system"] for command in commands_seen)
    assert any(command[:2] == ["useradd", "--system"] for command in commands_seen)


def test_ensure_system_user_accepts_existing_group_and_user() -> None:
    """Treat existing system user and group checks as a successful result set."""
    responses = {
        ("getent", "group", "scholar-sidecar"): subprocess.CompletedProcess(
            ["getent", "group", "scholar-sidecar"], 0, "scholar-sidecar:x:992:\n", ""
        ),
        ("id", "-u", "scholar-sidecar"): subprocess.CompletedProcess(
            ["id", "-u", "scholar-sidecar"], 0, "994\n", ""
        ),
    }

    def fake_runner(command, capture_output, text, check):
        del capture_output, text, check
        return responses[tuple(command)]

    results = ensure_system_user(SystemdSidecarOptions(), runner=fake_runner)

    assert len(results) == 2
    assert all_command_results_ok(results) is True
    ok, messages = summarize_command_results(results)
    assert ok is True
    assert messages == []


def test_summarize_command_results_reports_failures() -> None:
    """Return a compact failure summary for nonzero command results."""
    ok, messages = summarize_command_results(
        [
            SystemdCommandResult(["groupadd", "--system", "scholar-sidecar"], 0, "", "", True),
            SystemdCommandResult(["systemctl", "daemon-reload"], 1, "", "boom", False),
        ]
    )

    assert ok is False
    assert messages == ["systemctl daemon-reload: returncode=1"]


def test_install_systemd_unit_writes_unit_and_calls_daemon_reload(tmp_path) -> None:
    """Write the unit file and call daemon-reload through the injected runner."""
    commands_seen: list[list[str]] = []

    def fake_runner(command, capture_output, text, check):
        del capture_output, text, check
        commands_seen.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    unit_path = tmp_path / "scholar-outbound-sidecar.service"
    results = install_systemd_unit("[Unit]\nDescription=test\n", unit_path, runner=fake_runner)

    assert unit_path.exists()
    assert commands_seen == [["systemctl", "daemon-reload"]]
    assert results[0].ok is True


def test_run_systemctl_allows_allowlisted_actions() -> None:
    """Allow only the expected systemctl actions."""
    commands_seen: list[list[str]] = []

    def fake_runner(command, capture_output, text, check):
        del capture_output, text, check
        commands_seen.append(list(command))
        return subprocess.CompletedProcess(command, 0, "active", "")

    result = run_systemctl("status", "scholar-outbound-sidecar.service", runner=fake_runner)

    assert result.command == ["systemctl", "status", "scholar-outbound-sidecar.service"]
    assert commands_seen == [["systemctl", "status", "scholar-outbound-sidecar.service"]]


def test_run_systemctl_allows_is_enabled() -> None:
    """Allow systemctl is-enabled for read-only validation flows."""
    commands_seen: list[list[str]] = []

    def fake_runner(command, capture_output, text, check):
        del capture_output, text, check
        commands_seen.append(list(command))
        return subprocess.CompletedProcess(command, 0, "enabled", "")

    result = run_systemctl("is-enabled", "scholar-outbound-sidecar.service", runner=fake_runner)

    assert result.command == ["systemctl", "is-enabled", "scholar-outbound-sidecar.service"]
    assert commands_seen == [["systemctl", "is-enabled", "scholar-outbound-sidecar.service"]]


def test_run_systemctl_rejects_arbitrary_action() -> None:
    """Reject non-allowlisted systemctl actions."""
    with pytest.raises(ValueError, match="not allowed"):
        run_systemctl("reload-or-restart;rm", "scholar-outbound-sidecar.service")


def test_service_snippet_returns_socks_outbound() -> None:
    """Render the production SOCKS outbound snippet."""
    snippet = render_socks_outbound_snippet_for_sidecar("127.0.0.1", 19080)

    assert snippet["protocol"] == "socks"
    assert snippet["settings"]["servers"][0]["address"] == "127.0.0.1"


def _make_candidate(**overrides: object) -> CandidateProxy:
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


def _passed_candidates_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "sensitive": True,
        "candidates": [
            {
                "candidate": _make_candidate().to_dict(),
                "probe": {
                    "candidate_id": "candidate-001",
                    "home_status": 200,
                    "query_status": 200,
                    "blocked": False,
                    "timeout": False,
                    "error": None,
                    "failure_markers": [],
                    "latency_ms": 10,
                    "checked_at": "2026-05-27T00:00:00Z",
                    "passed": True,
                },
            }
        ],
    }


def _make_xray_config(tmp_path: Path) -> XrayConfig:
    return XrayConfig(
        binary_path=str(tmp_path / "current-xray"),
        runtime_dir=str(tmp_path / "runtime"),
        local_socks_host="127.0.0.1",
        local_socks_port=1081,
    )
