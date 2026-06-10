"""Tests for the config-centered TUI CLI entry points."""

from __future__ import annotations

import builtins
from pathlib import Path

from scholar_outbound_manager import cli


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


def test_tui_app_build_parser() -> None:
    from scholar_outbound_manager.tui.app import build_parser

    parser = build_parser()
    args = parser.parse_args([])
    assert args.config == "config.yaml"

    args = parser.parse_args(["custom.yaml"])
    assert args.config == "custom.yaml"


def test_services_snapshot_loads_without_textual(tmp_path: Path) -> None:
    """SessionServices.snapshot() works without Textual installed."""
    import yaml
    from scholar_outbound_manager.tui.services import SessionServices

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump({
            "user_data_dir": str(tmp_path / "state_data"),
            "subscriptions": [{"name": "test", "url": "https://example.invalid/sub", "format": "auto", "enabled": True, "headers": {}}],
            "filters": {"include_keywords": [], "exclude_keywords": [], "deprioritize_keywords": []},
            "probe": {"timeout_seconds": 15, "concurrency": 1, "cache_ttl_hours": 24, "failure_backoff_hours": 48, "allow_network_probe": False},
            "xray": {"binary_path": "/fake/xray", "runtime_dir": ".runtime", "local_socks_host": "127.0.0.1", "local_socks_port": 0},
            "output": {"outbounds_path": "generated/o.json", "routes_path": "generated/r.json", "manifest_path": "generated/m.json", "history_dir": "state_data/history"},
            "generation": {"tag_prefix": "test-", "max_passed_nodes": 3, "fallback_blackhole_tag": "test-blackhole", "previous_output_max_age_hours": 168},
            "routing": {"mode": "dedicated_inbound", "inbound_tags": ["test-in"], "fail_closed": True},
        }),
        encoding="utf-8",
    )

    services = SessionServices(config_path)
    state = services.snapshot()

    assert state.config_loaded is True
    assert state.config_valid is True
    assert state.subscription_url_configured is True
    assert state.subscription_url_masked != ""
