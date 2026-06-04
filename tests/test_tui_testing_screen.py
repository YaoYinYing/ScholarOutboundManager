"""Tests for Testing screen rendering helpers."""

from __future__ import annotations

from scholar_outbound_manager.tui.app import render_tab_text
from scholar_outbound_manager.tui.view_model import build_testing_table_model


def test_testing_table_model_has_candidate_columns() -> None:
    model = build_testing_table_model(
        {
            "testing": {
                "rows": [
                    {
                        "index": 1,
                        "region_hint": "US",
                        "label": "US relay",
                        "protocol": "vless",
                        "passed": True,
                        "status_icon": "PASS",
                        "latency_ms": 1200,
                        "home_status": 200,
                        "query_status": 200,
                        "stage": "full_access",
                        "markers": (),
                    }
                ]
            }
        }
    )

    assert model.columns == ["status", "#", "region", "label", "protocol", "latency", "home", "query", "stage", "markers"]
    assert model.rows[0][0] == "PASS"
    assert "scholar-outbound-manager probe" not in str(model.rows)


def test_render_testing_page_uses_workbench_language_not_command_dump() -> None:
    rendered = render_tab_text(
        "Testing",
        {
            "testing": {
                "job_state": "idle",
                "progress_current": 1,
                "progress_total": 3,
                "summary": {
                    "subscription_configured": True,
                    "last_fetch_status": "ready",
                    "candidate_count": 3,
                    "supported_count": 2,
                    "experimental_disabled_count": 1,
                    "attempted_count": 2,
                    "passed_count": 1,
                    "failed_count": 1,
                },
                "rows": [
                    {
                        "index": 18,
                        "region_hint": "US",
                        "label": "US relay",
                        "protocol": "vless",
                        "status_icon": "PASS",
                        "passed": True,
                        "latency_ms": 1225,
                        "home_status": 200,
                        "query_status": 200,
                        "stage": "full_access",
                        "markers": (),
                    }
                ],
                "inspector": {
                    "label": "US relay",
                    "region_hint": "US",
                    "protocol": "vless",
                    "candidate_id": "candidate-018",
                    "scholar_stage": "full_access",
                    "home_status": 200,
                    "query_status": 200,
                    "latency_ms": 1225,
                    "markers": (),
                    "selected_for_route": False,
                    "explanation": "Home and query both passed without failure markers.",
                    "artifact_warning": "Artifact lineage mismatch.\nThe current probe summary does not match the current candidates artifact.\nRun Test Nodes to rebuild probe_summary and passed_candidates.",
                },
                "log_lines": ["Probe Candidates completed successfully."],
            }
        },
    )

    assert "Fetch Subscription" in rendered
    assert "Test Nodes" in rendered
    assert "Retest Failed" in rendered
    assert "Selected candidate" in rendered
    assert "Recent events" in rendered
    assert "Artifact lineage mismatch." in rendered
    assert "scholar-outbound-manager probe" not in rendered
