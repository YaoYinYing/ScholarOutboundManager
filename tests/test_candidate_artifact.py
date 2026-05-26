"""Tests for sensitive candidate artifact construction and writing."""

from __future__ import annotations

import json

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.state.candidate_artifact import build_candidate_artifact
from scholar_outbound_manager.state.candidate_artifact import write_candidate_artifact


def test_build_candidate_artifact_includes_schema_version() -> None:
    """Include the expected schema version."""
    payload = build_candidate_artifact(
        [_candidate()],
        source_count=1,
        fetched_count=1,
        disabled_count=0,
        failed_count=0,
        total_bytes=10,
        parsed_count=1,
        unsupported_count=0,
    )

    assert payload["schema_version"] == 1


def test_build_candidate_artifact_marks_output_sensitive() -> None:
    """Mark the candidate artifact as sensitive."""
    payload = build_candidate_artifact(
        [_candidate()],
        source_count=1,
        fetched_count=1,
        disabled_count=0,
        failed_count=0,
        total_bytes=10,
        parsed_count=1,
        unsupported_count=0,
    )

    assert payload["sensitive"] is True


def test_build_candidate_artifact_warns_against_committing() -> None:
    """Include a local-only warning in the artifact description."""
    payload = build_candidate_artifact(
        [_candidate()],
        source_count=1,
        fetched_count=1,
        disabled_count=0,
        failed_count=0,
        total_bytes=10,
        parsed_count=1,
        unsupported_count=0,
    )

    assert "must not be committed" in str(payload["description"]).lower()


def test_build_candidate_artifact_keeps_raw_uri() -> None:
    """Keep raw URI material in the sensitive local artifact."""
    payload = build_candidate_artifact(
        [_candidate()],
        source_count=1,
        fetched_count=1,
        disabled_count=0,
        failed_count=0,
        total_bytes=10,
        parsed_count=1,
        unsupported_count=0,
    )

    assert payload["candidates"][0]["raw_uri"].startswith("vless://")


def test_write_candidate_artifact_persists_json(tmp_path) -> None:
    """Write one candidate artifact JSON file."""
    output_path = tmp_path / "candidates.json"
    payload = build_candidate_artifact(
        [_candidate()],
        source_count=1,
        fetched_count=1,
        disabled_count=0,
        failed_count=0,
        total_bytes=10,
        parsed_count=1,
        unsupported_count=0,
    )

    write_candidate_artifact(output_path, payload)

    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == 1


def test_candidate_artifact_helpers_do_not_print(capsys, tmp_path) -> None:
    """Avoid printing during payload construction or writing."""
    output_path = tmp_path / "candidates.json"
    payload = build_candidate_artifact(
        [_candidate()],
        source_count=1,
        fetched_count=1,
        disabled_count=0,
        failed_count=0,
        total_bytes=10,
        parsed_count=1,
        unsupported_count=0,
    )

    write_candidate_artifact(output_path, payload)
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == ""


def _candidate() -> CandidateProxy:
    """Build one placeholder candidate."""
    return CandidateProxy(
        source_name="fixture-source",
        raw_name="US Scholar IPv4",
        protocol="vless",
        address="example.invalid",
        port=443,
        user_id="00000000-0000-0000-0000-000000000000",
        public_key="PUBLIC_KEY_PLACEHOLDER",
        short_id="SHORT_ID_PLACEHOLDER",
        raw_uri="vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
        supported=True,
    )
