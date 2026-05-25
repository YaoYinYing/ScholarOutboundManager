"""Tests for dedicated inbound route generation."""

from __future__ import annotations

import pytest

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import GeneratedNode
from scholar_outbound_manager.xray.route_builder import build_dedicated_inbound_routes


def test_route_points_to_first_selected_node() -> None:
    """Route Scholar inbound tags to the first generated outbound."""
    node = _make_generated_node("google-scholar-node-001")

    routes = build_dedicated_inbound_routes(
        generated_nodes=[node],
        inbound_tags=["scholar-in"],
        fallback_blackhole_tag="blocked-scholar",
        fail_closed=True,
    )

    assert routes == [
        {
            "type": "field",
            "inboundTag": ["scholar-in"],
            "outboundTag": "google-scholar-node-001",
        }
    ]


def test_route_points_to_blackhole_when_fail_closed() -> None:
    """Route Scholar inbound tags to blackhole when no node is selected."""
    routes = build_dedicated_inbound_routes(
        generated_nodes=[],
        inbound_tags=["scholar-in"],
        fallback_blackhole_tag="blocked-scholar",
        fail_closed=True,
    )

    assert routes[0]["outboundTag"] == "blocked-scholar"


def test_route_builder_requires_inbound_tags() -> None:
    """Reject empty inbound tag lists."""
    with pytest.raises(ValueError, match="inbound tag"):
        build_dedicated_inbound_routes(
            generated_nodes=[],
            inbound_tags=[],
            fallback_blackhole_tag="blocked-scholar",
            fail_closed=True,
        )


def test_route_builder_rejects_open_fallback() -> None:
    """Reject empty generations when fail-closed behavior is disabled."""
    with pytest.raises(ValueError, match="fail_closed is disabled"):
        build_dedicated_inbound_routes(
            generated_nodes=[],
            inbound_tags=["scholar-in"],
            fallback_blackhole_tag="blocked-scholar",
            fail_closed=False,
        )


def _make_generated_node(tag: str) -> GeneratedNode:
    """Construct one generated node for route tests."""
    candidate = CandidateProxy(
        source_name="unit-test",
        raw_name="node",
        protocol="vless",
        address="example.invalid",
        port=443,
        user_id="00000000-0000-0000-0000-000000000000",
    )
    return GeneratedNode(tag=tag, candidate=candidate, outbound={"tag": tag}, probe=None)
