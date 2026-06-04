"""Structured Testing workbench events."""

from __future__ import annotations

from dataclasses import dataclass

from scholar_outbound_manager.tui.view_model import redact_text


@dataclass(slots=True, frozen=True)
class TestingEvent:
    __test__ = False
    event_type: str
    candidate_id: str | None
    index: int | None
    label: str | None
    region_hint: str | None
    protocol: str | None
    status: str | None
    home_status: int | None
    query_status: int | None
    stage: str | None
    markers: tuple[str, ...]
    latency_ms: int | None
    current: int | None
    total: int | None
    message: str
    redacted: bool = True


def render_testing_event_line(event: TestingEvent) -> str:
    """Render one review-safe Testing event line."""
    base = redact_text(event.message)
    if event.label:
        return f"{event.event_type}: {redact_text(event.label)} | {base}"
    return f"{event.event_type}: {base}"
