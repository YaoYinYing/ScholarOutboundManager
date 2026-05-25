"""Tests for core dataclass models."""

from scholar_outbound_manager.models import CandidateProxy


def test_candidate_proxy_to_dict_contains_core_fields() -> None:
    """Expose core candidate fields through dictionary serialization."""
    candidate = CandidateProxy(
        source_name="third_party_main",
        raw_name="sample-node",
        protocol="vless",
        address="example.invalid",
        port=443,
        user_id="00000000-0000-0000-0000-000000000000",
        network="tcp",
        security="reality",
    )

    result = candidate.to_dict()

    assert result["source_name"] == "third_party_main"
    assert result["raw_name"] == "sample-node"
    assert result["protocol"] == "vless"
    assert result["address"] == "example.invalid"
    assert result["port"] == 443
    assert result["user_id"] == "00000000-0000-0000-0000-000000000000"
