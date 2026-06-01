"""Single-Xray multi-port Scholar sidecar pool helpers."""

from __future__ import annotations

import json
import socket
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.probe.http_probe import SocksEndpoint
from scholar_outbound_manager.probe.http_probe import probe_http_via_socks
from scholar_outbound_manager.probe.scholar_classifier import build_scholar_home_target
from scholar_outbound_manager.probe.scholar_classifier import build_scholar_query_target
from scholar_outbound_manager.probe.scholar_classifier import classify_scholar_access
from scholar_outbound_manager.selection import CandidateSelectionRecord
from scholar_outbound_manager.selection import extract_candidate_selection_records
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.xray.outbound import build_xray_outbound
from scholar_outbound_manager.xray.runtime_config import build_local_socks_inbound


@dataclass(slots=True)
class SidecarPoolEntry:
    """Represent one local SOCKS port mapped to one candidate outbound."""

    pool_index: int
    candidate_id: str
    candidate_protocol: str
    listen_host: str
    listen_port: int
    inbound_tag: str
    outbound_tag: str
    socks_tag: str


@dataclass(slots=True)
class SidecarPoolPlan:
    """Represent one redacted single-Xray multi-port pool plan."""

    created_at: str
    listen_host: str
    base_port: int
    count: int
    entries: list[SidecarPoolEntry]
    schema_version: int = 1
    mode: str = "single_xray_multi_port"


def build_sidecar_pool_plan(
    payload: dict[str, object],
    *,
    candidate_ids: list[str] | None = None,
    max_count: int | None = None,
    listen_host: str = "127.0.0.1",
    base_port: int = 19080,
    inbound_tag_prefix: str = "scholar-sidecar-socks-in",
    outbound_tag_prefix: str = "scholar-sidecar-out",
    socks_tag_prefix: str = "scholar-sidecar-socks-out",
) -> SidecarPoolPlan:
    """Build one single-Xray multi-port pool plan from candidate payload."""
    if not listen_host:
        raise ValueError("listen_host must not be empty.")
    if max_count is not None and max_count <= 0:
        raise ValueError("max_count must be greater than 0.")
    _validate_port(base_port, "base_port")

    records = extract_candidate_selection_records(payload)
    passed_records = [record for record in records if _record_is_passed(record)]
    selected_records = _select_records_for_pool(passed_records, candidate_ids=candidate_ids)
    if max_count is not None:
        selected_records = selected_records[:max_count]

    entries: list[SidecarPoolEntry] = []
    used_ports: set[int] = set()
    for pool_index, record in enumerate(selected_records):
        listen_port = base_port + pool_index
        _validate_port(listen_port, f"listen_port for pool index {pool_index}")
        if listen_port in used_ports:
            raise ValueError(f"duplicate listen port generated for pool index {pool_index}: {listen_port}")
        used_ports.add(listen_port)
        entries.append(
            SidecarPoolEntry(
                pool_index=pool_index,
                candidate_id=record.candidate_id,
                candidate_protocol=record.candidate.protocol,
                listen_host=listen_host,
                listen_port=listen_port,
                inbound_tag=f"{inbound_tag_prefix}-{pool_index}",
                outbound_tag=f"{outbound_tag_prefix}-{pool_index}",
                socks_tag=f"{socks_tag_prefix}-{pool_index}",
            )
        )

    return SidecarPoolPlan(
        created_at=_utc_now_iso8601(),
        listen_host=listen_host,
        base_port=base_port,
        count=len(entries),
        entries=entries,
    )


def pool_plan_to_dict(plan: SidecarPoolPlan) -> dict[str, object]:
    """Convert one pool plan to a plain dictionary."""
    return asdict(plan)


def write_pool_plan(path: str | Path, plan: SidecarPoolPlan) -> None:
    """Write one redacted pool plan artifact."""
    atomic_write_json(path, pool_plan_to_dict(plan))


def load_pool_plan(path: str | Path) -> SidecarPoolPlan:
    """Load one pool plan artifact from disk."""
    plan_path = Path(path)
    try:
        raw_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse pool plan JSON: {plan_path}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read pool plan: {plan_path}") from exc
    if not isinstance(raw_payload, dict):
        raise ValueError("Pool plan must be a JSON object.")
    entries_payload = raw_payload.get("entries")
    if not isinstance(entries_payload, list):
        raise ValueError("Pool plan must contain an entries list.")
    entries = [SidecarPoolEntry(**_string_key_mapping(entry)) for entry in entries_payload if isinstance(entry, dict)]
    if len(entries) != len(entries_payload):
        raise ValueError("Pool plan entries must be JSON objects.")
    return SidecarPoolPlan(
        schema_version=int(raw_payload.get("schema_version", 1)),
        mode=str(raw_payload.get("mode", "single_xray_multi_port")),
        created_at=str(raw_payload.get("created_at", "")),
        listen_host=str(raw_payload.get("listen_host", "")),
        base_port=int(raw_payload.get("base_port", 0)),
        count=int(raw_payload.get("count", len(entries))),
        entries=entries,
    )


def check_tcp_port_available(host: str, port: int) -> bool:
    """Return whether one local TCP port is currently available for binding."""
    if not host:
        raise ValueError("host must not be empty.")
    _validate_port(port, "port")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        return True
    except OSError:
        return False


