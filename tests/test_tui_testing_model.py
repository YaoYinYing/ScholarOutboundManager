"""Tests for the structured Testing workbench state."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.testing_model import build_testing_screen_state
from scholar_outbound_manager.tui.testing_model import explain_probe_failure


def test_build_testing_screen_state_handles_missing_artifacts(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, subscription_url="")
    state = build_testing_screen_state(
        config_path=str(config_path),
        user_data_paths=resolve_user_data_paths(config_path),
    )

    assert state.summary.candidate_count == 0
    assert state.summary.last_fetch_status == "missing"
    assert state.rows == []
    assert state.inspector.explanation == "No subscription URL configured. Open Settings."
    assert state.actions["stop"] is False


def test_candidates_without_probe_render_as_untested(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    _write_candidates(paths.candidates)

    state = build_testing_screen_state(config_path=str(config_path), user_data_paths=paths)

    assert state.summary.candidate_count == 4
    assert state.summary.attempted_count == 0
    assert state.rows[0].status_icon == "PEND"
    assert state.rows[0].stage == "pending"
    assert state.inspector.explanation == "This candidate has not been tested yet."


def test_passed_candidates_render_as_passed_without_probe_summary(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    _write_candidates(paths.candidates)
    _write_passed_candidates(paths.passed_candidates, ["candidate-001"])

    state = build_testing_screen_state(config_path=str(config_path), user_data_paths=paths)

    assert state.rows[0].passed is True
    assert state.rows[0].stage == "full_access"
    assert state.summary.passed_count == 1


def test_full_passed_candidates_artifact_produces_pass_rows(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    _write_candidates(paths.candidates)
    _write_probe_summary(paths.probe_summary, with_hash=True, candidates_path=paths.candidates)
    _write_full_passed_candidates(paths.passed_candidates, with_hash=True, candidates_path=paths.candidates)

    state = build_testing_screen_state(config_path=str(config_path), user_data_paths=paths)

    assert state.rows[0].status_icon == "PASS"
    assert state.summary.attempted_count == 3
    assert state.summary.passed_count == 1
    assert state.summary.failed_count == 2


def test_lineage_mismatch_marks_rows_stale_not_pending(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    _write_candidates(paths.candidates)
    _write_probe_summary(paths.probe_summary, with_hash=False, candidates_path=paths.candidates)
    _write_full_passed_candidates(paths.passed_candidates, with_hash=False, candidates_path=paths.candidates)

    state = build_testing_screen_state(config_path=str(config_path), user_data_paths=paths)

    assert state.artifacts_stale is True
    assert state.rows[0].status_icon == "STALE"
    assert state.rows[0].stage == "stale"
    assert "artifact lineage is still inconsistent" in state.inspector.explanation.lower()


def test_query_blocked_and_transport_failures_receive_readable_explanations(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    _write_candidates(paths.candidates)
    _write_probe_summary(paths.probe_summary)
    _write_passed_candidates(paths.passed_candidates, ["candidate-001"])

    query_state = build_testing_screen_state(
        config_path=str(config_path),
        user_data_paths=paths,
        selected_index=1,
    )
    transport_state = build_testing_screen_state(
        config_path=str(config_path),
        user_data_paths=paths,
        selected_index=2,
    )

    assert query_state.rows[1].stage == "query_blocked"
    assert "anti-automation" in query_state.inspector.explanation
    assert transport_state.rows[2].stage == "transport_failed"
    assert "transport failed" in transport_state.inspector.explanation


def test_hysteria2_experimental_disabled_renders_as_disabled(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, enable_hysteria2=False)
    paths = resolve_user_data_paths(config_path)
    _write_candidates(paths.candidates)

    state = build_testing_screen_state(
        config_path=str(config_path),
        user_data_paths=paths,
        selected_index=3,
    )

    assert state.rows[3].experimental is True
    assert state.rows[3].stage == "experimental_disabled"
    assert "disabled by default" in state.inspector.explanation
    assert state.summary.experimental_disabled_count == 1


def test_rows_and_inspector_do_not_expose_secret_fields(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    _write_candidates(paths.candidates)
    _write_probe_summary(paths.probe_summary)

    state = build_testing_screen_state(config_path=str(config_path), user_data_paths=paths)
    rendered_rows = json.dumps([asdict(row) for row in state.rows], ensure_ascii=False, default=str)
    rendered_inspector = json.dumps(asdict(state.inspector), ensure_ascii=False, default=str)

    for forbidden in (
        "198.51.100.10",
        "secret.example.invalid",
        "/private",
        "00000000-0000-0000-0000-000000000000",
        "PASSWORD_PLACEHOLDER",
        "vless://",
    ):
        assert forbidden not in rendered_rows
        assert forbidden not in rendered_inspector


def test_summary_counts_and_testing_log_are_redacted(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    paths = resolve_user_data_paths(config_path)
    _write_candidates(paths.candidates)
    _write_probe_summary(paths.probe_summary)
    _write_passed_candidates(paths.passed_candidates, ["candidate-001"])
    _write_action_journal(paths.action_journal)

    state = build_testing_screen_state(config_path=str(config_path), user_data_paths=paths)
    rendered_log = "\n".join(state.log_lines)

    assert state.summary.supported_count == 3
    assert state.summary.passed_count == 1
    assert state.summary.failed_count == 2
    assert state.summary.query_blocked_count == 1
    assert state.summary.transport_failed_count == 1
    assert "vless://" not in rendered_log
    assert "00000000-0000-0000-0000-000000000000" not in rendered_log
    assert "secret.example.invalid" not in rendered_log


def test_explain_probe_failure_covers_missing_probe_and_403() -> None:
    assert explain_probe_failure((), None, attempted=False, passed=False) == "This candidate has not been tested yet."
    assert explain_probe_failure(("http_403",), "review", attempted=True, passed=False) == "Scholar returned HTTP 403."


def _write_config(tmp_path: Path, *, subscription_url: str = "https://example.invalid/subscription", enable_hysteria2: bool = False) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "subscription:",
                f"  url: {subscription_url}",
                "  user_agent: Clash.Meta",
                "subscriptions:",
                "  - name: primary",
                f"    url: {subscription_url}",
                "    enabled: true",
                "    headers:",
                "      User-Agent: Clash.Meta",
                "user_data_dir: state_data",
                "probe:",
                "  query: ppr",
                "  allow_network_probe: true",
                "xray:",
                "  binary_path: .runtime/xray/xray",
                "  runtime_dir: .runtime",
                "  local_socks_host: 127.0.0.1",
                "  local_socks_port: 19080",
                "route:",
                "  entries:",
                "    - name: Scholar",
                "      candidate_id: candidate-001",
                "      listen_host: 127.0.0.1",
                "      listen_port: 19080",
                "      enabled: true",
                "routing:",
                "  mode: dedicated_inbound",
                "  inbound_tags: [google-scholar-in]",
                "  fail_closed: true",
                "experimental:",
                f"  enable_hysteria2: {'true' if enable_hysteria2 else 'false'}",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _write_candidates(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "candidates": [
            _candidate_entry("candidate-001", "US relay", protocol="vless", supported=True),
            _candidate_entry("candidate-002", "JP relay", protocol="vless", supported=True),
            _candidate_entry("candidate-003", "SG relay", protocol="vless", supported=True),
            _candidate_entry("candidate-004", "HK relay", protocol="hysteria2", supported=False),
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_probe_summary(path: Path, *, with_hash: bool = True, candidates_path: Path | None = None) -> None:
    from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "records": [
            _probe_record("candidate-001", home_status=200, query_status=200, failure_markers=[], latency_ms=1225),
            _probe_record(
                "candidate-002",
                home_status=200,
                query_status=302,
                failure_markers=["google_sorry", "stage_query_blocked"],
                latency_ms=3514,
            ),
            _probe_record(
                "candidate-003",
                home_status=None,
                query_status=None,
                failure_markers=["transport_error", "stage_transport_failed"],
                latency_ms=None,
                error="transport failed",
            ),
        ],
    }
    if with_hash and candidates_path is not None:
        payload["source_candidates_hash"] = compute_artifact_hash(json.loads(candidates_path.read_text(encoding="utf-8")))
    elif candidates_path is not None:
        payload["source_candidates_hash"] = "deadbeefdeadbeef"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_passed_candidates(path: Path, candidate_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"passed_candidate_ids": candidate_ids}, ensure_ascii=False), encoding="utf-8")


def _write_full_passed_candidates(path: Path, *, with_hash: bool, candidates_path: Path) -> None:
    from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "candidates": [
            {
                "candidate_id": "candidate-001",
                "candidate": {
                    "source_name": "fixture-source",
                    "raw_name": "US relay",
                    "protocol": "vless",
                    "address": "198.51.100.10",
                    "port": 443,
                    "supported": True,
                },
                "probe": {
                    "candidate_id": "candidate-001",
                    "home_status": 200,
                    "query_status": 200,
                    "latency_ms": 1225,
                    "failure_markers": [],
                },
            }
        ],
    }
    payload["source_candidates_hash"] = (
        compute_artifact_hash(json.loads(candidates_path.read_text(encoding="utf-8"))) if with_hash else "deadbeefdeadbeef"
    )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_action_journal(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "created_at": "2026-06-04T00:00:00Z",
                "operation_key": "probe",
                "title": "Probe Candidates",
                "summary": "Probe Candidates completed successfully.",
                "redacted_stdout": "Candidate result: <REDACTED_URI>",
                "redacted_stderr": "uuid=<UUID> password=<REDACTED> server_name=<REDACTED>",
            },
            ensure_ascii=False,
        )
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _candidate_entry(candidate_id: str, label: str, *, protocol: str, supported: bool) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "candidate": {
            "source_name": "fixture-source",
            "raw_name": label,
            "protocol": protocol,
            "address": "198.51.100.10",
            "port": 443,
            "user_id": "00000000-0000-0000-0000-000000000000",
            "password": "PASSWORD_PLACEHOLDER",
            "host": "secret.example.invalid",
            "path": "/private",
            "server_name": "secret.example.invalid",
            "raw_uri": "vless://00000000-0000-0000-0000-000000000000@secret.example.invalid:443",
            "supported": supported,
        },
    }


def _probe_record(
    candidate_id: str,
    *,
    home_status: int | None,
    query_status: int | None,
    failure_markers: list[str],
    latency_ms: int | None,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "attempted": True,
        "passed": not failure_markers and error is None and query_status == 200,
        "skipped": False,
        "summary": {
            "result": {
                "candidate_id": candidate_id,
                "home_status": home_status,
                "query_status": query_status,
                "blocked": bool(failure_markers),
                "timeout": False,
                "error": error,
                "failure_markers": failure_markers,
                "latency_ms": latency_ms,
                "checked_at": "2026-06-04T00:00:00Z",
            }
        },
    }
