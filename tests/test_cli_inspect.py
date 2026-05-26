"""Tests for the safe inspect CLI command."""

from __future__ import annotations

import json

from scholar_outbound_manager import cli


def test_inspect_defaults_to_generated_manifest_in_cwd(tmp_path, monkeypatch, capsys) -> None:
    """Default to the generated manifest path when no target is provided."""
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    manifest_path = generated_dir / "google_scholar_manifest.json"
    manifest_path.write_text(json.dumps(_make_manifest_payload()), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["inspect"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Generated manifest:" in captured.out
    assert "path: generated/google_scholar_manifest.json" in captured.out


def test_inspect_can_render_manifest_summary(tmp_path, capsys) -> None:
    """Render one manifest inspection from an explicit path."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_make_manifest_payload()), encoding="utf-8")

    exit_code = cli.main(["inspect", "--manifest", str(manifest_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "selected_count: 1" in captured.out
    assert "google-scholar-node-001" in captured.out


def test_inspect_can_render_probe_summary(tmp_path, capsys) -> None:
    """Render one probe summary inspection from an explicit path."""
    summary_path = tmp_path / "probe_summary.json"
    summary_path.write_text(json.dumps(_make_probe_summary_payload()), encoding="utf-8")

    exit_code = cli.main(["inspect", "--probe-summary", str(summary_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Probe summary:" in captured.out
    assert "passed_count: 1" in captured.out


def test_inspect_can_render_sensitive_candidate_warning(tmp_path, capsys) -> None:
    """Render sensitive artifact metadata without printing credentials."""
    passed_candidates_path = tmp_path / "passed_candidates.json"
    passed_candidates_path.write_text(json.dumps(_make_sensitive_payload()), encoding="utf-8")

    exit_code = cli.main(["inspect", "--passed-candidates", str(passed_candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Sensitive passed candidates:" in captured.out
    assert "Warning: sensitive candidate credentials are not displayed." in captured.out


def test_inspect_outputs_sections_in_expected_order(tmp_path, capsys) -> None:
    """Render probe summary, manifest, and sensitive metadata in a stable order."""
    summary_path = tmp_path / "probe_summary.json"
    manifest_path = tmp_path / "manifest.json"
    passed_candidates_path = tmp_path / "passed_candidates.json"
    summary_path.write_text(json.dumps(_make_probe_summary_payload()), encoding="utf-8")
    manifest_path.write_text(json.dumps(_make_manifest_payload()), encoding="utf-8")
    passed_candidates_path.write_text(json.dumps(_make_sensitive_payload()), encoding="utf-8")

    exit_code = cli.main(
        [
            "inspect",
            "--probe-summary",
            str(summary_path),
            "--manifest",
            str(manifest_path),
            "--passed-candidates",
            str(passed_candidates_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    probe_index = captured.out.index("Probe summary:")
    manifest_index = captured.out.index("Generated manifest:")
    sensitive_index = captured.out.index("Sensitive passed candidates:")
    assert probe_index < manifest_index < sensitive_index
    assert "\n\nGenerated manifest:" in captured.out
    assert "\n\nSensitive passed candidates:" in captured.out


def test_inspect_returns_one_for_missing_file(tmp_path, capsys) -> None:
    """Return 1 when the target file does not exist."""
    exit_code = cli.main(["inspect", "--manifest", str(tmp_path / "missing.json")])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.err


def test_inspect_returns_one_for_invalid_json(tmp_path, capsys) -> None:
    """Return 1 when the target file contains invalid JSON."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{invalid", encoding="utf-8")

    exit_code = cli.main(["inspect", "--manifest", str(manifest_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.err


def test_inspect_output_excludes_sensitive_values(tmp_path, capsys) -> None:
    """Keep inspect output free of raw credentials and URIs."""
    summary_path = tmp_path / "probe_summary.json"
    manifest_path = tmp_path / "manifest.json"
    passed_candidates_path = tmp_path / "passed_candidates.json"
    summary_path.write_text(json.dumps(_make_probe_summary_payload()), encoding="utf-8")
    manifest_path.write_text(json.dumps(_make_manifest_payload()), encoding="utf-8")
    passed_candidates_path.write_text(json.dumps(_make_sensitive_payload()), encoding="utf-8")

    exit_code = cli.main(
        [
            "inspect",
            "--probe-summary",
            str(summary_path),
            "--manifest",
            str(manifest_path),
            "--passed-candidates",
            str(passed_candidates_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    rendered = captured.out + captured.err
    assert "vless://" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered


def test_fetch_remains_unimplemented(capsys) -> None:
    """Keep fetch in the placeholder state."""
    exit_code = cli.main(["fetch"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "not implemented in Phase 0.5" in captured.out


def test_probe_generate_and_run_remain_available(tmp_path, capsys, monkeypatch) -> None:
    """Keep existing wired subcommands available after adding inspect."""
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
    probe_captured = capsys.readouterr()
    generate_exit_code = cli.main(["generate", "--config", str(config_path), "--candidates", str(candidates_path)])
    generate_captured = capsys.readouterr()
    run_exit_code = cli.main(["run", "--config", str(config_path), "--candidates", str(candidates_path)])
    run_captured = capsys.readouterr()

    assert probe_exit_code == 0
    assert "Probed Scholar candidates." in probe_captured.out
    assert generate_exit_code == 0
    assert "Generated Scholar outbound artifacts." in generate_captured.out
    assert run_exit_code == 0
    assert "Prepared Scholar runtime config." in run_captured.out


def _make_probe_summary_payload() -> dict[str, object]:
    """Construct one redacted probe summary payload for CLI tests."""
    return {
        "schema_version": 1,
        "total_count": 1,
        "attempted_count": 1,
        "skipped_count": 0,
        "passed_count": 1,
        "failed_count": 0,
        "passed_indices": [0],
        "passed_candidate_ids": ["candidate-001-abc123"],
        "records": [
            {
                "index": 0,
                "candidate_id": "candidate-001-abc123",
                "candidate_name": "node-a",
                "attempted": True,
                "passed": True,
                "skipped": False,
                "skip_reason": None,
                "summary": {
                    "candidate_id": "candidate-001-abc123",
                    "runtime_config_path": "/tmp/runtime.json",
                    "local_socks_host": "127.0.0.1",
                    "local_socks_port": 1081,
                    "xray_started": True,
                    "xray_test_passed": True,
                    "startup_ready": True,
                    "result": {
                        "candidate_id": "candidate-001-abc123",
                        "home_status": 200,
                        "query_status": 200,
                        "blocked": False,
                        "timeout": False,
                        "error": None,
                        "failure_markers": [],
                        "latency_ms": 10,
                        "checked_at": "2026-05-25T00:00:00Z",
                    },
                },
            }
        ],
    }


def _make_manifest_payload() -> dict[str, object]:
    """Construct one generated manifest payload for CLI tests."""
    return {
        "schema_version": 1,
        "generated_at": "2026-05-25T00:00:00Z",
        "selected": [{"tag": "google-scholar-node-001", "candidate": {"raw_name": "node-a"}, "probe": None}],
        "rejected": [{"candidate": {"raw_name": "node-b"}, "reason": "Candidate was not selected."}],
    }


def _make_sensitive_payload() -> dict[str, object]:
    """Construct one sensitive passed-candidate payload for CLI tests."""
    return {
        "schema_version": 1,
        "sensitive": True,
        "description": "This file contains selected proxy credentials and must not be committed.",
        "passed_candidate_ids": ["candidate-001-abc123"],
        "candidates": [
            {
                "raw_name": "US Scholar IPv4",
                "address": "example.invalid",
                "port": 443,
                "user_id": "00000000-0000-0000-0000-000000000000",
                "public_key": "PUBLIC_KEY_PLACEHOLDER",
                "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
            }
        ],
    }


def _make_batch_summary():
    """Construct one batch probe summary object for CLI compatibility tests."""
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


def _artifact_result(tmp_path) -> dict[str, object]:
    """Construct one probe artifact write result for CLI compatibility tests."""
    return {
        "summary_path": str(tmp_path / "probe_summary.json"),
        "passed_candidates_path": str(tmp_path / "passed_candidates.json"),
        "passed_count": 1,
        "attempted_count": 1,
        "skipped_count": 0,
        "failed_count": 0,
    }


def _write_config(tmp_path, allow_network_probe: bool = False):
    """Write one placeholder config file for CLI compatibility tests."""
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
                "  binary_path: fake-xray",
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
                "  mode: dedicated_inbound",
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
    """Write one placeholder candidate file for CLI compatibility tests."""
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
