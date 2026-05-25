"""Tests for candidate filtering and ordering."""

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import FilterConfig
from scholar_outbound_manager.parsers.filtering import filter_candidates


def test_filter_candidates_include_exclude_and_deprioritize() -> None:
    """Apply include, exclude, and deprioritization rules consistently."""
    candidates = [
        CandidateProxy("source", "US Scholar IPv4", "vless", "a.example", 443),
        CandidateProxy("source", "US Scholar Warp", "vless", "b.example", 443),
        CandidateProxy("source", "Game Scholar IPv4", "vless", "c.example", 443),
        CandidateProxy("source", "Academic Scholar IPv6", "vless", "d.example", 443),
    ]
    config = FilterConfig(
        include_keywords=["scholar", "academic"],
        exclude_keywords=["game"],
        deprioritize_keywords=["ipv6", "warp"],
    )

    result = filter_candidates(candidates, config)

    assert [item.raw_name for item in result] == [
        "US Scholar IPv4",
        "Academic Scholar IPv6",
        "US Scholar Warp",
    ]


def test_filter_candidates_is_case_insensitive() -> None:
    """Match filtering keywords without case sensitivity."""
    candidates = [
        CandidateProxy("source", "Scholar Clean", "vless", "a.example", 443),
        CandidateProxy("source", "MEDIA node", "vless", "b.example", 443),
    ]
    config = FilterConfig(
        include_keywords=["scholar"],
        exclude_keywords=["media"],
        deprioritize_keywords=[],
    )

    result = filter_candidates(candidates, config)

    assert [item.raw_name for item in result] == ["Scholar Clean"]