def check_pool_ports_available(plan: SidecarPoolPlan) -> dict[int, bool]:
    """Return one pool-index to availability mapping for the plan ports."""
    return {
        entry.pool_index: check_tcp_port_available(entry.listen_host, entry.listen_port)
        for entry in plan.entries
    }


def build_multi_port_sidecar_runtime_config(
    *,
    entries: list[SidecarPoolEntry],
    candidates_by_id: dict[str, CandidateProxy],
) -> dict[str, object]:
    """Build one sensitive Xray config with multiple localhost SOCKS inbounds."""
    inbounds: list[dict[str, object]] = []
    outbounds: list[dict[str, object]] = []
    rules: list[dict[str, object]] = []
    for entry in entries:
        candidate = candidates_by_id.get(entry.candidate_id)
        if candidate is None:
            raise ValueError(f"candidate_id '{entry.candidate_id}' was not found for runtime config.")
        inbounds.append(
            build_local_socks_inbound(
                listen_host=entry.listen_host,
                listen_port=entry.listen_port,
                tag=entry.inbound_tag,
            )
        )
        outbounds.append(build_xray_outbound(candidate, entry.outbound_tag))
        rules.append(
            {
                "type": "field",
                "inboundTag": [entry.inbound_tag],
                "outboundTag": entry.outbound_tag,
            }
        )
    return {
        "log": {"loglevel": "warning"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"rules": rules},
    }


def build_pool_socks_outbound_snippets(plan: SidecarPoolPlan) -> list[dict[str, object]]:
    """Build downstream SOCKS outbound snippets for every pool entry."""
    return [
        {
            "tag": entry.socks_tag,
            "protocol": "socks",
            "settings": {
                "servers": [
                    {
                        "address": entry.listen_host,
                        "port": entry.listen_port,
                    }
                ]
            },
        }
        for entry in plan.entries
    ]


def validate_pool_sidecar(
    plan: SidecarPoolPlan,
    *,
    query: str = "ppr",
    request_timeout: float = 15.0,
) -> list[dict[str, object]]:
    """Validate every local SOCKS endpoint in one running pool."""
    if request_timeout <= 0:
        raise ValueError("request_timeout must be greater than 0.")

    results: list[dict[str, object]] = []
    for entry in plan.entries:
        tcp_connect = _check_tcp_connect(entry.listen_host, entry.listen_port, request_timeout)
        if not tcp_connect:
            results.append(
                {
                    "pool_index": entry.pool_index,
                    "listen_port": entry.listen_port,
                    "tcp_connect": False,
                    "home_status": None,
                    "query_status": None,
                    "scholar_stage": "transport_failed",
                    "passed": False,
                    "failure_markers": ["tcp_connect_failed"],
                }
            )
            continue

        socks = SocksEndpoint(entry.listen_host, entry.listen_port)
        home = probe_http_via_socks(build_scholar_home_target(), socks, request_timeout)
        query_response = probe_http_via_socks(build_scholar_query_target(query), socks, request_timeout)
        decision = classify_scholar_access(home, query_response)
        results.append(
            {
                "pool_index": entry.pool_index,
                "listen_port": entry.listen_port,
                "tcp_connect": True,
                "home_status": home.status_code,
                "query_status": query_response.status_code,
                "scholar_stage": decision.stage,
                "passed": decision.passed,
                "failure_markers": list(decision.failure_markers),
            }
        )
    return results


def _select_records_for_pool(
    records: list[CandidateSelectionRecord],
    *,
    candidate_ids: list[str] | None,
) -> list[CandidateSelectionRecord]:
    """Select passed records for pool planning."""
    if not candidate_ids:
        return list(records)
    records_by_id = {record.candidate_id: record for record in records}
    selected: list[CandidateSelectionRecord] = []
    for candidate_id in candidate_ids:
        record = records_by_id.get(candidate_id)
        if record is None:
            raise ValueError(f"candidate_id '{candidate_id}' was not found.")
        selected.append(record)
    return selected


def _record_is_passed(record: CandidateSelectionRecord) -> bool:
    """Return whether the record qualifies as passed for pool selection."""
    if record.probe_payload is None:
        return False
    allowed_statuses = {200, 301, 302, 303, 307, 308}
    passed = record.probe_payload.get("passed")
    if isinstance(passed, bool):
        return passed and not record.probe_payload.get("failure_markers")
    home_status = record.probe_payload.get("home_status")
    query_status = record.probe_payload.get("query_status")
    if record.probe_payload.get("failure_markers"):
        return False
    return home_status in allowed_statuses and query_status in allowed_statuses


def _check_tcp_connect(host: str, port: int, timeout_seconds: float) -> bool:
    """Return whether a TCP connect to the pool SOCKS port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _validate_port(port: int, field_name: str) -> None:
    """Validate one TCP port value."""
    if port <= 0 or port > 65535:
        raise ValueError(f"{field_name} must be within 1..65535.")


def _string_key_mapping(mapping: dict[object, object]) -> dict[str, object]:
    """Normalize one mapping to string keys."""
    return {str(key): value for key, value in mapping.items()}


def _utc_now_iso8601() -> str:
    """Return one UTC timestamp with a Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
