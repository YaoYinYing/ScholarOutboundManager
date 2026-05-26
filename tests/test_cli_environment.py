"""Tests for the runtime environment CLI command."""

from __future__ import annotations

from scholar_outbound_manager import cli


def test_environment_command_returns_zero_and_prints_trust_level(capsys, monkeypatch) -> None:
    """Print a safe environment report and return success."""
    monkeypatch.setenv("HTTPS_PROXY", "http://oreo:oreo@127.0.0.1:10089")
    monkeypatch.setattr("scholar_outbound_manager.environment.sys.platform", "darwin")

    exit_code = cli.main(["environment"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Runtime environment:" in captured.out
    assert "trust_level: development_only" in captured.out


def test_environment_command_does_not_print_proxy_url(capsys, monkeypatch) -> None:
    """Keep proxy URL values out of CLI output."""
    proxy_url = "http://oreo:oreo@127.0.0.1:10089"
    monkeypatch.setenv("HTTPS_PROXY", proxy_url)

    exit_code = cli.main(["environment"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert proxy_url not in (captured.out + captured.err)
