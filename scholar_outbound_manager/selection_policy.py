"""Geo-aware candidate selection policy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from scholar_outbound_manager.geo import CandidateGeoRecord
from scholar_outbound_manager.geo import GeoPoint
from scholar_outbound_manager.geo import haversine_distance_km
from scholar_outbound_manager.geo import load_candidate_geo_cache
from scholar_outbound_manager.geo import load_host_geo
from scholar_outbound_manager.geo import rank_candidates_by_geo
from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.selection import CandidateCatalogEntry
from scholar_outbound_manager.selection import CandidateSelectionRecord
from scholar_outbound_manager.selection import build_candidate_catalog
from scholar_outbound_manager.selection import extract_candidate_selection_records
from scholar_outbound_manager.selection import load_selected_candidate_artifact
from scholar_outbound_manager.selection import select_candidate_by_id
from scholar_outbound_manager.selection import infer_probe_passed
from scholar_outbound_manager.selection import select_candidate_by_index


@dataclass(slots=True)
class SelectionPolicyOptions:
    """Define selection policy inputs."""

    preferred_candidate_id: str | None = None
    preferred_candidate_index: int | None = None
    selected_candidate_path: str | None = None
    strategy: str = "auto"
    geo_cache_path: str | None = "state_data/geo/candidate_geo_cache.json"
    host_geo_path: str | None = "state_data/geo/host_geo.json"
    prefer_geo: bool = True
    fallback_to_first: bool = True


@dataclass(slots=True)
class SelectionDecision:
    """Represent one redacted selection decision."""

    selected_candidate_id: str
    selected_index: int
    method: str
    reason: str
    candidate_protocol: str
    geo_score: float | None = None
    geo_distance_km: float | None = None
    warnings: list[str] = field(default_factory=list)


def select_candidate_with_policy(
    payload: dict[str, object],
    options: SelectionPolicyOptions,
) -> tuple[CandidateProxy, dict[str, object] | None, SelectionDecision]:
    """Select one candidate with manual override, cached geo ranking, and fallback."""
    normalized_strategy = _normalize_strategy(options.strategy)
    options = SelectionPolicyOptions(
        preferred_candidate_id=options.preferred_candidate_id,
        preferred_candidate_index=options.preferred_candidate_index,
        selected_candidate_path=options.selected_candidate_path,
        strategy=normalized_strategy,
        geo_cache_path=options.geo_cache_path,
        host_geo_path=options.host_geo_path,
        prefer_geo=options.prefer_geo,
        fallback_to_first=options.fallback_to_first,
    )
    _validate_strategy(options.strategy)
    _validate_manual_selection_inputs(options)
    if options.selected_candidate_path:
        record = load_selected_candidate_artifact(options.selected_candidate_path)
        return record.candidate, record.probe_payload, SelectionDecision(
            selected_candidate_id=record.candidate_id,
            selected_index=record.index,
            method="manual:selected_candidate",
            reason="selected_candidate_path provided",
            candidate_protocol=record.candidate.protocol,
        )

    if options.preferred_candidate_id is not None:
        record = select_candidate_by_id(payload, options.preferred_candidate_id)
        return _record_to_selection(record, method="manual:candidate_id", reason="preferred_candidate_id provided")

    if options.preferred_candidate_index is not None:
        record = select_candidate_by_index(payload, options.preferred_candidate_index)
        return _record_to_selection(record, method="manual:index", reason="preferred_candidate_index provided")

    strategy = _resolve_effective_strategy(payload, options)
    if strategy == "geo_nearest":
        return _select_geo_nearest(payload, options)
    if strategy == "first":
        return _select_first_available(
            payload,
            method="first",
            reason="selected first available candidate",
            fallback_to_first=options.fallback_to_first,
        )
    if strategy == "manual":
        raise ValueError("manual strategy requires selected_candidate_path, preferred_candidate_id, or preferred_candidate_index.")
    raise ValueError(f"Unsupported selection strategy: {strategy}")


def explain_selection_policy(
    payload: dict[str, object],
    options: SelectionPolicyOptions,
) -> dict[str, object]:
    """Build one redacted explanation payload for selection ordering."""
    catalog = build_candidate_catalog(payload)
    warnings: list[str] = []
    host_geo = _load_host_geo_for_policy(options, warnings)
    candidate_geo = _load_candidate_geo_for_policy(options, warnings)
    ranked = (
        rank_candidates_by_geo(catalog, host_geo, candidate_geo)
        if host_geo is not None and candidate_geo
        else [(entry, None) for entry in catalog]
    )
    _, _, decision = select_candidate_with_policy(payload, options)
    normalized_strategy = _normalize_strategy(options.strategy)
    options = SelectionPolicyOptions(
        preferred_candidate_id=options.preferred_candidate_id,
        preferred_candidate_index=options.preferred_candidate_index,
        selected_candidate_path=options.selected_candidate_path,
        strategy=normalized_strategy,
        geo_cache_path=options.geo_cache_path,
        host_geo_path=options.host_geo_path,
        prefer_geo=options.prefer_geo,
        fallback_to_first=options.fallback_to_first,
    )
    return {
        "strategy": options.strategy,
        "effective_strategy": _resolve_effective_strategy(payload, options),
        "decision": {
            "selected_candidate_id": decision.selected_candidate_id,
            "selected_index": decision.selected_index,
            "method": decision.method,
            "reason": decision.reason,
            "candidate_protocol": decision.candidate_protocol,
            "geo_score": decision.geo_score,
            "geo_distance_km": decision.geo_distance_km,
            "warnings": list(decision.warnings),
        },
        "catalog": [
            {
                "index": entry.index,
                "candidate_id": entry.candidate_id,
                "protocol": entry.protocol,
                "passed": entry.passed,
                "stage": entry.scholar_stage,
                "home_status": entry.home_status,
                "query_status": entry.query_status,
                "geo_distance_km": distance,
            }
            for entry, distance in ranked
        ],
        "warnings": warnings,
    }


def _resolve_effective_strategy(payload: dict[str, object], options: SelectionPolicyOptions) -> str:
    """Resolve the effective strategy from policy options and cache availability."""
    if options.strategy == "manual":
        return "manual"
    if options.strategy == "geo_nearest":
        return "geo_nearest"
    if options.strategy == "first":
        return "first"

    if (
        options.selected_candidate_path is not None
        or options.preferred_candidate_id is not None
        or options.preferred_candidate_index is not None
    ):
        return "manual"

    if options.prefer_geo:
        try:
            host_geo = _safe_load_host_geo(options.host_geo_path)
            candidate_geo = _safe_load_candidate_geo_cache(options.geo_cache_path)
        except ValueError:
            host_geo = None
            candidate_geo = {}
        if host_geo is not None and candidate_geo:
            return "geo_nearest"

    if options.fallback_to_first:
        return "first"
    raise ValueError("auto strategy could not resolve a selection path and fallback_to_first is disabled.")


def _select_geo_nearest(
    payload: dict[str, object],
    options: SelectionPolicyOptions,
) -> tuple[CandidateProxy, dict[str, object] | None, SelectionDecision]:
    """Select the nearest candidate from cached Geo data."""
    warnings: list[str] = []
    host_geo = _load_host_geo_for_policy(options, warnings)
    candidate_geo = _load_candidate_geo_for_policy(options, warnings)
    if host_geo is None or not candidate_geo:
        if options.fallback_to_first:
            candidate, probe, decision = _select_first_available(
                payload,
                method="fallback:first",
                reason="geo cache unavailable, fell back to first available candidate",
                fallback_to_first=True,
            )
            decision.warnings.extend(warnings)
            return candidate, probe, decision
        raise ValueError("geo_nearest strategy requires host_geo and candidate_geo cache.")

    catalog = _build_eligible_catalog(payload)
    ranked = rank_candidates_by_geo(catalog, host_geo, candidate_geo)
    if not ranked:
        raise ValueError("No candidates are available for selection.")
    selected_entry, geo_distance = ranked[0]
    record = select_candidate_by_id(payload, selected_entry.candidate_id)
    decision = SelectionDecision(
        selected_candidate_id=record.candidate_id,
        selected_index=record.index,
        method="geo_nearest",
        reason="selected nearest candidate from local geo cache",
        candidate_protocol=record.candidate.protocol,
        geo_score=None if geo_distance is None else -geo_distance,
        geo_distance_km=geo_distance,
        warnings=warnings,
    )
    return record.candidate, record.probe_payload, decision


def _select_first_available(
    payload: dict[str, object],
    *,
    method: str,
    reason: str,
    fallback_to_first: bool,
) -> tuple[CandidateProxy, dict[str, object] | None, SelectionDecision]:
    """Select the first passed candidate, or the first supported candidate as fallback."""
    if not fallback_to_first:
        raise ValueError("fallback_to_first is disabled and no other strategy selected a candidate.")
    records = extract_candidate_selection_records(payload)
    passed_record = next((record for record in records if _record_is_passed(record)), None)
    if passed_record is not None:
        return _record_to_selection(passed_record, method=method, reason=reason)
    supported_record = next((record for record in records if record.candidate.supported), None)
    if supported_record is not None:
        candidate, probe, decision = _record_to_selection(
            supported_record,
            method=method,
            reason=f"{reason}; no passed candidate available, used first supported candidate",
        )
        decision.warnings.append("no_passed_candidate")
        return candidate, probe, decision
    raise ValueError("No candidates are available for selection.")


def _build_eligible_catalog(payload: dict[str, object]) -> list[CandidateCatalogEntry]:
    """Build the catalog entries eligible for geo ranking."""
    catalog = build_candidate_catalog(payload)
    passed_entries = [entry for entry in catalog if entry.passed]
    if passed_entries:
        return passed_entries
    return [entry for entry in catalog if entry.supported]


def _record_to_selection(
    record: CandidateSelectionRecord,
    *,
    method: str,
    reason: str,
) -> tuple[CandidateProxy, dict[str, object] | None, SelectionDecision]:
    """Convert one record into the selection tuple."""
    return record.candidate, record.probe_payload, SelectionDecision(
        selected_candidate_id=record.candidate_id,
        selected_index=record.index,
        method=method,
        reason=reason,
        candidate_protocol=record.candidate.protocol,
    )


def _record_is_passed(record: CandidateSelectionRecord) -> bool:
    """Return whether the selection record qualifies as passed."""
    return infer_probe_passed(record.probe_payload)


def _load_host_geo_for_policy(options: SelectionPolicyOptions, warnings: list[str]) -> GeoPoint | None:
    """Load host Geo while accumulating warnings."""
    try:
        return _safe_load_host_geo(options.host_geo_path)
    except ValueError as exc:
        warnings.append(str(exc))
        return None


def _load_candidate_geo_for_policy(
    options: SelectionPolicyOptions,
    warnings: list[str],
) -> dict[str, CandidateGeoRecord]:
    """Load candidate Geo cache while accumulating warnings."""
    try:
        return _safe_load_candidate_geo_cache(options.geo_cache_path)
    except ValueError as exc:
        warnings.append(str(exc))
        return {}


def _safe_load_host_geo(path: str | None) -> GeoPoint | None:
    """Load host geo only when a path is configured."""
    if not path:
        return None
    return load_host_geo(path)


def _safe_load_candidate_geo_cache(path: str | None) -> dict[str, CandidateGeoRecord]:
    """Load candidate geo cache only when a path is configured."""
    if not path:
        return {}
    return load_candidate_geo_cache(path)


def _validate_strategy(strategy: str) -> None:
    """Validate one strategy option."""
    if strategy not in {"manual", "geo_nearest", "first", "auto"}:
        raise ValueError("strategy must be one of: manual, geo_nearest, first, auto.")


def _normalize_strategy(strategy: str) -> str:
    """Normalize user-facing strategy spellings."""
    if strategy == "geo-nearest":
        return "geo_nearest"
    return strategy


def _validate_manual_selection_inputs(options: SelectionPolicyOptions) -> None:
    """Validate that manual selectors are not conflicting."""
    active = [
        value
        for value in (
            options.preferred_candidate_id,
            options.preferred_candidate_index,
            options.selected_candidate_path,
        )
        if value is not None
    ]
    if len(active) > 1:
        raise ValueError(
            "selected_candidate_path, preferred_candidate_id, and preferred_candidate_index are mutually exclusive."
        )
