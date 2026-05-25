"""Tests for the sequential probe CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from scholar_outbound_manager import cli
from scholar_outbound_manager.probe.batch_probe import BatchProbeRecord
from scholar_outbound_manager.probe.batch_probe import BatchProbeSummary
from scholar_outbound_manager.probe.candidate_probe import CandidateProbeSummary
from scholar_outbound_manager.models import ProbeResult


def test_probe_returns_zero_when_passed_candidates_exist(tmp_path, capsys, monkeypatch) -> None:
    """Return success when at least one candidate passes probing."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    monkeypatch.setattr(cli, "probe_candidates_sequential", lambda candidates, xray_config, options: _make_batch_summary(passed_count=1))
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))

    exit_code = cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "passed_count: 1" in captured.out


def test_probe_returns_two_when_no_candidates_pass(tmp_path, capsys, monkeypatch) -> None:
    """Return status 2 when probing completes without passed candidates."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    monkeypatch.setattr(cli, "probe_candidates_sequential", lambda candidates, xray_config, options: _make_batch_summary(passed_count=0, failed_count=1))
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))

    exit_code = cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "passed_count: 0" in captured.out


def test_probe_prints_counts_and_paths(tmp_path, capsys, monkeypatch) -> None:
    """Print summary counts and output paths."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    monkeypatch.setattr(cli, "probe_candidates_sequential", lambda candidates, xray_config, options: _make_batch_summary())
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))

    exit_code = cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "total_count: 1" in captured.out
    assert "attempted_count: 1" in captured.out
    assert "skipped_count: 0" in captured.out
    assert "failed_count: 0" in captured.out
    assert f"summary_path: {tmp_path / 'probe_summary.json'}" in captured.out
    assert f"passed_candidates_path: {tmp_path / 'passed_candidates.json'}" in captured.out


def test_probe_uses_config_default_max_passed(tmp_path, monkeypatch) -> None:
    """Use config.generation.max_passed_nodes when max-passed is omitted."""
    config_path = _write_config(tmp_path, max_passed_nodes=3)
    candidates_path = _write_candidates(tmp_path)
    observed = {}

    def fake_probe(candidates, xray_config, options):
        observed["options"] = options
        return _make_batch_summary()

    monkeypatch.setattr(cli, "probe_candidates_sequential", fake_probe)
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))

    assert cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path)]) == 0
    assert observed["options"].max_passed == 3


def test_probe_allows_cli_max_passed_override(tmp_path, monkeypatch) -> None:
    """Allow CLI max-passed to override config defaults."""
    config_path = _write_config(tmp_path, max_passed_nodes=3)
    candidates_path = _write_candidates(tmp_path)
    observed = {}

    def fake_probe(candidates, xray_config, options):
        observed["options"] = options
        return _make_batch_summary()

    monkeypatch.setattr(cli, "probe_candidates_sequential", fake_probe)
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))

    assert cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--max-passed", "1"]) == 0
    assert observed["options"].max_passed == 1


def test_probe_passes_max_candidates(tmp_path, monkeypatch) -> None:
    """Pass max-candidates through to BatchProbeOptions."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    observed = {}

    def fake_probe(candidates, xray_config, options):
        observed["options"] = options
        return _make_batch_summary()

    monkeypatch.setattr(cli, "probe_candidates_sequential", fake_probe)
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))

    cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--max-candidates", "2"])

    assert observed["options"].max_candidates == 2


def test_probe_passes_include_unsupported(tmp_path, monkeypatch) -> None:
    """Pass include-unsupported through to BatchProbeOptions."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    observed = {}

    def fake_probe(candidates, xray_config, options):
        observed["options"] = options
        return _make_batch_summary()

    monkeypatch.setattr(cli, "probe_candidates_sequential", fake_probe)
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))
    cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--include-unsupported"])

    assert observed["options"].include_unsupported is True


def test_probe_disables_stop_after_max_passed(tmp_path, monkeypatch) -> None:
    """Honor --no-stop-after-max-passed."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    observed = {}

    def fake_probe(candidates, xray_config, options):
        observed["options"] = options
        return _make_batch_summary()

    monkeypatch.setattr(cli, "probe_candidates_sequential", fake_probe)
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))
    cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--no-stop-after-max-passed"])

    assert observed["options"].stop_after_max_passed is False


def test_probe_passes_query_to_candidate_options(tmp_path, monkeypatch) -> None:
    """Pass custom query text through to CandidateProbeOptions."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    observed = {}

    def fake_probe(candidates, xray_config, options):
        observed["options"] = options
        return _make_batch_summary()

    monkeypatch.setattr(cli, "probe_candidates_sequential", fake_probe)
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))
    cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--query", "deep learning"])

    assert observed["options"].candidate_options.query == "deep learning"


