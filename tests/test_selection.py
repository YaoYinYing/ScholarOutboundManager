"""Tests for candidate selection helpers."""

from __future__ import annotations

import pytest

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.selection import select_candidate_by_index


def test_select_candidate_by_index_returns_requested_candidate() -> None:
    """Select one candidate by zero-based index."""
    candidates = [_make_candidate(raw_name="first"), _make_candidate(raw_name="second")]

    selected = select_candidate_by_index(candidates, 1)

    assert selected.raw_name == "second"


def test_select_candidate_by_index_rejects_empty_candidates() -> None:
    """Reject selection from an empty candidate list."""
    with pytest.raises(ValueError, match="No candidates"):
        select_candidate_by_index([], 0)


def test_select_candidate_by_index_rejects_negative_index() -> None:
    """Reject negative candidate indices."""
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        select_candidate_by_index([_make_candidate()], -1)


def test_select_candidate_by_index_rejects_out_of_range_index() -> None:
    """Reject indices beyond the available candidate range."""
    with pytest.raises(ValueError, match="out of range"):
        select_candidate_by_index([_make_candidate()], 1)


def test_select_candidate_by_index_rejects_unsupported_candidate() -> None:
    """Reject unsupported candidates with their unsupported reason."""
    with pytest.raises(ValueError, match="Unsupported transport."):
        select_candidate_by_index(
            [_make_candidate(supported=False, unsupported_reason="Unsupported transport.")],
            0,
        )


def test_select_candidate_by_index_rejects_non_vless_candidate() -> None:
    """Reject candidates outside the supported Phase 4b protocol."""
    with pytest.raises(ValueError, match="only supports vless"):
        select_candidate_by_index([_make_candidate(protocol="vmess")], 0)


def test_select_candidate_by_index_error_does_not_expose_raw_uri() -> None:
    """Keep raw URI source material out of error messages."""
    with pytest.raises(ValueError) as exc_info:
        select_candidate_by_index(
            [_make_candidate(supported=False, unsupported_reason="Unsupported transport.")],
            0,
        )

    assert "vless://" not in str(exc_info.value)


def _make_candidate(**overrides: object) -> CandidateProxy:
    """Construct one placeholder candidate for selection tests."""
    candidate_data: dict[str, object] = {
        "source_name": "fixture-source",
        "raw_name": "US Scholar IPv4",
        "protocol": "vless",
        "address": "example.invalid",
        "port": 443,
        "user_id": "00000000-0000-0000-0000-000000000000",
        "encryption": "none",
        "flow": "xtls-rprx-vision",
        "network": "tcp",
        "security": "reality",
        "server_name": "www.cloudflare.com",
        "fingerprint": "chrome",
        "public_key": "PUBLIC_KEY_PLACEHOLDER",
        "short_id": "SHORT_ID_PLACEHOLDER",
        "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
        "supported": True,
        "unsupported_reason": None,
    }
    candidate_data.update(overrides)
    return CandidateProxy(**candidate_data)
