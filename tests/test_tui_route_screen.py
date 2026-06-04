"""Tests for the Route screen model."""

from __future__ import annotations

from scholar_outbound_manager.tui.app import render_tab_text
from scholar_outbound_manager.tui.view_model import build_route_table_model


def test_route_table_model_exposes_operator_fields() -> None:
    model = build_route_table_model(
        {
            "route": {
                "entries": [
                    {
                        "name": "Scholar",
                        "listen_host": "127.0.0.1",
                        "listen_port": 19080,
                        "enabled": True,
                    }
                ],
                "selected_candidate_label": "US relay",
            }
        }
    )

    assert model.columns == ["enabled", "name", "candidate", "host", "port", "port status", "validation"]
    assert model.rows[0][2] == "US relay"
    assert "production Xray" not in str(model.rows)


def test_route_render_shows_editor_labels_and_boundary() -> None:
    rendered = render_tab_text(
        "Route",
        {
            "route": {
                "entries": [
                    {
                        "name": "Scholar",
                        "listen_host": "127.0.0.1",
                        "listen_port": 19080,
                        "enabled": True,
                    }
                ],
                "selected_candidate_label": "US relay",
                "service_name": "scholar-outbound-sidecar.service",
                "production_boundary": "Only manages the ScholarOutboundManager sidecar. It does not modify production Xray/XrayR/x-ui.",
                "candidate_select_ready": False,
                "listen_host": "127.0.0.1",
                "listen_port": 19080,
                "route_enabled": True,
            }
        },
    )

    assert "Listen host:" in rendered
    assert "Listen port:" in rendered
    assert "Enabled:" in rendered
    assert "Choose Passed Node" in rendered
    assert "Candidate selector not implemented yet." in rendered
    assert "does not modify production Xray/XrayR/x-ui" in rendered
