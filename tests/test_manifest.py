"""Tests for generation manifest construction and persistence."""

from __future__ import annotations

import json

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import GeneratedNode
from scholar_outbound_manager.state.manifest import build_manifest
from scholar_outbound_manager.state.manifest import write_manifest


def test_manifest_contains_required_top_level_fields() -> None:
    """Build a manifest with the required top-level fields."""
    manifest = build_manifest(
        selected_nodes=[_make_generated_node()],
        rejected_candidates=[_make_rejected_candidate()],
        generated_at="2026-05-25T00:00:00Z",
    )

    assert manifest["schema_version"] == 1
    assert manifest["generated_at"] == "2026-05-25T00:00:00Z"
    assert "selected" in manifest
    assert "rejected" in manifest


def test_manifest_writes_probe_none_as_null_equivalent() -> None:
    """Keep empty probe evidence as a null-compatible value."""
    manifest = build_manifest(
        selected_nodes=[_make_generated_node()],
        rejected_candidates=[],
        generated_at="2026-05-25T00:00:00Z",
    )

    assert manifest["selected"][0]["probe"] is None


def test_manifest_uses_unsupported_reason_for_rejections() -> None:
    """Prefer the unsupported reason when recording rejections."""
    manifest = build_manifest(
        selected_nodes=[],
        rejected_candidates=[_make_rejected_candidate()],
        generated_at="2026-05-25T00:00:00Z",
    )

    assert manifest["rejected"][0]["reason"] == "Unsupported transport."


def test_manifest_redacts_raw_uri() -> None:
    """Ensure raw URI content is not exposed in manifest output."""
    manifest = build_manifest(
        selected_nodes=[_make_generated_node()],
        rejected_candidates=[_make_rejected_candidate()],
        generated_at="2026-05-25T00:00:00Z",
    )

    rendered = json.dumps(manifest)
    assert "vless://" not in rendered
    assert "raw_uri" not in rendered


def test_write_manifest_persists_json_file(tmp_path) -> None:
    """Write the manifest to disk as JSON."""
    manifest = build_manifest(
        selected_nodes=[_make_generated_node()],
        rejected_candidates=[_make_rejected_candidate()],
        generated_at="2026-05-25T00:00:00Z",
    )
    output_path = tmp_path / "manifest.json"

    write_manifest(output_path, manifest)

    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == 1


def _make_generated_node() -> GeneratedNode:
    """Construct one generated node for manifest tests."""
    candidate = CandidateProxy(
        source_name="unit-test",
        raw_name="selected-node",
        protocol="vless",
        address="example.invalid",
        port=443,
        user_id="00000000-0000-0000-0000-000000000000",
        public_key="PUBLIC_KEY_PLACEHOLDER",
        raw_uri="vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
    )
    return GeneratedNode(
        tag="google-scholar-node-001",
        candidate=candidate,
        outbound={"tag": "google-scholar-node-001", "protocol": "vless"},
        probe=None,
    )


def _make_rejected_candidate() -> CandidateProxy:
    """Construct one rejected candidate for manifest tests."""
    return CandidateProxy(
        source_name="unit-test",
        raw_name="rejected-node",
        protocol="vmess",
        address="rejected.invalid",
        port=443,
        user_id="00000000-0000-0000-0000-000000000000",
        public_key="PUBLIC_KEY_PLACEHOLDER",
        raw_uri="vless://00000000-0000-0000-0000-000000000000@rejected.invalid:443",
        supported=False,
        unsupported_reason="Unsupported transport.",
    )
