"""Tests for candidate selection and redacted catalog helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.selection import build_candidate_catalog
from scholar_outbound_manager.selection import build_candidate_display_label
from scholar_outbound_manager.selection import build_selected_candidate_artifact
from scholar_outbound_manager.selection import catalog_to_dicts
from scholar_outbound_manager.selection import format_candidate_catalog_table
from scholar_outbound_manager.selection import infer_region_hint
from scholar_outbound_manager.selection import load_selected_candidate_artifact
from scholar_outbound_manager.selection import redact_candidate_label
from scholar_outbound_manager.selection import select_candidate_by_id
from scholar_outbound_manager.selection import infer_probe_passed
from scholar_outbound_manager.selection import select_candidate_by_index
from scholar_outbound_manager.selection import write_selected_candidate_artifact


def test_catalog_hides_sensitive_fields_and_keeps_redacted_fields() -> None:
    """Build a redacted catalog entry without candidate secrets."""
    catalog = build_candidate_catalog(_passed_candidates_payload())

    rendered = str(catalog_to_dicts(catalog))
    assert "source_name" not in catalog_to_dicts(catalog)[0]
    assert catalog[0].candidate_id == "candidate-001"
    assert catalog[0].label == "US-LA Scholar 01"
    assert catalog[0].region_hint == "US-LA"
    assert catalog[0].scholar_stage == "full_access"
    assert catalog[0].passed is True
    assert "raw_uri" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "PASSWORD_PLACEHOLDER" not in rendered


def test_catalog_hides_hysteria2_sensitive_fields_from_extra() -> None:
    """Keep Hysteria2 auth and obfs secrets out of review-safe catalog output."""
    catalog = build_candidate_catalog(
        {
            "schema_version": 1,
            "sensitive": True,
            "candidates": [
                {
                    "candidate": _make_candidate(
                        protocol="hysteria2",
                        raw_name="HK Hysteria2",
                        password="HY2_PASSWORD_PLACEHOLDER",
                        user_id=None,
                        security="hysteria",
                        server_name="hy2.example.invalid",
                        public_key=None,
                        short_id=None,
                        raw_uri=None,
                        address="hy2.example.invalid",
                        extra={
                            "auth": "HY2_PASSWORD_PLACEHOLDER",
                            "obfs-password": "OBFS_PASSWORD_PLACEHOLDER",
                            "sni": "hy2.example.invalid",
                        },
                    ).to_dict(),
                    "probe": {
                        "candidate_id": "candidate-001",
                        "home_status": 200,
                        "query_status": 200,
                        "blocked": False,
                        "timeout": False,
                        "error": None,
                        "failure_markers": [],
                        "latency_ms": 18,
                        "checked_at": "2026-05-27T00:00:00Z",
                        "passed": True,
                    },
                }
            ],
        }
    )

    rendered = str(catalog_to_dicts(catalog))
    assert "HY2_PASSWORD_PLACEHOLDER" not in rendered
    assert "OBFS_PASSWORD_PLACEHOLDER" not in rendered
    assert "hy2.example.invalid" not in rendered


def test_catalog_table_hides_secrets() -> None:
    """Keep catalog table output free of sensitive fields."""
    table = format_candidate_catalog_table(build_candidate_catalog(_passed_candidates_payload()))

    assert "candidate-001" in table
    assert "US-LA Scholar 01" in table
    assert "full_access" in table
    assert "raw_uri" not in table
    assert "PUBLIC_KEY_PLACEHOLDER" not in table
    assert "PASSWORD_PLACEHOLDER" not in table
    assert "00000000-0000-0000-0000-000000000000" not in table


def test_redact_candidate_label_removes_uuid() -> None:
    assert redact_candidate_label("Tokyo 00000000-0000-0000-0000-000000000000") == "Tokyo <UUID>"


def test_redact_candidate_label_removes_vless_uri() -> None:
    assert redact_candidate_label("US vless://abc@example.invalid:443") == "US"


def test_redact_candidate_label_removes_secret_fields() -> None:
    redacted = redact_candidate_label("HK public_key=abc password=def token=ghi secret=jkl")
    assert redacted == "HK public_key=<REDACTED> password=<REDACTED> token=<REDACTED> secret=<REDACTED>"


def test_redact_candidate_label_removes_obvious_ip() -> None:
    assert redact_candidate_label("SG 1.2.3.4") == "SG <IP>"


def test_build_candidate_display_label_prefers_raw_name() -> None:
    assert build_candidate_display_label(
        {
            "raw_name": "US-LA Scholar 01",
            "source_name": "source-jp",
            "extra": {"display_name": "display"},
        }
    ) == "US-LA Scholar 01"


def test_build_candidate_display_label_falls_back_to_source_name() -> None:
    assert build_candidate_display_label({"raw_name": "", "source_name": "Japan Tokyo 02"}) == "Japan Tokyo 02"


def test_build_candidate_display_label_falls_back_to_extra_display_name() -> None:
    assert build_candidate_display_label({"raw_name": "", "source_name": "", "extra": {"display_name": "HK Edge"}}) == "HK Edge"


def test_infer_region_hint_uses_simple_heuristics() -> None:
    assert infer_region_hint("Los Angeles premium") == "US-LA"
    assert infer_region_hint("Tokyo premium") == "JP"


def test_select_candidate_by_id_returns_requested_record() -> None:
    """Select one candidate record by candidate ID."""
    selected = select_candidate_by_id(_passed_candidates_payload(), "candidate-001")

    assert selected.index == 0
    assert selected.candidate.protocol == "vless"


def test_select_candidate_by_index_returns_requested_payload_record() -> None:
    """Select one candidate record by payload index."""
    selected = select_candidate_by_index(_passed_candidates_payload(), 0)

    assert selected.candidate_id == "candidate-001"
    assert selected.probe_payload is not None


def test_selected_candidate_artifact_is_sensitive_and_preserves_candidate() -> None:
    """Persist a sensitive selected-candidate artifact with the real candidate payload."""
    record = select_candidate_by_id(_passed_candidates_payload(), "candidate-001")

    artifact = build_selected_candidate_artifact(record, selection_method="candidate_id")

    assert artifact["sensitive"] is True
    assert artifact["selected_candidate_id"] == "candidate-001"
    assert artifact["candidate"]["address"] == "example.invalid"
    assert artifact["candidate"]["public_key"] == "PUBLIC_KEY_PLACEHOLDER"


def test_write_and_load_selected_candidate_artifact_round_trips(tmp_path: Path) -> None:
    """Load one selected-candidate artifact without losing candidate identity."""
    record = select_candidate_by_id(_passed_candidates_payload(), "candidate-001")
    artifact = build_selected_candidate_artifact(record, selection_method="candidate_id")
    output_path = tmp_path / "selected_candidate.json"

    write_selected_candidate_artifact(output_path, artifact)
    loaded = load_selected_candidate_artifact(output_path)

    assert loaded.candidate_id == "candidate-001"
    assert loaded.candidate.address == "example.invalid"


def test_select_candidate_by_index_preserves_legacy_list_behavior() -> None:
    """Keep the original list-based selector behavior for older call sites."""
    candidates = [_make_candidate(raw_name="first"), _make_candidate(raw_name="second")]

    selected = select_candidate_by_index(candidates, 1)

    assert isinstance(selected, CandidateProxy)
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
    """Keep raw URI source material out of legacy selection errors."""
    with pytest.raises(ValueError) as exc_info:
        select_candidate_by_index(
            [_make_candidate(supported=False, unsupported_reason="Unsupported transport.")],
            0,
        )

    assert "vless://" not in str(exc_info.value)


def _passed_candidates_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "sensitive": True,
        "description": "This file contains selected proxy credentials and must not be committed.",
        "candidates": [
            {
                "candidate": _make_candidate().to_dict(),
                "probe": {
                    "candidate_id": "candidate-001",
                    "home_status": 200,
                    "query_status": 200,
                    "blocked": False,
                    "timeout": False,
                    "error": None,
                    "failure_markers": [],
                    "latency_ms": 18,
                    "checked_at": "2026-05-27T00:00:00Z",
                    "passed": True,
                },
            }
        ],
    }


def _make_candidate(**overrides: object) -> CandidateProxy:
    """Construct one placeholder candidate for selection tests."""
    candidate_data: dict[str, object] = {
        "source_name": "fixture-source",
        "raw_name": "US-LA Scholar 01",
        "protocol": "vless",
        "address": "example.invalid",
        "port": 443,
        "user_id": "00000000-0000-0000-0000-000000000000",
        "password": "PASSWORD_PLACEHOLDER",
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
        "extra": {"tags": ["scholar", "us"], "display_name": "Tokyo Backup"},
    }
    candidate_data.update(overrides)
    return CandidateProxy(**candidate_data)


def test_infer_probe_passed_scenarios() -> None:
    """Cover infer_probe_passed logic for standard and historical-style payloads."""
    # 1. infer_probe_passed() returns True when:
    #    - probe has no explicit `passed`
    #    - home_status=200
    #    - query_status=200
    #    - failure_markers=[]
    payload_1 = {
        "home_status": 200,
        "query_status": 200,
        "failure_markers": [],
    }
    assert infer_probe_passed(payload_1) is True

    # 2. infer_probe_passed() returns True when:
    #    - home_status=200
    #    - query_status=302
    #    - failure_markers=[]
    payload_2 = {
        "home_status": 200,
        "query_status": 302,
        "failure_markers": [],
    }
    assert infer_probe_passed(payload_2) is True

    # 3. infer_probe_passed() returns False when:
    #    - home_status=200
    #    - query_status=403
    #    - failure_markers contains stage_query_blocked
    payload_3 = {
        "home_status": 200,
        "query_status": 403,
        "failure_markers": ["stage_query_blocked"],
    }
    assert infer_probe_passed(payload_3) is False

    # 4. infer_probe_passed() returns False when:
    #    - passed=True
    #    - failure_markers non-empty
    payload_4 = {
        "passed": True,
        "failure_markers": ["stage_home_blocked"],
    }
    assert infer_probe_passed(payload_4) is False

    # 5. Additional edge cases
    assert infer_probe_passed(None) is False
    assert infer_probe_passed({"passed": False}) is False
    assert infer_probe_passed({"passed": True}) is True
