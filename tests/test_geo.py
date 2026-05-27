"""Tests for cached Geo helpers."""

from __future__ import annotations

import json
from pathlib import Path

from scholar_outbound_manager.geo import haversine_distance_km
from scholar_outbound_manager.geo import load_candidate_geo_cache
from scholar_outbound_manager.geo import load_host_geo
from scholar_outbound_manager.geo import GeoPoint
from scholar_outbound_manager.geo import rank_candidates_by_geo
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


def test_load_candidate_geo_cache(tmp_path: Path) -> None:
    """Load the candidate geo cache without sensitive fields."""
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
                            "accuracy_radius_km": 100,
                            "source": "dbip-lite",
                            "updated_at": "2026-05-27T00:00:00Z",
                        },
                        "confidence": "city",
                        "note": "cached",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cache = load_candidate_geo_cache(path)

    assert cache["candidate-001"].protocol == "vless"
    rendered = str(cache["candidate-001"])
    assert "address" not in rendered
    assert "raw_uri" not in rendered
    assert "PUBLIC_KEY" not in rendered


def test_missing_candidate_geo_cache_returns_empty_mapping(tmp_path: Path) -> None:
    """Treat a missing cache file as an empty cache."""
    assert load_candidate_geo_cache(tmp_path / "missing.json") == {}


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
    candidate_geo = load_candidate_geo_cache_from_mapping(
        {
            "candidate-001": {"lat": 35.6762, "lon": 139.6503},
            "candidate-002": {"lat": 22.3193, "lon": 114.1694},
        }
    )

    ranked = rank_candidates_by_geo(catalog, host_geo, candidate_geo)

    assert ranked[0][0].candidate_id == "candidate-002"
    assert ranked[-1][0].candidate_id == "candidate-003"
    assert ranked[-1][1] is None


def load_candidate_geo_cache_from_mapping(raw: dict[str, dict[str, float]]) -> dict[str, object]:
    """Build a small candidate geo mapping for tests."""
    return {
        candidate_id: type(
            "CandidateGeoRecordLike",
            (),
            {
                "candidate_id": candidate_id,
                "protocol": "vless",
                "geo": GeoPoint(latitude=values["lat"], longitude=values["lon"]),
            },
        )()
        for candidate_id, values in raw.items()
    }


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
