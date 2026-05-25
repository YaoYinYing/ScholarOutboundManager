"""Xray route fragment builders."""

from __future__ import annotations

from scholar_outbound_manager.models import GeneratedNode


def build_dedicated_inbound_routes(
    generated_nodes: list[GeneratedNode],
    inbound_tags: list[str],
    fallback_blackhole_tag: str,
    fail_closed: bool,
) -> list[dict[str, object]]:
    """Build dedicated inbound-to-outbound routes for generated Scholar traffic."""
    if not inbound_tags:
        raise ValueError("Dedicated inbound routing requires at least one inbound tag.")

    if generated_nodes:
        return [
            {
                "type": "field",
                "inboundTag": inbound_tags,
                "outboundTag": generated_nodes[0].tag,
            }
        ]

    if not fail_closed:
        raise ValueError("No generated nodes are available and fail_closed is disabled.")
    if not fallback_blackhole_tag:
        raise ValueError("A fallback_blackhole_tag is required for fail-closed routing.")

    return [
        {
            "type": "field",
            "inboundTag": inbound_tags,
            "outboundTag": fallback_blackhole_tag,
        }
    ]
