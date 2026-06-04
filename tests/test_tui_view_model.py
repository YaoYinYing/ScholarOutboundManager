"""Tests for TUI view-model helpers."""

from __future__ import annotations

from scholar_outbound_manager.selection import CandidateCatalogEntry
from scholar_outbound_manager.tui.view_model import build_dashboard_model
from scholar_outbound_manager.tui.view_model import build_candidate_detail
from scholar_outbound_manager.tui.view_model import build_home_cards
from scholar_outbound_manager.tui.view_model import build_logs_summary
from scholar_outbound_manager.tui.view_model import build_pool_plan_rows
from scholar_outbound_manager.tui.view_model import build_route_table_model
from scholar_outbound_manager.tui.view_model import build_settings_summary
from scholar_outbound_manager.tui.view_model import build_snippet_view
from scholar_outbound_manager.tui.view_model import build_candidate_table_rows
from scholar_outbound_manager.tui.view_model import build_testing_table_model
from scholar_outbound_manager.tui.view_model import truncate_display_value


def test_build_candidate_table_rows_hides_secrets() -> None:
    """Render only redacted row fields for TUI use."""
    rows = build_candidate_table_rows(
        [
            CandidateCatalogEntry(
                index=0,
                candidate_id="candidate-001",
                protocol="vless",
                label="US-LA-01",
                source_label="fixture",
                region_hint="US-LA",
                source_name="fixture",
                supported=True,
                scholar_stage="full_access",
                passed=True,
                home_status=200,
                query_status=200,
                checked_at="2026-05-27T00:00:00Z",
                failure_marker_count=0,
                failure_markers=[],
                latency_ms=10,
                tags=["scholar"],
            )
        ]
    )

    rendered = str(rows[0])
    assert rows[0]["label"] == "US-LA-01"
    assert rows[0]["region"] == "US-LA"
    assert rows[0]["candidate_id"] == "candidate-001"
    assert "address" not in rendered
    assert "raw_uri" not in rendered
    assert "public_key" not in rendered


def test_candidate_detail_hides_secrets_and_shows_status() -> None:
    """Selected candidate detail should remain review-safe while showing workflow status."""
    detail = build_candidate_detail(
        {
            "candidate_id": "candidate-001",
            "label": "vless://secret@example.invalid",
            "region": "US",
            "protocol": "vless",
            "passed": True,
            "stage": "full_access",
            "home_status": 200,
            "query_status": 200,
            "markers": ["ok"],
        },
        selected_candidate_id="candidate-001",
        artifact_lineage_warning="warn",
    )

    rendered = str(detail)
    assert "vless://" not in rendered
    assert detail["protocol"] == "vless"
    assert detail["passed"] is True
    assert detail["selected"] is True
    assert detail["artifact_lineage_warning"] == "warn"


def test_candidate_table_truncates_long_labels_safely() -> None:
    """Overlong labels should be truncated for dense workbench rendering."""
    rows = build_candidate_table_rows(
        [
            CandidateCatalogEntry(
                index=0,
                candidate_id="candidate-001",
                protocol="vless",
                label="United States Candidate " + ("x" * 80),
                source_label="fixture",
                region_hint="US",
                source_name="fixture",
                supported=True,
                scholar_stage="full_access",
                passed=True,
                home_status=200,
                query_status=200,
                checked_at="2026-05-27T00:00:00Z",
                failure_marker_count=0,
                failure_markers=[],
                latency_ms=10,
                tags=["scholar"],
            )
        ]
    )

    assert rows[0]["label"].endswith("...")
    assert len(rows[0]["label"]) <= 48
    assert truncate_display_value("abc", limit=8) == "abc"


