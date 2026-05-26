"""Tests for local-only doctor preflight checks."""

from __future__ import annotations

import json

from scholar_outbound_manager.doctor import build_doctor_report
from scholar_outbound_manager.doctor import format_doctor_report


def test_valid_config_without_candidates_returns_report_without_errors(tmp_path, monkeypatch, capsys) -> None:
    """Build a report with no errors for a valid local config."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text(_gitignore_text(), encoding="utf-8")
    config_path = _write_config(tmp_path)

    report = build_doctor_report(config_path)
    captured = capsys.readouterr()

    assert report.error_count == 0
    assert report.exit_code == 0
    assert report.ok_count > 0
    assert captured.out == ""
    assert captured.err == ""


def test_config_missing_produces_error_check(tmp_path, monkeypatch) -> None:
    """Report config loading errors without raising."""
    monkeypatch.chdir(tmp_path)
    report = build_doctor_report(tmp_path / "missing.yaml")

    assert report.exit_code == 1
    assert any(check.name == "config_load" and check.status == "error" for check in report.checks)


def test_allow_network_probe_false_warns_by_default(tmp_path, monkeypatch) -> None:
    """Warn when live probing is disabled by default."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path, allow_network_probe=False)

    report = build_doctor_report(config_path)

    assert _check_status(report, "probe_safety_gate") == "warn"


def test_allow_network_probe_false_errors_when_ready_is_required(tmp_path, monkeypatch) -> None:
    """Error when live probing readiness is explicitly required."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path, allow_network_probe=False)

    report = build_doctor_report(config_path, require_network_probe_ready=True)

    assert report.exit_code == 1
    assert _check_status(report, "probe_safety_gate") == "error"


def test_allow_network_probe_true_mentions_cli_flag(tmp_path, monkeypatch) -> None:
    """Report that CLI opt-in is still required when config enables live probing."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path, allow_network_probe=True)

    report = build_doctor_report(config_path)

    matching = [check for check in report.checks if check.name == "probe_safety_gate"]
    assert matching[0].status == "ok"
    assert "--allow-network-probe" in matching[0].message


def test_missing_xray_binary_path_produces_warn_not_error(tmp_path, monkeypatch) -> None:
    """Warn when the configured Xray path does not exist."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path, binary_path=str(tmp_path / "missing-xray"))

    report = build_doctor_report(config_path)

    assert _check_status(report, "xray_binary_path") == "warn"
    assert report.exit_code == 0


def test_invalid_routing_mode_produces_error(tmp_path, monkeypatch) -> None:
    """Error on unsupported routing mode."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path, routing_mode="domain_match")

    report = build_doctor_report(config_path)

    assert _check_status(report, "routing_mode") == "error"


def test_empty_inbound_tags_produce_error(tmp_path, monkeypatch) -> None:
    """Error when no inbound tags are configured."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path, inbound_tags=[])

    report = build_doctor_report(config_path)

    assert _check_status(report, "routing_inbound_tags") == "error"


def test_fail_closed_false_produces_warn(tmp_path, monkeypatch) -> None:
    """Warn when routing is not fail-closed."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path, fail_closed=False)

    report = build_doctor_report(config_path)

    assert _check_status(report, "routing_fail_closed") == "warn"


def test_invalid_generation_max_passed_nodes_produces_error(tmp_path, monkeypatch) -> None:
    """Error when generation.max_passed_nodes is not positive."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path, max_passed_nodes=0)

    report = build_doctor_report(config_path)

    assert _check_status(report, "generation_max_passed_nodes") == "error"


def test_valid_candidates_produce_candidate_counts(tmp_path, monkeypatch) -> None:
    """Report candidate counts after loading and filtering."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)

    report = build_doctor_report(config_path, candidates_path=candidates_path)

    candidate_count_checks = [check for check in report.checks if check.name == "candidate_counts"]
    assert candidate_count_checks
    assert "loaded=1" in candidate_count_checks[0].message
    assert "filtered=1" in candidate_count_checks[0].message


