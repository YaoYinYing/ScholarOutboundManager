from __future__ import annotations

from scholar_outbound_manager.tui.detail_model import build_route_detail_body
from scholar_outbound_manager.tui.detail_model import build_testing_detail_body


def test_build_testing_detail_body_renders_on_demand_detail() -> None:
    body = build_testing_detail_body(
        {
            "inspector": {
                "label": "US relay",
                "region_hint": "US",
                "protocol": "vless",
                "candidate_id": "candidate-001",
                "scholar_stage": "full_access",
                "home_status": 200,
                "query_status": 200,
                "latency_ms": 800,
                "markers": (),
                "explanation": "Home and query both passed.",
            }
        }
    )

    assert "Selected candidate" in body
    assert "US relay" in body


def test_build_route_detail_body_renders_on_demand_route_detail() -> None:
    body = build_route_detail_body(
        {
            "selected_index": 0,
            "entries": [
                {
                    "name": "Scholar",
                    "candidate_label": "JP relay",
                    "listen_host": "127.0.0.1",
                    "listen_port": 19080,
                    "enabled": True,
                    "validation_status": "ready",
                }
            ],
            "production_boundary": "Only ScholarOutboundManager sidecar is managed.",
        }
    )

    assert "Selected route" in body
    assert "JP relay" in body
