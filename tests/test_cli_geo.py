"""Tests for geo CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from scholar_outbound_manager import cli


def test_geo_db_info_missing_file_outputs_metadata_only(capsys) -> None:
    """Inspect a missing Geo DB file without leaking secrets."""
    exit_code = cli.main(["geo", "db-info", "--geo-db", "/tmp/missing.mmdb"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "exists: false" in captured.out
    assert "format_hint: maxmind-mmdb" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_geo_db_info_existing_mmdb_outputs_size(tmp_path: Path, capsys) -> None:
    """Inspect an existing local Geo DB file by metadata only."""
    db_path = tmp_path / "GeoLite2-City.mmdb"
    db_path.write_bytes(b"placeholder-mmdb")

    exit_code = cli.main(["geo", "db-info", "--geo-db", str(db_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "exists: true" in captured.out
    assert "readable: true" in captured.out
    assert "format_hint: maxmind-mmdb" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_geo_cache_inspect_outputs_summary_only(tmp_path: Path, capsys) -> None:
    """Print cache summary counts without listing candidate details."""
    cache_path = tmp_path / "candidate_geo_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "candidate_id": "candidate-001",
                        "protocol": "vless",
                        "geo": {"country": "JP", "city": "Tokyo", "latitude": 35.6762, "longitude": 139.6503},
                        "observed_via": "endpoint_geo",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(["geo", "cache-inspect", "--geo-cache", str(cache_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "record_count: 1" in captured.out
    assert "endpoint_geo_count: 1" in captured.out
    assert "candidate-001" not in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_geo_refresh_plan_counts_missing_and_expired_without_writing(tmp_path: Path, capsys) -> None:
    """Build a dry-run refresh plan without mutating the cache."""
    candidates_path = _write_passed_candidates(tmp_path)
    cache_path = tmp_path / "candidate_geo_cache.json"
    original_cache = {
        "schema_version": 1,
        "records": [
            {
                "candidate_id": "candidate-001",
                "protocol": "vless",
                "geo": {"country": "TW", "latitude": 25.033, "longitude": 121.565},
            },
            {
                "candidate_id": "candidate-002",
                "protocol": "trojan",
                "geo": {"country": "JP", "latitude": 35.6762, "longitude": 139.6503},
                "expires_at": "2020-01-01T00:00:00Z",
            },
        ],
    }
    cache_path.write_text(json.dumps(original_cache), encoding="utf-8")

    exit_code = cli.main(
        [
            "geo",
            "refresh-plan",
            "--candidates",
            str(candidates_path),
            "--geo-cache",
            str(cache_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "candidate_count: 3" in captured.out
    assert "cached_count: 2" in captured.out
    assert "missing_count: 1" in captured.out
    assert "expired_count: 1" in captured.out
    assert "would_refresh_count: 2" in captured.out
    assert "mode: dry_run" in captured.out
    assert json.loads(cache_path.read_text(encoding="utf-8")) == original_cache
    _assert_no_secrets(captured.out + captured.err)


def _write_passed_candidates(tmp_path: Path) -> Path:
    path = tmp_path / "passed_candidates.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sensitive": True,
                "candidates": [
                    {
                        "candidate": {
                            "source_name": "fixture",
                            "raw_name": "node-a",
                            "protocol": "vless",
                            "address": "example.invalid",
                            "port": 443,
                            "user_id": "00000000-0000-0000-0000-000000000000",
                            "public_key": "PUBLIC_KEY_PLACEHOLDER",
                            "supported": True,
                            "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
                        },
                        "probe": {"candidate_id": "candidate-001", "passed": True, "failure_markers": []},
                    },
                    {
                        "candidate": {
                            "source_name": "fixture",
                            "raw_name": "node-b",
                            "protocol": "trojan",
                            "address": "example-b.invalid",
                            "port": 443,
                            "password": "PASSWORD_PLACEHOLDER",
                            "supported": True,
                        },
                        "probe": {"candidate_id": "candidate-002", "passed": True, "failure_markers": []},
                    },
                    {
                        "candidate": {
                            "source_name": "fixture",
                            "raw_name": "node-c",
                            "protocol": "vless",
                            "address": "example-c.invalid",
                            "port": 443,
                            "supported": True,
                        },
                        "probe": {"candidate_id": "candidate-003", "passed": True, "failure_markers": []},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _assert_no_secrets(rendered: str) -> None:
    lowered = rendered.lower()
    assert "raw_uri" not in lowered
    assert "00000000-0000-0000-0000-000000000000" not in lowered
    assert "public_key_placeholder" not in lowered
    assert "password_placeholder" not in lowered
