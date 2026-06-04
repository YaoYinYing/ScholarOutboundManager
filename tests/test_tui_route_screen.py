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
                        "candidate_id": "candidate-001",
                        "candidate_label": "US relay",
                    }
                ]
            }
        }
    )

    assert model.columns == ["enabled", "name", "candidate", "region", "protocol", "host", "port", "port status", "validation"]
    assert model.rows[0][2] == "US relay"
    assert "production Xray" not in str(model.rows)


def test_route_table_model_shows_not_selected_when_candidate_missing() -> None:
    model = build_route_table_model(
        {
            "route": {
                "entries": [
                    {
                        "name": "Scholar",
                        "listen_host": "127.0.0.1",
                        "listen_port": 19080,
                        "enabled": True,
                        "candidate_id": None,
                        "candidate_label": "stale fallback",
                    }
                ]
            }
        }
    )

    assert model.rows[0][2] == "(not selected)"


def test_route_table_model_marks_stale_candidate() -> None:
    model = build_route_table_model(
        {
            "route": {
                "entries": [
                    {
                        "name": "Scholar",
                        "listen_host": "127.0.0.1",
                        "listen_port": 19080,
                        "enabled": True,
                        "candidate_id": "candidate-stale",
                        "candidate_label": "US relay",
                        "error": "stale candidate",
                    }
                ]
            }
        }
    )

    assert model.rows[0][2] == "stale: US relay"


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
                "candidate_selector_enabled": True,
                "selected_index": 0,
                "can_apply": True,
                "validation_errors": [],
            }
        },
    )

    assert "Listen host:" in rendered
    assert "Listen port:" in rendered
    assert "Enabled:" in rendered
    assert "Choose Passed Node" in rendered
    assert "Candidate selector not implemented yet." not in rendered
    assert "does not modify production Xray/XrayR/x-ui" in rendered


def test_route_render_shows_disabled_selector_message_when_artifacts_stale() -> None:
    rendered = render_tab_text(
        "Route",
        {
            "route": {
                "entries": [
                    {
                        "name": "Scholar",
                        "candidate_id": None,
                        "candidate_label": None,
                        "listen_host": "127.0.0.1",
                        "listen_port": 19080,
                        "enabled": True,
                    }
                ],
                "service_name": "scholar-outbound-sidecar.service",
                "production_boundary": "Only manages the ScholarOutboundManager sidecar. It does not modify production Xray/XrayR/x-ui.",
                "candidate_selector_enabled": False,
                "candidate_selector_message": "Testing artifacts are stale. Run Test Nodes before changing routes.",
                "selected_index": 0,
                "can_apply": False,
                "validation_errors": ["Testing artifacts are stale. Run Test Nodes before changing routes."],
            }
        },
    )

    assert "Candidate: (not selected)" in rendered
    assert "Candidate selector: disabled" in rendered
    assert "Testing artifacts are stale. Run Test Nodes before changing routes." in rendered
    assert "Apply available: no" in rendered
