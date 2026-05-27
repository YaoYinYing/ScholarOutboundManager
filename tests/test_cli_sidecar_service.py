"""Tests for production systemd sidecar CLI commands."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scholar_outbound_manager import cli
from scholar_outbound_manager.probe.http_probe import HttpProbeResponse
from scholar_outbound_manager.systemd_sidecar import SystemdCommandResult


def test_sidecar_service_render_prints_unit(tmp_path, capsys) -> None:
    """Render the production unit to stdout."""
    exit_code = cli.main(["sidecar", "service-render"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "[Service]" in captured.out
    assert "ExecStart=/opt/scholar-outbound-manager/xray/xray run -config /etc/scholar-outbound-manager/scholar_sidecar_runtime.json" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_sidecar_service_stage_with_tmp_paths_stages_files(tmp_path, capsys, monkeypatch) -> None:
    """Stage production files into custom tmp paths."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    source_binary = tmp_path / "xray"
    source_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    source_binary.chmod(0o755)

    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        "scholar_outbound_manager.systemd_sidecar.shutil.chown",
        lambda *args, **kwargs: None,
    )

    exit_code = cli.main(
        [
            "sidecar",
            "service-stage",
            "--config",
            str(config_path),
            "--candidates",
            str(candidates_path),
            "--candidate-index",
            "0",
            "--install-root",
            str(tmp_path / "opt"),
            "--config-dir",
            str(tmp_path / "etc"),
            "--state-dir",
            str(tmp_path / "var"),
            "--source-xray-binary",
            str(source_binary),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "staged: true" in captured.out
    assert "candidate_protocol: vless" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_sidecar_service_install_uses_monkeypatched_installer_and_does_not_start_service(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    """Install the unit without starting it."""
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    called: dict[str, object] = {"ensure_user": False, "install_unit": False, "run_systemctl": False}

    def fake_ensure_system_user(options):
        called["ensure_user"] = True
        return [SystemdCommandResult(["id"], 0, "", "", True)]

    def fake_install_systemd_unit(unit_text, unit_path):
        called["install_unit"] = True
        assert "[Service]" in unit_text
        return [SystemdCommandResult(["systemctl", "daemon-reload"], 0, "", "", True)]

    def fail_run_systemctl(*args, **kwargs):
        called["run_systemctl"] = True
        raise AssertionError("service-install must not start or enable the unit")

    monkeypatch.setattr(cli, "ensure_system_user", fake_ensure_system_user)
    monkeypatch.setattr(cli, "install_systemd_unit", fake_install_systemd_unit)
    monkeypatch.setattr(cli, "run_systemctl", fail_run_systemctl)

    exit_code = cli.main(
        [
            "sidecar",
            "service-install",
            "--install-root",
            str(tmp_path / "opt"),
            "--config-dir",
            str(tmp_path / "etc"),
            "--state-dir",
            str(tmp_path / "var"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "installed: true" in captured.out
    assert called["ensure_user"] is True
    assert called["install_unit"] is True
    assert called["run_systemctl"] is False


def test_sidecar_service_install_returns_zero_when_group_user_exist_and_reload_succeeds(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    """Return 0 when preparation and daemon-reload all succeed."""
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        cli,
        "ensure_system_user",
        lambda options: [
            SystemdCommandResult(["getent", "group", options.service_group], 0, "", "", True),
            SystemdCommandResult(["id", "-u", options.service_user], 0, "", "", True),
        ],
    )
    monkeypatch.setattr(
        cli,
        "install_systemd_unit",
        lambda unit_text, unit_path: [SystemdCommandResult(["systemctl", "daemon-reload"], 0, "", "", True)],
    )

    exit_code = cli.main(
        [
            "sidecar",
            "service-install",
            "--install-root",
            str(tmp_path / "opt"),
            "--config-dir",
            str(tmp_path / "etc"),
            "--state-dir",
            str(tmp_path / "var"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "installed: true" in captured.out
    assert captured.err == ""


def test_sidecar_service_install_returns_zero_when_group_user_created_successfully(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    """Return 0 when missing dedicated accounts are created successfully."""
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        cli,
        "ensure_system_user",
        lambda options: [
            SystemdCommandResult(["getent", "group", options.service_group], 2, "", "", False),
            SystemdCommandResult(["groupadd", "--system", options.service_group], 0, "", "", True),
            SystemdCommandResult(["id", "-u", options.service_user], 1, "", "", False),
            SystemdCommandResult(["useradd", "--system", options.service_user], 0, "", "", True),
        ],
    )
    monkeypatch.setattr(
        cli,
        "install_systemd_unit",
        lambda unit_text, unit_path: [SystemdCommandResult(["systemctl", "daemon-reload"], 0, "", "", True)],
    )

    exit_code = cli.main(
        [
            "sidecar",
            "service-install",
            "--install-root",
            str(tmp_path / "opt"),
            "--config-dir",
            str(tmp_path / "etc"),
            "--state-dir",
            str(tmp_path / "var"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "installed: true" in captured.out
    assert captured.err == ""


def test_sidecar_service_install_returns_one_when_groupadd_fails(tmp_path, capsys, monkeypatch) -> None:
    """Return 1 when the dedicated group cannot be created."""
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        cli,
        "ensure_system_user",
        lambda options: [
            SystemdCommandResult(["getent", "group", options.service_group], 2, "", "", False),
            SystemdCommandResult(["groupadd", "--system", options.service_group], 1, "", "", False),
        ],
    )
    monkeypatch.setattr(
        cli,
        "install_systemd_unit",
        lambda unit_text, unit_path: [SystemdCommandResult(["systemctl", "daemon-reload"], 0, "", "", True)],
    )

    exit_code = cli.main(
        [
            "sidecar",
            "service-install",
            "--install-root",
            str(tmp_path / "opt"),
            "--config-dir",
            str(tmp_path / "etc"),
            "--state-dir",
            str(tmp_path / "var"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "installed: true" in captured.out
    assert "groupadd --system" in captured.err


def test_sidecar_service_install_returns_one_when_useradd_fails(tmp_path, capsys, monkeypatch) -> None:
    """Return 1 when the dedicated user cannot be created."""
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        cli,
        "ensure_system_user",
        lambda options: [
            SystemdCommandResult(["getent", "group", options.service_group], 0, "", "", True),
            SystemdCommandResult(["id", "-u", options.service_user], 1, "", "", False),
            SystemdCommandResult(["useradd", "--system", options.service_user], 1, "", "", False),
        ],
    )
    monkeypatch.setattr(
        cli,
        "install_systemd_unit",
        lambda unit_text, unit_path: [SystemdCommandResult(["systemctl", "daemon-reload"], 0, "", "", True)],
    )

    exit_code = cli.main(
        [
            "sidecar",
            "service-install",
            "--install-root",
            str(tmp_path / "opt"),
            "--config-dir",
            str(tmp_path / "etc"),
            "--state-dir",
            str(tmp_path / "var"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "useradd --system" in captured.err


def test_sidecar_service_install_returns_one_when_daemon_reload_fails(tmp_path, capsys, monkeypatch) -> None:
    """Return 1 when daemon-reload fails after successful preparation."""
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        cli,
        "ensure_system_user",
        lambda options: [SystemdCommandResult(["id", "-u", options.service_user], 0, "", "", True)],
    )
    monkeypatch.setattr(
        cli,
        "install_systemd_unit",
        lambda unit_text, unit_path: [SystemdCommandResult(["systemctl", "daemon-reload"], 1, "", "", False)],
    )

    exit_code = cli.main(
        [
            "sidecar",
            "service-install",
            "--install-root",
            str(tmp_path / "opt"),
            "--config-dir",
            str(tmp_path / "etc"),
            "--state-dir",
            str(tmp_path / "var"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "systemctl daemon-reload" in captured.err


def test_sidecar_service_actions_call_expected_systemctl(tmp_path, capsys, monkeypatch) -> None:
    """Route service lifecycle commands through the expected systemctl action."""
    observed: list[str] = []

    def fake_run_systemctl(action, unit_name):
        observed.append(action)
        return SystemdCommandResult(["systemctl", action, unit_name], 0, "", "", True)

    monkeypatch.setattr(cli, "run_systemctl", fake_run_systemctl)

    for action in ("start", "stop", "status", "enable", "disable"):
        exit_code = cli.main(["sidecar", f"service-{action}", "--unit-name", "scholar-outbound-sidecar.service"])
        capsys.readouterr()
        assert exit_code == 0

    assert observed == ["start", "stop", "status", "enable", "disable"]


def test_sidecar_service_snippet_prints_socks_outbound_json(capsys) -> None:
    """Print the production SOCKS outbound snippet."""
    exit_code = cli.main(["sidecar", "service-snippet", "--listen-host", "127.0.0.1", "--listen-port", "19080"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"protocol": "socks"' in captured.out
    assert '"port": 19080' in captured.out


def test_sidecar_service_validate_returns_zero_when_all_checks_pass(capsys, monkeypatch) -> None:
    """Return 0 when service state, TCP reachability, and Scholar validation all pass."""
    monkeypatch.setattr(
        cli,
        "run_systemctl",
        lambda action, unit_name: SystemdCommandResult(
            ["systemctl", action, unit_name],
            0,
            "active\n" if action == "is-active" else "enabled\n",
            "",
            True,
        ),
    )
    monkeypatch.setattr(cli, "_check_tcp_connect", lambda host, port, timeout_seconds: True)
    monkeypatch.setattr(cli, "probe_http_via_socks", lambda target, socks, timeout: _make_http_response(target.url, 200))

    exit_code = cli.main(["sidecar", "service-validate"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "service_active: true" in captured.out
    assert "service_enabled: true" in captured.out
    assert "socks_tcp_connect: true" in captured.out
    assert "scholar_passed: true" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_sidecar_service_validate_returns_one_when_service_inactive(capsys, monkeypatch) -> None:
    """Return 1 when the unit is not active."""
    monkeypatch.setattr(
        cli,
        "run_systemctl",
        lambda action, unit_name: SystemdCommandResult(
            ["systemctl", action, unit_name],
            3 if action == "is-active" else 0,
            "inactive\n" if action == "is-active" else "enabled\n",
            "",
            action != "is-active",
        ),
    )
    monkeypatch.setattr(cli, "_check_tcp_connect", lambda host, port, timeout_seconds: True)
    monkeypatch.setattr(cli, "probe_http_via_socks", lambda target, socks, timeout: _make_http_response(target.url, 200))

    exit_code = cli.main(["sidecar", "service-validate"])

    assert exit_code == 1


def test_sidecar_service_validate_returns_one_when_tcp_connect_fails(capsys, monkeypatch) -> None:
    """Return 1 when the SOCKS listener is not reachable."""
    monkeypatch.setattr(
        cli,
        "run_systemctl",
        lambda action, unit_name: SystemdCommandResult(["systemctl", action, unit_name], 0, "active\n" if action == "is-active" else "enabled\n", "", True),
    )
    monkeypatch.setattr(cli, "_check_tcp_connect", lambda host, port, timeout_seconds: False)
    monkeypatch.setattr(cli, "probe_http_via_socks", lambda target, socks, timeout: _make_http_response(target.url, 200))

    exit_code = cli.main(["sidecar", "service-validate"])

    assert exit_code == 1


def test_sidecar_service_validate_returns_one_when_scholar_query_blocked(capsys, monkeypatch) -> None:
    """Return 1 when Scholar access through the sidecar does not pass."""
    monkeypatch.setattr(
        cli,
        "run_systemctl",
        lambda action, unit_name: SystemdCommandResult(["systemctl", action, unit_name], 0, "active\n" if action == "is-active" else "enabled\n", "", True),
    )
    monkeypatch.setattr(cli, "_check_tcp_connect", lambda host, port, timeout_seconds: True)

    def fake_probe(target, socks, timeout):
        del socks, timeout
        if "scholar.google.com/schhp" in target.url:
            return _make_http_response(target.url, 200)
        return _make_http_response(target.url, 403)

    monkeypatch.setattr(cli, "probe_http_via_socks", fake_probe)

    exit_code = cli.main(["sidecar", "service-validate"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "scholar_passed: false" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_sidecar_service_invalid_unit_name_returns_one(capsys) -> None:
    """Reject an invalid production unit name."""
    exit_code = cli.main(["sidecar", "service-render", "--unit-name", "../bad.service"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.err


def test_sidecar_service_invalid_user_name_returns_one(capsys) -> None:
    """Reject an invalid dedicated service user name."""
    exit_code = cli.main(["sidecar", "service-render", "--service-user", "bad:user"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.err


def test_existing_manual_sidecar_commands_remain_available(tmp_path, capsys, monkeypatch) -> None:
    """Keep manual sidecar commands available after adding service mode."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)

    def fake_start_sidecar_runtime(xray_config, summary, *, test_config_timeout_seconds=10.0):
        del xray_config, test_config_timeout_seconds
        return summary.__class__(**{**summary.__dict__, "started": True, "config_test_passed": True, "error": None})

    monkeypatch.setattr(cli, "start_sidecar_runtime", fake_start_sidecar_runtime)

    assert cli.main(["sidecar", "prepare", "--config", str(config_path), "--candidates", str(candidates_path)]) == 0
    capsys.readouterr()
    assert cli.main(["sidecar", "status", "--config", str(config_path)]) == 0
    capsys.readouterr()


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "subscriptions:",
                '  - name: "fixture-source"',
                '    url: "https://example.invalid/subscription"',
                '    format: "auto"',
                "    enabled: false",
                "    headers: {}",
                "filters:",
                "  include_keywords: []",
                "  exclude_keywords: []",
                "  deprioritize_keywords: []",
                "probe:",
                "  timeout_seconds: 5",
                "  concurrency: 1",
                "  cache_ttl_hours: 24",
                "  failure_backoff_hours: 24",
                "  allow_network_probe: true",
                "xray:",
                f"  binary_path: {tmp_path / 'current-xray'}",
                f"  runtime_dir: {tmp_path / 'runtime'}",
                "  local_socks_host: 127.0.0.1",
                "  local_socks_port: 1081",
                "output:",
                f"  outbounds_path: {tmp_path / 'outbounds.json'}",
                f"  routes_path: {tmp_path / 'routes.json'}",
                f"  manifest_path: {tmp_path / 'manifest.json'}",
                f"  history_dir: {tmp_path / 'history'}",
                "generation:",
                "  tag_prefix: google-scholar-node-",
                "  max_passed_nodes: 2",
                "  fallback_blackhole_tag: blocked-scholar",
                "  previous_output_max_age_hours: 24",
                "routing:",
                "  mode: dedicated_inbound",
                "  inbound_tags:",
                "    - scholar-in",
                "  fail_closed: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "current-xray").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (tmp_path / "current-xray").chmod(0o755)
    return config_path


def _write_candidates(tmp_path: Path) -> Path:
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(
        '{"candidates":[{"source_name":"fixture","raw_name":"node","protocol":"vless","address":"example.invalid","port":443,"user_id":"00000000-0000-0000-0000-000000000000","security":"reality","server_name":"www.cloudflare.com","public_key":"PUBLIC_KEY_PLACEHOLDER","supported":true,"raw_uri":"vless://00000000-0000-0000-0000-000000000000@example.invalid:443"}]}',
        encoding="utf-8",
    )
    return candidates_path


def _assert_no_secrets(rendered: str) -> None:
    lowered = rendered.lower()
    assert "raw_uri" not in lowered
    assert "00000000-0000-0000-0000-000000000000" not in lowered
    assert "public_key_placeholder" not in lowered
    assert "password" not in lowered
    assert "token" not in lowered
    assert "secret" not in lowered


def _make_http_response(url: str, status_code: int) -> HttpProbeResponse:
    return HttpProbeResponse(
        url=url,
        status_code=status_code,
        reason="OK" if status_code == 200 else "Forbidden",
        headers={},
        body_prefix="",
        elapsed_ms=10,
        timed_out=False,
        error=None,
    )
