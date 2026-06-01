"""Generation helpers for Xray outbounds, routes, and manifests."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import GeneratedNode
from scholar_outbound_manager.models import GenerationConfig
from scholar_outbound_manager.models import OutputConfig
from scholar_outbound_manager.models import ProbeResult
from scholar_outbound_manager.models import RoutingConfig
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.state.manifest import build_manifest
from scholar_outbound_manager.state.manifest import write_manifest
from scholar_outbound_manager.xray.outbound import build_xray_outbound
from scholar_outbound_manager.xray.route_builder import build_dedicated_inbound_routes


def build_generated_nodes(
    candidates: list[CandidateProxy],
    tag_prefix: str,
    max_nodes: int,
    probe_results: list[ProbeResult | None] | None = None,
) -> list[GeneratedNode]:
    """Build generated nodes from supported Xray-compatible candidates."""
    generated_nodes, _ = _select_candidates(candidates, tag_prefix, max_nodes, probe_results)
    return generated_nodes


def write_generation_outputs(
    candidates: list[CandidateProxy],
    output_config: OutputConfig,
    generation_config: GenerationConfig,
    routing_config: RoutingConfig,
    probe_results: list[ProbeResult | None] | None = None,
) -> dict[str, object]:
    """Write outbounds, routes, and manifest artifacts for Phase 3 generation."""
    if routing_config.mode != "dedicated_inbound":
        raise ValueError("Only dedicated_inbound routing mode is supported in Phase 3b.")

    generated_nodes, rejected_candidates = _select_candidates(
        candidates,
        generation_config.tag_prefix,
        generation_config.max_passed_nodes,
        probe_results,
    )

    outbounds = [node.outbound for node in generated_nodes]
    if routing_config.fail_closed and not generated_nodes:
        outbounds.append(
            {
                "tag": generation_config.fallback_blackhole_tag,
                "protocol": "blackhole",
            }
        )

    routes = build_dedicated_inbound_routes(
        generated_nodes=generated_nodes,
        inbound_tags=routing_config.inbound_tags,
        fallback_blackhole_tag=generation_config.fallback_blackhole_tag,
        fail_closed=routing_config.fail_closed,
    )

    manifest = build_manifest(
        selected_nodes=generated_nodes,
        rejected_candidates=rejected_candidates,
    )

    atomic_write_json(output_config.outbounds_path, {"outbounds": outbounds})
    atomic_write_json(output_config.routes_path, {"routing": {"rules": routes}})
    write_manifest(output_config.manifest_path, manifest)

    return {
        "selected_count": len(generated_nodes),
        "rejected_count": len(rejected_candidates),
        "outbounds_path": str(Path(output_config.outbounds_path)),
        "routes_path": str(Path(output_config.routes_path)),
        "manifest_path": str(Path(output_config.manifest_path)),
    }


def _select_candidates(
    candidates: list[CandidateProxy],
    tag_prefix: str,
    max_nodes: int,
    probe_results: list[ProbeResult | None] | None = None,
) -> tuple[list[GeneratedNode], list[CandidateProxy]]:
    """Select generated nodes and collect rejected candidates."""
    if probe_results is not None and len(probe_results) != len(candidates):
        raise ValueError("probe_results must match the candidate list length.")

    generated_nodes: list[GeneratedNode] = []
    rejected_candidates: list[CandidateProxy] = []
    processed_indices: set[int] = set()

    for index, candidate in enumerate(candidates):
        if len(generated_nodes) >= max_nodes:
            rejected_candidates.append(candidate)
            processed_indices.add(index)
            continue
        if not candidate.supported:
            rejected_candidates.append(candidate)
            processed_indices.add(index)
            continue
        tag = f"{tag_prefix}{len(generated_nodes) + 1:03d}"
        try:
            outbound = build_xray_outbound(candidate, tag)
        except ValueError as exc:
            rejected_candidates.append(
                _with_rejection_reason(candidate, f"Xray outbound is not supported: {exc}")
            )
            processed_indices.add(index)
            continue
        generated_nodes.append(
            GeneratedNode(
                tag=tag,
                candidate=candidate,
                outbound=outbound,
                probe=None if probe_results is None else probe_results[index],
            )
        )
        processed_indices.add(index)

    for index, candidate in enumerate(candidates):
        if index in processed_indices:
            continue
        rejected_candidates.append(candidate)

    return generated_nodes, rejected_candidates


def _with_rejection_reason(candidate: CandidateProxy, reason: str) -> CandidateProxy:
    """Return a rejected candidate copy that preserves the rejection reason."""
    candidate_data = candidate.to_dict()
    candidate_data["unsupported_reason"] = reason
    candidate_data["supported"] = False
    return CandidateProxy(**candidate_data)
