"""Tests for the Settings screen model."""

from __future__ import annotations

from scholar_outbound_manager.tui.app import render_tab_text
from scholar_outbound_manager.tui.view_model import build_settings_summary


def test_settings_summary_shows_masked_subscription_and_user_data_dir() -> None:
    summary = build_settings_summary(
        {
            "settings": {
                "config_path": "/tmp/config.yaml",
                "user_data_dir": "/tmp/state_data",
                "subscription_url_masked": "******** configured",
                "subscription_user_agent": "Clash.Meta",
                "xray_binary_path": ".runtime/xray/xray",
                "fail_closed": True,
                "experimental_hysteria2": False,
                "service_name": "scholar-outbound-sidecar.service",
            }
        }
    )

    assert summary.user_data_dir == "/tmp/state_data"
    assert summary.subscription_url_masked == "******** configured"
    assert "http" not in summary.subscription_url_masked


def test_settings_render_shows_field_labels() -> None:
    rendered = render_tab_text(
        "Settings",
        {
            "settings": {
                "config_path": "/tmp/config.yaml",
                "user_data_dir": "/tmp/state_data",
                "subscription_url_masked": "******** configured",
                "subscription_user_agent": "Clash.Meta",
                "xray_binary_path": ".runtime/xray/xray",
                "fail_closed": True,
                "experimental_hysteria2": False,
                "service_name": "scholar-outbound-sidecar.service",
                "redacted_diff": "",
            }
        },
    )

    assert "Config path:" in rendered
    assert "User data dir:" in rendered
    assert "User-Agent:" in rendered
    assert "service name:" in rendered
