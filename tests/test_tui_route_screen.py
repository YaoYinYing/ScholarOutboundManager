"""Tests for the Route screen model."""

from __future__ import annotations

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