def test_probe_can_skip_query(tmp_path, monkeypatch) -> None:
    """Pass skip-query through to CandidateProbeOptions."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    observed = {}

    def fake_probe(candidates, xray_config, options):
        observed["options"] = options
        return _make_batch_summary()

    monkeypatch.setattr(cli, "probe_candidates_sequential", fake_probe)
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))
    cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--skip-query"])

    assert observed["options"].candidate_options.probe_query is False


def test_probe_passes_startup_timeout(tmp_path, monkeypatch) -> None:
    """Pass startup-timeout through to CandidateProbeOptions."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    observed = {}

    def fake_probe(candidates, xray_config, options):
        observed["options"] = options
        return _make_batch_summary()

    monkeypatch.setattr(cli, "probe_candidates_sequential", fake_probe)
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))
    cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--startup-timeout", "7"])

    assert observed["options"].candidate_options.startup_timeout_seconds == 7.0


def test_probe_can_override_request_timeout(tmp_path, monkeypatch) -> None:
    """Allow request-timeout to override config.probe.timeout_seconds."""
    config_path = _write_config(tmp_path, probe_timeout=5)
    candidates_path = _write_candidates(tmp_path)
    observed = {}

    def fake_probe(candidates, xray_config, options):
        observed["options"] = options
        return _make_batch_summary()

    monkeypatch.setattr(cli, "probe_candidates_sequential", fake_probe)
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))
    cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--request-timeout", "11"])

    assert observed["options"].candidate_options.request_timeout_seconds == 11.0


def test_probe_passes_xray_test_timeout(tmp_path, monkeypatch) -> None:
    """Pass xray-test-timeout through to CandidateProbeOptions."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    observed = {}

    def fake_probe(candidates, xray_config, options):
        observed["options"] = options
        return _make_batch_summary()

    monkeypatch.setattr(cli, "probe_candidates_sequential", fake_probe)
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))
    cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--xray-test-timeout", "3"])

    assert observed["options"].candidate_options.xray_test_timeout_seconds == 3.0


def test_probe_passes_runtime_config_name(tmp_path, monkeypatch) -> None:
    """Pass runtime-config-name through to CandidateProbeOptions."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    observed = {}

    def fake_probe(candidates, xray_config, options):
        observed["options"] = options
        return _make_batch_summary()

    monkeypatch.setattr(cli, "probe_candidates_sequential", fake_probe)
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))
    cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--runtime-config-name", "probe-runtime.json"])

    assert observed["options"].candidate_options.runtime_config_name == "probe-runtime.json"