def test_missing_candidates_file_produces_error(tmp_path, monkeypatch) -> None:
    """Report candidate loading errors."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)

    report = build_doctor_report(config_path, candidates_path=tmp_path / "missing.json")

    assert _check_status(report, "candidate_load") == "error"


def test_empty_candidates_produce_error(tmp_path, monkeypatch) -> None:
    """Error when no candidates are loaded."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path, raw_payload={"candidates": []})

    report = build_doctor_report(config_path, candidates_path=candidates_path)

    assert _check_status(report, "candidate_counts") == "error"


def test_filters_reducing_all_candidates_to_zero_produce_error(tmp_path, monkeypatch) -> None:
    """Error when configured filters remove every candidate."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path, include_keywords=["missing"])
    candidates_path = _write_candidates(tmp_path)

    report = build_doctor_report(config_path, candidates_path=candidates_path)

    assert _check_status(report, "candidate_counts") == "error"


def test_unsupported_only_candidates_warn_by_default(tmp_path, monkeypatch) -> None:
    """Warn when filtered candidates are all unsupported."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(
        tmp_path,
        raw_payload={"candidates": [_candidate_mapping(supported=False, unsupported_reason="Unsupported transport.")]},
    )

    report = build_doctor_report(config_path, candidates_path=candidates_path)

    assert _check_status(report, "candidate_counts") == "warn"


def test_unsupported_only_candidates_error_when_passed_candidates_are_required(tmp_path, monkeypatch) -> None:
    """Error when passed-candidate readiness is required but none are usable."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(
        tmp_path,
        raw_payload={"candidates": [_candidate_mapping(supported=False, unsupported_reason="Unsupported transport.")]},
    )

    report = build_doctor_report(
        config_path,
        candidates_path=candidates_path,
        require_passed_candidates=True,
    )

    assert _check_status(report, "candidate_counts") == "error"


def test_passed_candidates_artifact_with_probe_evidence_reports_evidence_count(tmp_path, monkeypatch) -> None:
    """Count probe evidence inside passed-candidates artifacts."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path, raw_payload=_passed_candidates_payload(with_probe=True))

    report = build_doctor_report(config_path, candidates_path=candidates_path)

    assert _check_status(report, "passed_candidates_shape") == "ok"
    candidate_counts = [check for check in report.checks if check.name == "candidate_counts"][0]
    assert "with_probe_evidence=1" in candidate_counts.message


def test_old_style_plain_candidates_artifact_warns_about_missing_probe_evidence(tmp_path, monkeypatch) -> None:
    """Warn when the artifact has no embedded probe evidence."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path, raw_payload=[_candidate_mapping()])

    report = build_doctor_report(
        config_path,
        candidates_path=candidates_path,
        require_passed_candidates=True,
    )

    assert _check_status(report, "passed_candidates_shape") == "warn"
    assert _check_status(report, "passed_candidates_probe_evidence") == "warn"


def test_format_doctor_report_includes_status_sections_and_excludes_sensitive_values(tmp_path, monkeypatch, capsys) -> None:
    """Format doctor output without exposing secrets."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text(_gitignore_text(), encoding="utf-8")
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path, raw_payload=_passed_candidates_payload(with_probe=True))

    report = build_doctor_report(config_path, candidates_path=candidates_path)
    rendered = format_doctor_report(report)
    captured = capsys.readouterr()

    assert "ScholarOutboundManager doctor report" in rendered
    assert "ok:" in rendered
    assert "warn:" in rendered
    assert "error:" in rendered
    assert "[OK]" in rendered
    assert "[WARN]" in rendered or "[ERROR]" in rendered
    assert "vless://" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered
    assert captured.out == ""
    assert captured.err == ""


def _check_status(report, name: str) -> str:
    """Return the first matching check status."""
    return [check.status for check in report.checks if check.name == name][0]


