"""Smoke tests for the command-line interface skeleton."""

from scholar_outbound_manager import cli


def test_cli_help_returns_zero(capsys) -> None:
    """Return success when help text is requested."""
    exit_code = cli.main(["--help"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "usage:" in captured.out


def test_cli_version_returns_zero(capsys) -> None:
    """Return success when version text is requested."""
    exit_code = cli.main(["--version"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "scholar-outbound-manager 0.1.0" in captured.out


def test_fetch_requires_explicit_network_opt_in(capsys) -> None:
    """Refuse fetch unless the network opt-in flag is present."""
    exit_code = cli.main(["fetch"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "--allow-network-fetch" in captured.err


def test_cli_no_args_returns_zero(capsys) -> None:
    """Return success and print usage when no arguments are provided."""
    exit_code = cli.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "usage:" in captured.out


def test_cli_invalid_command_returns_two(capsys) -> None:
    """Return an argparse error status for an unknown subcommand."""
    exit_code = cli.main(["unknown-command"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "invalid choice" in captured.err or "usage:" in captured.out
