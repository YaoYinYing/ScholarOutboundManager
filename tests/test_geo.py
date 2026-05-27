"""Tests for cached Geo helpers."""

from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone
from pathlib import Path

import pytest

from scholar_outbound_manager.geo import build_geo_refresh_plan
from scholar_outbound_manager.geo import CandidateGeoRecord
from scholar_outbound_manager.geo import GeoPoint
from scholar_outbound_manager.geo import haversine_distance_km
from scholar_outbound_manager.geo import inspect_geo_database
from scholar_outbound_manager.geo import is_geo_record_expired
from scholar_outbound_manager.geo import load_candidate_geo_cache
from scholar_outbound_manager.geo import load_host_geo
from scholar_outbound_manager.geo import rank_candidates_by_geo
from scholar_outbound_manager.geo import summarize_candidate_geo_cache
from scholar_outbound_manager.selection import CandidateCatalogEntry


def test_load_host_geo(tmp_path: Path) -> None:
    """Load one host geo record from local JSON."""
    path = tmp_path / "host_geo.json"
    path.write_text(
        json.dumps(
            {
                "country": "TW",
                "region": "Taipei",
                "city": "Taipei",
                "latitude": 25.033,
                "longitude": 121.565,
                "accuracy_radius_km": 50,
                "source": "manual",
                "updated_at": "2026-05-27T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    geo = load_host_geo(path)

    assert geo is not None
    assert geo.country == "TW"
    assert geo.latitude == 25.033


def test_candidate_geo_record_loads_old_schema(tmp_path: Path) -> None:
    """Load old cache schema with defaults for new fields."""
    path = tmp_path / "candidate_geo_cache.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "candidate_id": "candidate-001",
                        "protocol": "vless",
                        "geo": {
                            "country": "JP",
                            "city": "Tokyo",
                            "latitude": 35.6762,
                            "longitude": 139.6503,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    record = load_candidate_geo_cache(path)["candidate-001"]

    assert record.observed_via == "unknown"
    assert record.egress_ip_hash is None
    assert record.expires_at is None


def test_candidate_geo_record_loads_extended_schema(tmp_path: Path) -> None:
    """Load new cache metadata fields."""
    path = tmp_path / "candidate_geo_cache.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "candidate_id": "candidate-001",
                        "protocol": "vless",
                        "geo": {
                            "country": "JP",
                            "city": "Tokyo",
                            "latitude": 35.6762,
                            "longitude": 139.6503,
                        },
                        "observed_via": "egress_geo",
                        "egress_ip_hash": "sha256:abc123",
                        "updated_at": "2026-05-27T00:00:00Z",
                        "expires_at": "2026-06-27T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    record = load_candidate_geo_cache(path)["candidate-001"]

    assert record.observed_via == "egress_geo"
    assert record.egress_ip_hash == "sha256:abc123"
    assert record.expires_at == "2026-06-27T00:00:00Z"


def test_load_candidate_geo_cache_rejects_malformed_record(tmp_path: Path) -> None:
    """Reject malformed cache entries clearly."""
    path = tmp_path / "candidate_geo_cache.json"
    path.write_text(
        json.dumps({"schema_version": 1, "records": [{"candidate_id": "candidate-001"}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must contain protocol"):
        load_candidate_geo_cache(path)


def test_missing_candidate_geo_cache_returns_empty_mapping(tmp_path: Path) -> None:
    """Treat a missing cache file as an empty cache."""
    assert load_candidate_geo_cache(tmp_path / "missing.json") == {}


def test_is_geo_record_expired_handles_missing_and_invalid_values() -> None:
    """Treat missing expiry as false and invalid expiry as expired."""
    record = CandidateGeoRecord("candidate-001", "vless", GeoPoint())
    assert is_geo_record_expired(record) is False
    invalid_record = CandidateGeoRecord("candidate-001", "vless", GeoPoint(), expires_at="bad-value")
    assert is_geo_record_expired(invalid_record) is True


def test_summarize_candidate_geo_cache_counts_sources_and_expired_records() -> None:
    """Summarize endpoint, egress, manual, expired, and missing-coordinate counts."""
    records = {
        "candidate-001": CandidateGeoRecord(
            "candidate-001",
            "vless",
            GeoPoint(latitude=1.0, longitude=2.0),
            observed_via="endpoint_geo",
        ),
        "candidate-002": CandidateGeoRecord(
            "candidate-002",
            "vless",
            GeoPoint(latitude=1.0, longitude=2.0),
            observed_via="egress_geo",
            expires_at="2020-01-01T00:00:00Z",
        ),
        "candidate-003": CandidateGeoRecord(
            "candidate-003",
            "vless",
            GeoPoint(),
            observed_via="manual",
        ),
    }

    summary = summarize_candidate_geo_cache(records)

    assert summary.record_count == 3
    assert summary.endpoint_geo_count == 1
    assert summary.egress_geo_count == 1
    assert summary.manual_count == 1
    assert summary.expired_count == 1
    assert summary.missing_coordinates_count == 1


def test_inspect_geo_database_missing_file() -> None:
    """Inspect a missing Geo DB path without reading contents."""
    info = inspect_geo_database("/tmp/does-not-exist.mmdb")

    assert info.exists is False
    assert info.readable is False
    assert info.size_bytes is None
    assert info.format_hint == "maxmind-mmdb"


def test_inspect_geo_database_existing_mmdb_file(tmp_path: Path) -> None:
    """Inspect an existing Geo DB file by metadata only."""
    path = tmp_path / "GeoLite2-City.mmdb"
    path.write_bytes(b"not-a-real-mmdb")

    info = inspect_geo_database(path)

    assert info.exists is True
    assert info.readable is True
    assert info.size_bytes == len(b"not-a-real-mmdb")
    assert info.format_hint == "maxmind-mmdb"
    assert info.error is None


def test_haversine_distance_km_returns_none_without_coordinates() -> None:
    """Return None when one side lacks coordinates."""
    assert haversine_distance_km(GeoPoint(latitude=25.0), GeoPoint(longitude=121.0)) is None


def test_haversine_distance_km_returns_expected_positive_distance() -> None:
    """Return a positive distance between two valid points."""
    distance = haversine_distance_km(
        GeoPoint(latitude=25.033, longitude=121.565),
        GeoPoint(latitude=35.6762, longitude=139.6503),
    )

    assert distance is not None
    assert distance > 1000


def test_rank_candidates_by_geo_orders_by_distance_then_index() -> None:
    """Rank candidates by smaller cached distance first."""
    catalog = [
        _catalog_entry(0, "candidate-001"),
        _catalog_entry(1, "candidate-002"),
        _catalog_entry(2, "candidate-003"),
    ]
    host_geo = GeoPoint(latitude=25.033, longitude=121.565)
    candidate_geo = {
        "candidate-001": CandidateGeoRecord("candidate-001", "vless", GeoPoint(latitude=35.6762, longitude=139.6503)),
        "candidate-002": CandidateGeoRecord("candidate-002", "vless", GeoPoint(latitude=22.3193, longitude=114.1694)),
    }

    ranked = rank_candidates_by_geo(catalog, host_geo, candidate_geo)

    assert ranked[0][0].candidate_id == "candidate-002"
    assert ranked[-1][0].candidate_id == "candidate-003"
    assert ranked[-1][1] is None


def test_build_geo_refresh_plan_counts_missing_and_expired() -> None:
    """Build a dry-run plan using candidate IDs only."""
    payload = {
        "schema_version": 1,
        "sensitive": True,
        "candidates": [
            {"candidate": {"source_name": "fixture", "raw_name": "a", "protocol": "vless", "address": "example.invalid", "port": 443, "supported": True}, "probe": {"candidate_id": "candidate-001", "passed": True, "failure_markers": []}},
            {"candidate": {"source_name": "fixture", "raw_name": "b", "protocol": "vless", "address": "example.invalid", "port": 443, "supported": True}, "probe": {"candidate_id": "candidate-002", "passed": True, "failure_markers": []}},
            {"candidate": {"source_name": "fixture", "raw_name": "c", "protocol": "vless", "address": "example.invalid", "port": 443, "supported": True}, "probe": {"candidate_id": "candidate-003", "passed": True, "failure_markers": []}},
        ],
    }
    cache = {
        "candidate-001": CandidateGeoRecord("candidate-001", "vless", GeoPoint(latitude=1.0, longitude=2.0)),
        "candidate-002": CandidateGeoRecord(
            "candidate-002",
            "vless",
            GeoPoint(latitude=1.0, longitude=2.0),
            expires_at="2020-01-01T00:00:00Z",
        ),
    }

    plan = build_geo_refresh_plan(payload, cache, refresh_expired=True)

    assert plan.candidate_count == 3
    assert plan.cached_count == 2
    assert plan.missing_count == 1
    assert plan.expired_count == 1
    assert plan.would_refresh_count == 2
    assert plan.mode == "dry_run"


def _catalog_entry(index: int, candidate_id: str) -> CandidateCatalogEntry:
    return CandidateCatalogEntry(
        index=index,
        candidate_id=candidate_id,
        protocol="vless",
        source_name="fixture",
        supported=True,
        scholar_stage="full_access",
        passed=True,
        home_status=200,
        query_status=200,
        checked_at="2026-05-27T00:00:00Z",
        failure_marker_count=0,
        failure_markers=[],
        latency_ms=10,
        tags=[],
    )
