"""Tests for config-centered TUI presentation helpers."""

from __future__ import annotations

from scholar_outbound_manager.tui import app as tui_app
from scholar_outbound_manager.tui.workflow import MAIN_TABS


def test_textual_safe_id_keeps_widget_ids_valid() -> None:
    assert tui_app._textual_safe_id("Fetch & Probe") == "fetch-probe"
    assert tui_app._textual_safe_id("123 Test") == "tab-123-test"
    assert tui_app._textual_safe_id("   ") == "tab"


def test_build_tab_specs_uses_home_as_initial_tab() -> None:
    specs, initial_id = tui_app._build_tab_specs(list(MAIN_TABS))

    assert MAIN_TABS == ("Home", "Settings", "Testing", "Route", "Logs")
    assert initial_id == "home"
    assert [spec["title"] for spec in specs] == list(MAIN_TABS)


def test_render_home_tab_shows_config_centered_summary() -> None:
    rendered = tui_app.render_tab_text(
        "Home",
        {
            "home": {
                "config_path": "/tmp/config.yaml",
                "user_data_dir": "/tmp/state_data",
                "subscription_configured": True,
                "last_fetch_status": "ready",
                "candidate_count": 12,
                "passed_count": 5,
                "tested_count": 9,
                "full_access_count": 5,
                "query_blocked_count": 3,
                "enabled_route_count": 1,
                "route_count": 1,
                "active_listen_ports": [19080],
                "selected_candidate_label": "US relay",
                "service_active": "unknown",
                "socks_status": "unknown",
                "last_validation": "needed",
                "next_recommended_action": "Validate sidecar service.",
            },
            "wizard": {
                "active": False,
            },
        },
    )

    assert "Scholar Outbound Manager" in rendered
    assert "Config: /tmp/config.yaml" in rendered
    assert "User data: /tmp/state_data" in rendered
    assert "Subscription" in rendered
    assert "Testing" in rendered
    assert "Route" in rendered
    assert "Sidecar" in rendered
    assert "Next: Validate sidecar service." in rendered


def test_render_settings_hides_subscription_url_and_shows_safe_fields() -> None:
    rendered = tui_app.render_tab_text(
        "Settings",
        {
            "settings": {
                "config_path": "/tmp/config.yaml",
                "user_data_dir": "/tmp/state_data",
                "subscription_url_configured": True,
                "subscription_user_agent": "Clash.Meta",
                "xray_binary_path": ".runtime/xray/xray",
                "fail_closed": True,
                "experimental_hysteria2": False,
                "service_name": "scholar-outbound-sidecar.service",
                "redacted_diff": "",
            }
        },
    )

    assert "Settings" in rendered
    assert "URL configured: yes" in rendered
    assert "https://" not in rendered
    assert "User-Agent: Clash.Meta" in rendered
    assert "fail_closed: ON" in rendered
    assert "hysteria2 experimental: OFF" in rendered


def test_render_logs_shows_local_only_rollback_warning() -> None:
    rendered = tui_app.render_tab_text(
        "Logs",
        {
            "logs_screen": {
                "latest_snapshot_id": "snap-1",
                "latest_snapshot_reason": "pre_probe",
                "last_action": {
                    "title": "Probe Candidates",
                    "summary": "Probe Candidates failed with exit code 1.",
                },
            }
        },
    )

    assert "Logs" in rendered
    assert "Latest snapshot: snap-1" in rendered
    assert "Artifact rollback restores local artifacts only." in rendered
    assert "Probe Candidates failed with exit code 1." in rendered