def test_probe_requires_candidates_argument(capsys) -> None:
    """Return an argparse error when candidates are omitted."""
    exit_code = cli.main(["probe", "--config", "config.yaml"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "--candidates" in captured.err


def test_probe_returns_one_when_config_is_missing(tmp_path, capsys) -> None:
    """Return 1 when config loading fails."""
    candidates_path = _write_candidates(tmp_path)
    exit_code = cli.main(["probe", "--config", str(tmp_path / "missing.yaml"), "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.err


def test_probe_returns_one_when_candidates_file_is_missing(tmp_path, capsys) -> None:
    """Return 1 when candidate loading fails."""
    config_path = _write_config(tmp_path)
    exit_code = cli.main(["probe", "--config", str(config_path), "--candidates", str(tmp_path / "missing.json")])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.err


def test_probe_rejects_non_positive_max_candidates(tmp_path, capsys) -> None:
    """Reject non-positive max-candidates."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    exit_code = cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--max-candidates", "0"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "max-candidates" in captured.err


def test_probe_rejects_non_positive_max_passed(tmp_path, capsys) -> None:
    """Reject non-positive max-passed."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    exit_code = cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--max-passed", "0"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "max-passed" in captured.err


def test_probe_rejects_non_positive_startup_timeout(tmp_path, capsys) -> None:
    """Reject non-positive startup-timeout."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    exit_code = cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--startup-timeout", "0"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "startup-timeout" in captured.err


def test_probe_rejects_non_positive_request_timeout(tmp_path, capsys) -> None:
    """Reject non-positive request-timeout."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    exit_code = cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--request-timeout", "0"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "request-timeout" in captured.err


def test_probe_rejects_non_positive_xray_test_timeout(tmp_path, capsys) -> None:
    """Reject non-positive xray-test-timeout."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    exit_code = cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--xray-test-timeout", "0"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "xray-test-timeout" in captured.err


def test_probe_rejects_runtime_config_name_with_path_separator(tmp_path, capsys) -> None:
    """Reject runtime-config-name values with path separators."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    exit_code = cli.main(
        ["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--runtime-config-name", "nested/runtime.json"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "runtime-config-name" in captured.err


def test_probe_rejects_identical_output_paths(tmp_path, capsys) -> None:
    """Reject probe artifact paths that point to the same file."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    shared_path = tmp_path / "shared.json"
    exit_code = cli.main(
        [
            "probe",
            "--config",
            str(config_path),
            "--candidates",
            str(candidates_path),
            "--summary-output",
            str(shared_path),
            "--passed-candidates-output",
            str(shared_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "must be different paths" in captured.err


def test_probe_returns_one_when_artifact_write_fails(tmp_path, capsys, monkeypatch) -> None:
    """Return 1 when artifact writing fails."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    monkeypatch.setattr(cli, "probe_candidates_sequential", lambda candidates, xray_config, options: _make_batch_summary())
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: (_ for _ in ()).throw(OSError("disk full")))

    exit_code = cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "disk full" in captured.err


def test_probe_returns_one_when_batch_probe_raises_value_error(tmp_path, capsys, monkeypatch) -> None:
    """Return 1 when sequential probing raises a validation error."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    monkeypatch.setattr(cli, "probe_candidates_sequential", lambda candidates, xray_config, options: (_ for _ in ()).throw(ValueError("bad probe options")))

    exit_code = cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "bad probe options" in captured.err


def test_probe_output_excludes_sensitive_values(tmp_path, capsys, monkeypatch) -> None:
    """Keep CLI output free of raw credentials and URIs."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    monkeypatch.setattr(cli, "probe_candidates_sequential", lambda candidates, xray_config, options: _make_batch_summary())
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))

    exit_code = cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    rendered = captured.out + captured.err
    assert "vless://" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered


def test_fetch_and_inspect_remain_unimplemented(capsys) -> None:
    """Keep unrelated subcommands in the placeholder state."""
    for command_name in ("fetch", "inspect"):
        exit_code = cli.main([command_name])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "not implemented in Phase 0.5" in captured.out


def test_generate_and_run_remain_available(tmp_path, capsys) -> None:
    """Keep generate and run behavior available after wiring probe."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)

    generate_exit_code = cli.main(["generate", "--config", str(config_path), "--candidates", str(candidates_path)])
    generate_captured = capsys.readouterr()
    run_exit_code = cli.main(["run", "--config", str(config_path), "--candidates", str(candidates_path)])
    run_captured = capsys.readouterr()

    assert generate_exit_code == 0
    assert "Generated Scholar outbound artifacts." in generate_captured.out
    assert run_exit_code == 0
    assert "Prepared Scholar runtime config." in run_captured.out


def _make_batch_summary(
    *,
    passed_count: int = 1,
    failed_count: int = 0,
    attempted_count: int = 1,
    skipped_count: int = 0,
    total_count: int = 1,
) -> BatchProbeSummary:
    """Construct one BatchProbeSummary for CLI tests."""
    record = BatchProbeRecord(
        index=0,
        candidate_id="candidate-001",
        candidate_name="node-a",
        attempted=True,
        passed=passed_count > 0,
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
    return BatchProbeSummary(
        total_count=total_count,
        attempted_count=attempted_count,
        skipped_count=skipped_count,
        passed_count=passed_count,
        failed_count=failed_count,
        records=[record],
        passed_indices=[0] if passed_count > 0 else [],
        passed_candidate_ids=["candidate-001"] if passed_count > 0 else [],
    )


def _artifact_result(tmp_path: Path) -> dict[str, object]:
    """Construct one artifact write result for CLI tests."""
    return {
        "summary_path": str(tmp_path / "probe_summary.json"),
        "passed_candidates_path": str(tmp_path / "passed_candidates.json"),
        "passed_count": 1,
        "attempted_count": 1,
        "skipped_count": 0,
        "failed_count": 0,
    }


def _write_config(tmp_path: Path, max_passed_nodes: int = 2, probe_timeout: int = 5) -> Path:
    """Write one placeholder configuration file for probe CLI tests."""
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
                f"  timeout_seconds: {probe_timeout}",
                "  concurrency: 1",
                "  cache_ttl_hours: 24",
                "  failure_backoff_hours: 24",
                "  allow_network_probe: false",
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
                f"  max_passed_nodes: {max_passed_nodes}",
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


def _write_candidates(tmp_path: Path) -> Path:
    """Write one placeholder candidate file for probe CLI tests."""
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
