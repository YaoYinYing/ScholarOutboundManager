"""Tests for the config-centered TUI CLI entry points."""

from __future__ import annotations

import builtins
from pathlib import Path

from scholar_outbound_manager import cli
from scholar_outbound_manager.tui import app as tui_app
from scholar_outbound_manager.tui.config_centered import write_config_template


def test_cli_tui_missing_textual_gives_install_hint(capsys, monkeypatch) -> None:
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("textual"):
            raise ModuleNotFoundError("No module named 'textual'", name="textual")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    exit_code = cli.main(["tui"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert 'pip install "ScholarOutboundManager[tui]"' in captured.out or 'pip install "ScholarOutboundManager[tui]"' in captured.err


def test_cli_tui_defaults_to_config_yaml() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["tui"])

    assert args.command == "tui"
    assert args.config == "config.yaml"


def test_cli_tui_accepts_custom_positional_config() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["tui", "/tmp/custom.yaml"])

    assert args.config == "/tmp/custom.yaml"


def test_tui_template_writer_includes_subscription_and_user_data_dir(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config_template(config_path)

    rendered = config_path.read_text(encoding="utf-8")
    assert "subscription:" in rendered
    assert "url: ''" in rendered or 'url: ""' in rendered
    assert "user_data_dir: state_data" in rendered


def test_load_workflow_state_uses_config_centered_tabs_and_first_run_state(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.yaml"

    state = tui_app.load_workflow_state(config_path=str(config_path))

    assert state["tabs"] == ["Home", "Settings", "Testing", "Route", "Logs"]
    assert state["wizard"]["active"] is True
    assert state["wizard"]["steps"] == ["Config path", "Subscription", "User data dir", "Runtime", "Save"]
