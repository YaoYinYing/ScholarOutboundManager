from __future__ import annotations

from scholar_outbound_manager.tui.testing_events import TestingEvent
from scholar_outbound_manager.tui.testing_events import render_testing_event_line


def test_render_testing_event_line_is_redacted() -> None:
    event = TestingEvent(
        event_type="candidate_result",
        candidate_id="candidate-001",
        index=1,
        label="US relay",
        region_hint="US",
        protocol="vless",
        status="PASS",
        home_status=200,
        query_status=200,
        stage="full_access",
        markers=(),
        latency_ms=1200,
        current=1,
        total=3,
        message="vless://00000000-0000-0000-0000-000000000000@example.invalid",
    )

    rendered = render_testing_event_line(event)

    assert "vless://" not in rendered
    assert "example.invalid" not in rendered
    assert "US relay" in rendered
