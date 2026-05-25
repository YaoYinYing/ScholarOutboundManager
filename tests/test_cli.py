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


def test_unimplemented_subcommand_returns_two(capsys) -> None:
    """Return the documented placeholder status for unimplemented commands."""
    exit_code = cli.main(["fetch"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "not implemented in Phase 0.5" in captured.out


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
