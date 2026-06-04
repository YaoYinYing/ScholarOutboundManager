"""Tests for config-centered TUI state helpers."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.tui.config_centered import build_first_run_wizard_state
from scholar_outbound_manager.tui.config_centered import summarize_config_centered_state
from scholar_outbound_manager.tui.config_centered import write_config_template


def test_config_centered_summary_masks_subscription_url(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config_template(config_path, subscription_url="https://example.invalid/token")

    summary = summarize_config_centered_state(config_path)

    assert summary.subscription_url_configured is True
    assert summary.subscription_url_masked == "******** configured"
    assert "example.invalid" not in summary.subscription_url_masked


def test_config_centered_summary_falls_back_to_operator_port(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config_template(config_path)
    config_path.write_text(config_path.read_text(encoding="utf-8").replace("local_socks_port: 19080", "local_socks_port: 0"), encoding="utf-8")

    summary = summarize_config_centered_state(config_path)

    assert summary.selected_ports == [19080]


def test_first_run_wizard_has_product_steps(tmp_path: Path) -> None:
    wizard = build_first_run_wizard_state(tmp_path / "missing.yaml")

    assert wizard.active is True
    assert wizard.step_titles == ("Config path", "Subscription", "User data dir", "Runtime", "Save")
