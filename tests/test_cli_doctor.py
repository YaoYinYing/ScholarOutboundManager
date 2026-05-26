"""Tests for the doctor CLI command."""

from __future__ import annotations

import json

from scholar_outbound_manager import cli


def test_doctor_with_valid_config_returns_zero_and_prints_report(tmp_path, capsys, monkeypatch) -> None:
    """Return success and print one doctor report for valid local config."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text(_gitignore_text(), encoding="utf-8")
    config_path = _write_config(tmp_path)

    exit_code = cli.main(["doctor", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "ScholarOutboundManager doctor report" in captured.out
    assert "ok:" in captured.out
    assert "warn:" in captured.out
    assert "error:" in captured.out


def test_doctor_with_missing_config_returns_one(tmp_path, capsys) -> None:
    """Return failure when config cannot be loaded."""
    exit_code = cli.main(["doctor", "--config", str(tmp_path / "missing.yaml")])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "config_load" in captured.out


def test_doctor_with_valid_candidates_returns_zero(tmp_path, capsys, monkeypatch) -> None:
    """Return success when config and candidates are locally valid."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text(_gitignore_text(), encoding="utf-8")
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        ["doctor", "--config", str(config_path), "--candidates", str(candidates_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "candidate_counts" in captured.out


def test_doctor_require_network_probe_ready_returns_one_when_disabled(tmp_path, capsys, monkeypatch) -> None:
    """Return failure when live probing readiness is required but disabled."""
    monkeypatch.chdir(tmp_path)
    config_path = _write_config(tmp_path, allow_network_probe=False)

    exit_code = cli.main(
        ["doctor", "--config", str(config_path), "--require-network-probe-ready"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "[ERROR] probe_safety_gate:" in captured.out


def test_doctor_output_excludes_sensitive_values(tmp_path, capsys, monkeypatch) -> None:
    """Keep doctor output free of raw credentials and URIs."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text(_gitignore_text(), encoding="utf-8")
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        ["doctor", "--config", str(config_path), "--candidates", str(candidates_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    rendered = captured.out + captured.err
    assert "vless://" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered


def test_probe_generate_run_and_inspect_remain_available(tmp_path, capsys, monkeypatch) -> None:
    """Keep existing wired CLI commands available after adding doctor."""
    config_path = _write_config(tmp_path, allow_network_probe=True)
    candidates_path = _write_candidates(tmp_path)
    monkeypatch.setattr(cli, "probe_candidates_sequential", lambda candidates, xray_config, options: _make_batch_summary())
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))

    probe_exit_code = cli.main(
        [
            "probe",
            "--config",
            str(config_path),
            "--candidates",
            str(candidates_path),
            "--allow-network-probe",
        ]
    )
    capsys.readouterr()
    generate_exit_code = cli.main(["generate", "--config", str(config_path), "--candidates", str(candidates_path)])
    capsys.readouterr()
    run_exit_code = cli.main(["run", "--config", str(config_path), "--candidates", str(candidates_path)])
    capsys.readouterr()
    inspect_path = tmp_path / "manifest.json"
    inspect_path.write_text(json.dumps(_make_manifest_payload()), encoding="utf-8")
    inspect_exit_code = cli.main(["inspect", "--manifest", str(inspect_path)])
    capsys.readouterr()

    assert probe_exit_code == 0
    assert generate_exit_code == 0
    assert run_exit_code == 0
    assert inspect_exit_code == 0


def test_fetch_remains_unimplemented(capsys) -> None:
    """Keep fetch in the placeholder state."""
    exit_code = cli.main(["fetch"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "not implemented in Phase 0.5" in captured.out


def _write_config(tmp_path, allow_network_probe: bool = False):
    """Write one placeholder config for doctor CLI tests."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "subscriptions: []",
                "filters:",
                "  include_keywords: []",
                "  exclude_keywords: []",
                "  deprioritize_keywords: []",
                "probe:",
                "  timeout_seconds: 5",
                "  concurrency: 1",
                "  cache_ttl_hours: 24",
                "  failure_backoff_hours: 24",
                f"  allow_network_probe: {'true' if allow_network_probe else 'false'}",
                "xray:",
                f"  binary_path: {tmp_path / 'missing-xray'}",
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
                "  max_passed_nodes: 2",
                "  fallback_blackhole_tag: blocked-scholar",
                "  previous_output_max_age_hours: 24",
                "routing:",
                '  mode: "dedicated_inbound"',
                "  inbound_tags:",
                "    - scholar-in",
                "  fail_closed: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _write_candidates(tmp_path):
    """Write one placeholder candidate file for doctor CLI tests."""
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
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
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return candidates_path


def _make_batch_summary():
    """Construct one batch probe summary object for compatibility tests."""
    from scholar_outbound_manager.models import ProbeResult
    from scholar_outbound_manager.probe.batch_probe import BatchProbeRecord
    from scholar_outbound_manager.probe.batch_probe import BatchProbeSummary
    from scholar_outbound_manager.probe.candidate_probe import CandidateProbeSummary

    return BatchProbeSummary(
        total_count=1,
        attempted_count=1,
        skipped_count=0,
        passed_count=1,
        failed_count=0,
        records=[
            BatchProbeRecord(
                index=0,
                candidate_id="candidate-001",
                candidate_name="node-a",
                attempted=True,
                passed=True,
                skipped=False,
                skip_reason=None,
                summary=CandidateProbeSummary(
                    candidate_id="candidate-001",
                    runtime_config_path="/tmp/runtime.json",
                    local_socks_host="127.0.0.1",
                    local_socks_port=1081,
                    xray_started=True,
                    xray_test_passed=None,
                    startup_ready=True,
                    result=ProbeResult(
                        candidate_id="candidate-001",
                        home_status=200,
                        query_status=200,
                        blocked=False,
                        timeout=False,
                        error=None,
                        failure_markers=[],
                        latency_ms=10,
                        checked_at="2026-05-25T00:00:00Z",
                    ),
                ),
            )
        ],
        passed_indices=[0],
        passed_candidate_ids=["candidate-001"],
    )


def _artifact_result(tmp_path):
    """Construct one probe artifact write result for compatibility tests."""
    return {
        "summary_path": str(tmp_path / "probe_summary.json"),
        "passed_candidates_path": str(tmp_path / "passed_candidates.json"),
        "passed_count": 1,
        "attempted_count": 1,
        "skipped_count": 0,
        "failed_count": 0,
    }


def _make_manifest_payload() -> dict[str, object]:
    """Construct one generated manifest payload for inspect compatibility tests."""
    return {
        "schema_version": 1,
        "generated_at": "2026-05-25T00:00:00Z",
        "selected": [{"tag": "google-scholar-node-001", "candidate": {"raw_name": "node-a"}, "probe": None}],
        "rejected": [{"candidate": {"raw_name": "node-b"}, "reason": "Candidate was not selected."}],
    }


def _gitignore_text() -> str:
    """Return one minimal gitignore body for doctor CLI tests."""
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
