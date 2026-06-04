"""Tests for the Testing screen model."""

from __future__ import annotations

from scholar_outbound_manager.tui.view_model import build_testing_table_model


def test_testing_table_model_has_candidate_columns() -> None:
    model = build_testing_table_model(
        {
            "testing": {
                "candidate_rows": [
                    {
                        "index": 1,
                        "region": "US",
                        "label": "US relay",
                        "protocol": "vless",
                        "passed": True,
                        "latency_ms": 1200,
                        "home_status": 200,
                        "query_status": 200,
                        "stage": "full_access",
                        "failure_marker_count": 0,
                    }
                ]
            }
        }
    )

    assert model.columns == ["status", "#", "region", "label", "protocol", "latency", "home", "query", "stage", "markers"]
    assert model.rows[0][0] == "PASS"
    assert "scholar-outbound-manager probe" not in str(model.rows)
