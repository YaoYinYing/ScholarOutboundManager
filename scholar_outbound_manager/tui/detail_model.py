"""On-demand detail panel helpers for the TUI."""

from __future__ import annotations


def build_testing_detail_body(testing_state: dict[str, object]) -> str:
    inspector = testing_state.get("inspector", {}) if isinstance(testing_state.get("inspector"), dict) else {}
    return "\n".join(
        [
            "Selected candidate",
            "",
            f"Label: {inspector.get('label') or 'none'}",
            f"Region: {inspector.get('region_hint') or '-'}",
            f"Protocol: {inspector.get('protocol') or '-'}",
            f"Candidate ID: {inspector.get('candidate_id') or '-'}",
            f"Scholar: {inspector.get('scholar_stage') or '-'}",
            f"Home: {inspector.get('home_status') or '-'}",
            f"Query: {inspector.get('query_status') or '-'}",
            f"Latency: {inspector.get('latency_ms') or '-'}",
            f"Markers: {', '.join(inspector.get('markers') or []) or 'none'}",
            f"Meaning: {inspector.get('explanation') or '-'}",
        ]
    )


def build_route_detail_body(route_state: dict[str, object]) -> str:
    entries = route_state.get("entries", [])
    index = int(route_state.get("selected_index", 0) or 0)
    entry = entries[index] if isinstance(entries, list) and entries and 0 <= index < len(entries) else {}
    return "\n".join(
        [
            "Selected route",
            "",
            f"Name: {entry.get('name') or 'Route'}",
            f"Candidate: {entry.get('candidate_label') or '(not selected)'}",
            f"Host: {entry.get('listen_host') or '127.0.0.1'}",
            f"Port: {entry.get('listen_port') or '19080'}",
            f"Enabled: {'yes' if entry.get('enabled', True) else 'no'}",
            f"Status: {entry.get('validation_status') or 'draft'}",
            "",
            str(route_state.get("production_boundary") or ""),
        ]
    )
