"""Offline Geo cache helpers for candidate ranking."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from scholar_outbound_manager.selection import CandidateCatalogEntry


@dataclass(slots=True)
class GeoPoint:
    """Represent one cached geographic point."""

    country: str | None = None
    region: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracy_radius_km: float | None = None
    source: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class CandidateGeoRecord:
    """Represent one candidate-linked cached Geo record."""

    candidate_id: str
    protocol: str
    geo: GeoPoint
    confidence: str = "unknown"
    note: str | None = None


def load_host_geo(path: str | Path) -> GeoPoint | None:
    """Load one host Geo record when available."""
    geo_path = Path(path)
    if not geo_path.exists():
        return None
    try:
        raw_payload = json.loads(geo_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse host geo JSON: {geo_path}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read host geo file: {geo_path}") from exc
    if not isinstance(raw_payload, dict):
        raise ValueError(f"Host geo payload must be a JSON object: {geo_path}")
    return _build_geo_point(raw_payload)


def load_candidate_geo_cache(path: str | Path) -> dict[str, CandidateGeoRecord]:
    """Load one candidate Geo cache mapping keyed by candidate ID."""
    cache_path = Path(path)
    if not cache_path.exists():
        return {}
    try:
        raw_payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse candidate geo cache JSON: {cache_path}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read candidate geo cache file: {cache_path}") from exc
    if not isinstance(raw_payload, dict):
        raise ValueError(f"Candidate geo cache must be a JSON object: {cache_path}")

    records_payload = raw_payload.get("records")
    if not isinstance(records_payload, list):
        raise ValueError(f"Candidate geo cache must contain a records list: {cache_path}")

    records: dict[str, CandidateGeoRecord] = {}
    for index, raw_record in enumerate(records_payload):
        if not isinstance(raw_record, dict):
            raise ValueError(f"Candidate geo record at index {index} must be a JSON object.")
        candidate_id = raw_record.get("candidate_id")
        protocol = raw_record.get("protocol")
        geo_payload = raw_record.get("geo")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError(f"Candidate geo record at index {index} must contain candidate_id.")
        if not isinstance(protocol, str) or not protocol:
            raise ValueError(f"Candidate geo record at index {index} must contain protocol.")
        if not isinstance(geo_payload, dict):
            raise ValueError(f"Candidate geo record at index {index} must contain geo.")
        records[candidate_id] = CandidateGeoRecord(
            candidate_id=candidate_id,
            protocol=protocol,
            geo=_build_geo_point(geo_payload),
            confidence=_coerce_optional_str(raw_record.get("confidence")) or "unknown",
            note=_coerce_optional_str(raw_record.get("note")),
        )
    return records


def haversine_distance_km(a: GeoPoint, b: GeoPoint) -> float | None:
    """Return the great-circle distance between two Geo points."""
    if (
        a.latitude is None
        or a.longitude is None
        or b.latitude is None
        or b.longitude is None
    ):
        return None
    radius_km = 6371.0
    lat1 = math.radians(a.latitude)
    lon1 = math.radians(a.longitude)
    lat2 = math.radians(b.latitude)
    lon2 = math.radians(b.longitude)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    arc = 2 * math.asin(math.sqrt(haversine))
    return radius_km * arc


def rank_candidates_by_geo(
    catalog: list[CandidateCatalogEntry],
    host_geo: GeoPoint,
    candidate_geo: dict[str, CandidateGeoRecord],
) -> list[tuple[CandidateCatalogEntry, float | None]]:
    """Rank redacted candidates by cached Geo distance."""
    ranked = [
        (
            entry,
            haversine_distance_km(host_geo, candidate_geo[entry.candidate_id].geo)
            if entry.candidate_id in candidate_geo
            else None,
        )
        for entry in catalog
    ]
    return sorted(
        ranked,
        key=lambda item: (
            item[1] is None,
            float("inf") if item[1] is None else item[1],
            item[0].index,
        ),
    )


def _build_geo_point(payload: dict[str, object]) -> GeoPoint:
    """Build one GeoPoint from a JSON payload."""
    return GeoPoint(
        country=_coerce_optional_str(payload.get("country")),
        region=_coerce_optional_str(payload.get("region")),
        city=_coerce_optional_str(payload.get("city")),
        latitude=_coerce_optional_float(payload.get("latitude")),
        longitude=_coerce_optional_float(payload.get("longitude")),
        accuracy_radius_km=_coerce_optional_float(payload.get("accuracy_radius_km")),
        source=_coerce_optional_str(payload.get("source")),
        updated_at=_coerce_optional_str(payload.get("updated_at")),
    )


def _coerce_optional_float(value: object) -> float | None:
    """Coerce one optional float field."""
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_optional_str(value: object) -> str | None:
    """Coerce one optional string field."""
    if isinstance(value, str) and value:
        return value
    return None
