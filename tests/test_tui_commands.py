"""Tests for TUI command-adapter helpers."""

from __future__ import annotations

import subprocess

from scholar_outbound_manager.tui.commands import build_fetch_command
from scholar_outbound_manager.tui.commands import build_probe_command
from scholar_outbound_manager.tui.commands import build_service_restart_command
from scholar_outbound_manager.tui.commands import build_service_snippet_command
from scholar_outbound_manager.tui.commands import build_service_stage_command
from scholar_outbound_manager.tui.commands import build_service_validate_command
from scholar_outbound_manager.tui.commands import preview_command
from scholar_outbound_manager.tui.commands import run_command


def test_command_adapter_uses_list_argv_and_not_shell() -> None:
    """Run command adapter through subprocess without shell=True."""
    observed = {}

    def fake_runner(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    result = run_command(["echo", "ok"], runner=fake_runner)

    assert observed["argv"] == ["echo", "ok"]
    assert observed["kwargs"]["shell"] is False
    assert result.exit_code == 0


def test_command_adapter_redacts_stdout_and_stderr() -> None:
    """Redact secret-like output before the TUI displays it."""
    def fake_runner(argv, **kwargs):
        del kwargs
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="vless://secret@example.invalid public_key=abc password=def",
            stderr="server_name=example.invalid host=1.2.3.4",
        )

    result = run_command(["echo"], runner=fake_runner)

    assert "vless://" not in result.stdout
    assert "public_key=abc" not in result.stdout
    assert "password=def" not in result.stdout
    assert "server_name=example.invalid" not in result.stderr
    assert "1.2.3.4" not in result.stderr


def test_fetch_and_probe_command_preview_is_correct() -> None:
    """Build workflow previews for fetch and probe."""
    fetch_preview = preview_command(build_fetch_command(config_path="config.yaml", output_path="candidates.json"))
    probe_preview = preview_command(
        build_probe_command(
            config_path="config.yaml",
            candidates_path="candidates.json",
            summary_output="state_data/probe_summary.json",
            passed_candidates_output="state_data/passed_candidates.json",
        )
    )

    assert "scholar-outbound-manager fetch --config config.yaml --output candidates.json --allow-network-fetch" in fetch_preview
    probe_argv = build_probe_command(
        config_path="config.yaml",
        candidates_path="candidates.json",
        summary_output="state_data/probe_summary.json",
        passed_candidates_output="state_data/passed_candidates.json",
    )
    parallel_index = probe_argv.index("--parallel")
    assert probe_argv[parallel_index + 1] == "2"
    assert "--keep-all-passed" not in probe_argv[parallel_index:parallel_index + 2]
    assert "--transport-retry-count 2" in probe_preview
    assert "--hysteria2-warmup-attempts 1" in probe_preview
    assert "--parallel --keep-all-passed 2" not in probe_preview


def test_service_stage_command_includes_skip_binary_copy_by_default() -> None:
    """Default sidecar staging preview should be safe for restaging."""
    argv = build_service_stage_command()
    assert "--skip-xray-binary-copy" in argv


def test_sidecar_service_previews_cover_restart_validate_and_snippet() -> None:
    """Build preview commands for the remaining sidecar workflow steps."""
    restart_preview = preview_command(build_service_restart_command())
    validate_preview = preview_command(build_service_validate_command())
    snippet_preview = preview_command(build_service_snippet_command())

    assert "sidecar service-restart --unit-name scholar-outbound-sidecar.service" in restart_preview
    assert "sidecar service-validate --unit-name scholar-outbound-sidecar.service" in validate_preview
    assert "sidecar service-snippet --listen-host 127.0.0.1 --listen-port 19080 --tag scholar-sidecar-socks-out" in snippet_preview