def test_dashboard_model_hides_secrets() -> None:
    """Redact secret-like dashboard labels."""
    dashboard = build_dashboard_model(
        {
            "repo_status": "dirty",
            "current_git_commit": "abc1234",
            "venv_detected": True,
            "config_exists": True,
            "config_dirty": True,
            "config_valid": False,
            "undo_available": True,
            "xray_binary_exists": True,
            "service_active": True,
            "service_enabled": True,
            "socks_tcp_connect": True,
            "last_scholar_validation": True,
            "candidate_count": 3,
            "passed_count": 1,
            "selected_candidate_label": "vless://secret@example.invalid 1.2.3.4",
            "current_sidecar_port": 19080,
        }
    )

    rendered = str(dashboard)
    assert "vless://" not in rendered
    assert "example.invalid" not in rendered
    assert "1.2.3.4" not in rendered
    assert dashboard["config_dirty"] is True
    assert dashboard["config_valid"] is False
    assert dashboard["undo_available"] is True


def test_pool_plan_view_shows_ports_and_labels_only() -> None:
    """Render pool-plan rows without raw candidate payload."""
    rows = build_pool_plan_rows(
        [
            {
                "listen_port": 19080,
                "candidate_id": "candidate-001",
                "candidate_label": "US-LA-01",
                "protocol": "hysteria2",
                "address": "example.invalid",
                "raw_uri": "vless://secret",
            }
        ]
    )

    rendered = str(rows)
    assert rows[0]["listen_port"] == 19080
    assert rows[0]["label"] == "US-LA-01"
    assert "address" not in rendered
    assert "raw_uri" not in rendered


def test_snippets_view_does_not_contain_secrets() -> None:
    """Keep snippets copy-friendly and redacted."""
    view = build_snippet_view(
        [
            {
                "tag": "out",
                "protocol": "socks",
                "settings": {
                    "servers": [
                        {"address": "127.0.0.1", "port": 19080}
                    ]
                },
                "password": "PASSWORD_PLACEHOLDER",
            }
        ],
        warning="These snippets are not automatically written to production Xray/XrayR.",
    )

    assert "PASSWORD_PLACEHOLDER" not in view["rendered"]
    assert "production Xray/XrayR" in view["warning"]


def test_new_page_models_are_task_centered() -> None:
    home_cards = build_home_cards({"home": {"subscription_configured": True, "last_fetch_status": "ready", "candidate_count": 3, "supported_count": 3, "tested_count": 3, "passed_count": 2, "failed_count": 1, "full_access_count": 2, "query_blocked_count": 1, "transport_failed_count": 0, "route_count": 1, "enabled_route_count": 1, "selected_candidate_label": "US relay", "active_listen_ports": [19080], "service_active": "unknown", "service_enabled": "unknown", "socks_status": "unknown", "last_validation": "needed"}})
    settings = build_settings_summary({"settings": {"config_path": "/tmp/config.yaml", "user_data_dir": "/tmp/state_data", "subscription_url_masked": "******** configured", "subscription_user_agent": "Clash.Meta", "xray_binary_path": ".runtime/xray/xray", "fail_closed": True, "experimental_hysteria2": False, "service_name": "scholar-outbound-sidecar.service"}})
    testing = build_testing_table_model({"testing": {"candidate_rows": [{"index": 1, "region": "US", "label": "US relay", "protocol": "vless", "passed": True, "latency_ms": 15, "home_status": 200, "query_status": 200, "stage": "full_access", "failure_marker_count": 0}]}})
    route = build_route_table_model({"route": {"entries": [{"name": "Scholar", "listen_host": "127.0.0.1", "listen_port": 19080, "enabled": True}], "selected_candidate_label": "US relay"}})
    logs = build_logs_summary({"logs_screen": {"rollback_warning": ["Artifact rollback restores local artifacts only."], "last_action": {"title": "Artifact Check", "succeeded": True, "summary": "ok"}}})

    assert home_cards[0].title == "Subscription"
    assert settings.subscription_url_masked == "******** configured"
    assert testing.columns[0] == "status"
    assert route.columns[0] == "enabled"
    assert logs.rollback_warning[0] == "Artifact rollback restores local artifacts only."
