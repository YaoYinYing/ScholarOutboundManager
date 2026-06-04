"""Tests for the Home screen model."""

from __future__ import annotations

from scholar_outbound_manager.tui.view_model import build_home_cards


def test_home_cards_are_task_oriented() -> None:
    cards = build_home_cards(
        {
            "home": {
                "subscription_configured": True,
                "last_fetch_status": "ready",
                "candidate_count": 20,
                "supported_count": 20,
                "tested_count": 20,
                "passed_count": 18,
                "failed_count": 2,
                "full_access_count": 18,
                "query_blocked_count": 1,
                "transport_failed_count": 1,
                "route_count": 1,
                "enabled_route_count": 1,
                "selected_candidate_label": "US relay",
                "active_listen_ports": [19080],
                "service_active": "unknown",
                "service_enabled": "unknown",
                "socks_status": "unknown",
                "last_validation": "needed",
            }
        }
    )

    assert [card.title for card in cards] == ["Subscription", "Testing", "Route", "Sidecar"]
    rendered = str(cards)
    assert "candidates.json" not in rendered
    assert "probe_summary.json" not in rendered
    assert "{" not in rendered