def _write_config(
    tmp_path,
    *,
    allow_network_probe: bool = False,
    binary_path: str | None = None,
    routing_mode: str = "dedicated_inbound",
    inbound_tags: list[str] | None = None,
    fail_closed: bool = True,
    max_passed_nodes: int = 2,
    include_keywords: list[str] | None = None,
) -> Path:
    """Write one doctor test config file."""
    from pathlib import Path

    include_keywords = include_keywords or []
    inbound_tags = ["scholar-in"] if inbound_tags is None else inbound_tags
    config_path = tmp_path / "config.yaml"
    actual_binary_path = str(tmp_path / "missing-xray") if binary_path is None else binary_path
    inbound_tag_lines = ["  inbound_tags: []"] if not inbound_tags else [
        "  inbound_tags:",
        *(f"    - {item}" for item in inbound_tags),
    ]
    config_path.write_text(
        "\n".join(
            [
                "subscriptions: []",
                "filters:",
                f"  include_keywords: [{', '.join(_quote_yaml(item) for item in include_keywords)}]",
                "  exclude_keywords: []",
                "  deprioritize_keywords: []",
                "probe:",
                "  timeout_seconds: 5",
                "  concurrency: 1",
                "  cache_ttl_hours: 24",
                "  failure_backoff_hours: 24",
                f"  allow_network_probe: {'true' if allow_network_probe else 'false'}",
                "xray:",
                f"  binary_path: {_quote_yaml(actual_binary_path)}",
                f"  runtime_dir: {tmp_path / 'runtime'}",
                "  local_socks_host: 127.0.0.1",
                "  local_socks_port: 1081",
                "output:",
                f"  outbounds_path: {tmp_path / 'outbounds.json'}",
                f"  routes_path: {tmp_path / 'routes.json'}",
                f"  manifest_path: {tmp_path / 'manifest.json'}",
                f"  history_dir: {tmp_path / 'history'}",
                "generation:",
                "  tag_prefix: google-scholar-node-",
                f"  max_passed_nodes: {max_passed_nodes}",
                "  fallback_blackhole_tag: blocked-scholar",
                "  previous_output_max_age_hours: 24",
                "routing:",
                f"  mode: {_quote_yaml(routing_mode)}",
                *inbound_tag_lines,
                f"  fail_closed: {'true' if fail_closed else 'false'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _write_candidates(tmp_path, *, raw_payload: object | None = None):
    """Write one candidate file for doctor tests."""
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(
        json.dumps(raw_payload if raw_payload is not None else {"candidates": [_candidate_mapping()]}),
        encoding="utf-8",
    )
    return candidate_path


def _candidate_mapping(**overrides: object) -> dict[str, object]:
    """Build one placeholder candidate mapping."""
    candidate = {
        "source_name": "fixture-source",
        "raw_name": "US Scholar IPv4",
        "protocol": "vless",
        "address": "example.invalid",
        "port": 443,
        "user_id": "00000000-0000-0000-0000-000000000000",
        "encryption": "none",
        "flow": "xtls-rprx-vision",
        "network": "tcp",
        "security": "reality",
        "server_name": "www.cloudflare.com",
        "fingerprint": "chrome",
        "public_key": "PUBLIC_KEY_PLACEHOLDER",
        "short_id": "SHORT_ID_PLACEHOLDER",
        "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
        "supported": True,
        "unsupported_reason": None,
    }
    candidate.update(overrides)
    return candidate


def _passed_candidates_payload(*, with_probe: bool) -> dict[str, object]:
    """Build one sensitive passed-candidates payload."""
    return {
        "schema_version": 1,
        "sensitive": True,
        "passed_candidate_ids": ["candidate-001"],
        "candidates": [
            {
                "candidate": _candidate_mapping(),
                "probe": (
                    {
                        "candidate_id": "candidate-001",
                        "home_status": 200,
                        "query_status": 200,
                        "blocked": False,
                        "timeout": False,
                        "error": None,
                        "failure_markers": [],
                        "latency_ms": 10,
                        "checked_at": "2026-05-25T00:00:00Z",
                    }
                    if with_probe
                    else None
                ),
            }
        ],
    }


def _quote_yaml(value: str) -> str:
    """Quote a YAML scalar for compact inline config output."""
    return f'"{value}"'


def _gitignore_text() -> str:
    """Return one minimal gitignore body for doctor tests."""
    return "\n".join(
        [
            "config.yaml",
            "candidates.json",
            "passed_candidates.json",
            "probe_summary.json",
            "generated/",
            "state_data/",
            ".runtime/",
            ".env",
            "",
        ]
    )
