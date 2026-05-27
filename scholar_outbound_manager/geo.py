"""Offline Geo cache and Geo DB boundary helpers."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from scholar_outbound_manager.selection import CandidateCatalogEntry
from scholar_outbound_manager.selection import extract_candidate_selection_records


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
    """Represent one candidate-linked cached Geo record without raw IPs."""

    candidate_id: str
    protocol: str
    geo: GeoPoint
    confidence: str = "unknown"
    note: str | None = None
    observed_via: str = "unknown"
    egress_ip_hash: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None


@dataclass(slots=True)
class GeoCacheSummary:
    """Summarize one candidate Geo cache."""

    schema_version: int
    record_count: int
    endpoint_geo_count: int
    egress_geo_count: int
    manual_count: int
    expired_count: int
    missing_coordinates_count: int


@dataclass(slots=True)
class GeoDatabaseInfo:
    """Describe one local Geo database file without parsing its contents."""

    path: str
    exists: bool
    readable: bool
    size_bytes: int | None
    format_hint: str | None
    error: str | None


@dataclass(slots=True)
class GeoRefreshPlan:
    """Summarize one dry-run candidate Geo refresh plan."""

    candidate_count: int
    cached_count: int
    missing_count: int
    expired_count: int
    would_refresh_count: int
    mode: str


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
        observed_via = _coerce_optional_str(raw_record.get("observed_via")) or "unknown"
        if observed_via not in {"endpoint_geo", "egress_geo", "manual", "unknown"}:
            observed_via = "unknown"
        egress_ip_hash = _coerce_optional_str(raw_record.get("egress_ip_hash"))
        if egress_ip_hash is not None and not egress_ip_hash.startswith("sha256:"):
            raise ValueError(f"Candidate geo record at index {index} has invalid egress_ip_hash.")
        records[candidate_id] = CandidateGeoRecord(
            candidate_id=candidate_id,
            protocol=protocol,
            geo=_build_geo_point(geo_payload),
            confidence=_coerce_optional_str(raw_record.get("confidence")) or "unknown",
            note=_coerce_optional_str(raw_record.get("note")),
            observed_via=observed_via,
            egress_ip_hash=egress_ip_hash,
            updated_at=_coerce_optional_str(raw_record.get("updated_at")),
            expires_at=_coerce_optional_str(raw_record.get("expires_at")),
        )
    return records


def summarize_candidate_geo_cache(records: dict[str, CandidateGeoRecord]) -> GeoCacheSummary:
    """Summarize one candidate Geo cache mapping."""
    endpoint_geo_count = 0
    egress_geo_count = 0
    manual_count = 0
    expired_count = 0
    missing_coordinates_count = 0
    for record in records.values():
        if record.observed_via == "endpoint_geo":
            endpoint_geo_count += 1
        elif record.observed_via == "egress_geo":
            egress_geo_count += 1
        elif record.observed_via == "manual":
            manual_count += 1
        if is_geo_record_expired(record):
            expired_count += 1
        if record.geo.latitude is None or record.geo.longitude is None:
            missing_coordinates_count += 1
    return GeoCacheSummary(
        schema_version=1,
        record_count=len(records),
        endpoint_geo_count=endpoint_geo_count,
        egress_geo_count=egress_geo_count,
        manual_count=manual_count,
        expired_count=expired_count,
        missing_coordinates_count=missing_coordinates_count,
    )


def is_geo_record_expired(record: CandidateGeoRecord, now: datetime | None = None) -> bool:
    """Return whether one cached geo record is expired."""
    if record.expires_at is None:
        return False
    try:
        expires_at = _parse_iso_datetime(record.expires_at)
    except ValueError:
        return True
    reference = datetime.now(expires_at.tzinfo) if now is None else now
    return expires_at <= reference


def inspect_geo_database(path: str | Path) -> GeoDatabaseInfo:
    """Inspect one local Geo database file without reading its contents."""
    db_path = Path(path)
    exists = db_path.exists()
    format_hint = _guess_geo_db_format(db_path)
    if not exists:
        return GeoDatabaseInfo(
            path=str(db_path),
            exists=False,
            readable=False,
            size_bytes=None,
            format_hint=format_hint,
            error=None,
        )

    try:
        stat_result = db_path.stat()
        readable = os.access(db_path, os.R_OK)
        size_bytes = stat_result.st_size
        error = None if readable else "File is not readable."
    except OSError as exc:
        readable = False
        size_bytes = None
        error = str(exc)

    return GeoDatabaseInfo(
        path=str(db_path),
        exists=True,
        readable=readable,
        size_bytes=size_bytes,
        format_hint=format_hint,
        error=error,
    )


def build_geo_refresh_plan(
    candidate_payload: dict[str, object],
    candidate_geo: dict[str, CandidateGeoRecord],
    *,
    refresh_expired: bool = True,
) -> GeoRefreshPlan:
    """Build one dry-run Geo refresh plan without network or DB access."""
    records = extract_candidate_selection_records(candidate_payload)
    candidate_count = len(records)
    cached_count = 0
    missing_count = 0
    expired_count = 0
    would_refresh_count = 0
    for record in records:
        cached_record = candidate_geo.get(record.candidate_id)
        if cached_record is None:
            missing_count += 1
            would_refresh_count += 1
            continue
        cached_count += 1
        if is_geo_record_expired(cached_record):
            expired_count += 1
            if refresh_expired:
                would_refresh_count += 1
    return GeoRefreshPlan(
        candidate_count=candidate_count,
        cached_count=cached_count,
        missing_count=missing_count,
        expired_count=expired_count,
        would_refresh_count=would_refresh_count,
        mode="dry_run",
    )


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


def _guess_geo_db_format(path: Path) -> str:
    """Guess one Geo DB format from the file extension only."""
    suffix = path.suffix.lower()
    if suffix == ".mmdb":
        return "maxmind-mmdb"
    if suffix == ".csv":
        return "csv"
    if suffix == ".json":
        return "json"
    return "unknown"


def _parse_iso_datetime(value: str) -> datetime:
    """Parse one ISO8601 datetime string with optional Z suffix."""
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


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
