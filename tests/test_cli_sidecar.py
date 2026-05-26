"""Tests for the sidecar CLI commands."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager import cli


def test_sidecar_prepare_outputs_non_secret_summary(tmp_path, capsys, monkeypatch) -> None:
    """Prepare a sidecar runtime and print only non-secret fields."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        [
            "sidecar",
            "prepare",
            "--config",
            str(config_path),
            "--candidates",
            str(candidates_path),
            "--candidate-index",
            "0",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Prepared Scholar sidecar runtime." in captured.out
    assert "candidate_protocol: vless" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_sidecar_start_can_be_monkeypatched_to_success(tmp_path, capsys, monkeypatch) -> None:
    """Allow sidecar start through a fake sidecar starter."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)

    def fake_start_sidecar_runtime(xray_config, summary, *, test_config_timeout_seconds=10.0):
        del xray_config, test_config_timeout_seconds
        from scholar_outbound_manager.sidecar import SidecarRuntimeSummary

        return SidecarRuntimeSummary(
            runtime_config_path=summary.runtime_config_path,
            pid_file_path=summary.pid_file_path,
            metadata_file_path=summary.metadata_file_path,
            listen_host=summary.listen_host,
            listen_port=summary.listen_port,
            outbound_tag=summary.outbound_tag,
            inbound_tag=summary.inbound_tag,
            candidate_id=summary.candidate_id,
            candidate_protocol=summary.candidate_protocol,
            started=True,
            config_test_passed=True,
            error=None,
        )

    monkeypatch.setattr(cli, "start_sidecar_runtime", fake_start_sidecar_runtime)

    exit_code = cli.main(
        [
            "sidecar",
            "start",
            "--config",
            str(config_path),
            "--candidates",
            str(candidates_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "started: true" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_sidecar_status_reports_alive_false_for_missing_pid(tmp_path, capsys) -> None:
    """Report a missing sidecar pid file without failing the command."""
    config_path = _write_config(tmp_path)

    exit_code = cli.main(["sidecar", "status", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "alive: false" in captured.out


def test_sidecar_stop_does_not_kill_non_managed_process(tmp_path, capsys, monkeypatch) -> None:
    """Keep stop scoped to sidecar-managed pid ownership."""
    config_path = _write_config(tmp_path)
    called: dict[str, object] = {}

    def fake_stop(pid_file_path, *, expected_binary_path, expected_config_path=None):
        called["pid_file_path"] = str(pid_file_path)
        called["expected_binary_path"] = str(expected_binary_path)
        called["expected_config_path"] = None if expected_config_path is None else str(expected_config_path)
        return False

    monkeypatch.setattr(cli, "stop_sidecar_runtime", fake_stop)

    exit_code = cli.main(["sidecar", "stop", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "terminated: false" in captured.out
    assert str(tmp_path / "runtime" / "scholar_sidecar.pid.json") == called["pid_file_path"]


def test_sidecar_snippet_outputs_socks_outbound_json(tmp_path, capsys) -> None:
    """Print one SOCKS outbound snippet for production integration."""
    exit_code = cli.main(
        [
            "sidecar",
            "snippet",
            "--listen-host",
            "127.0.0.1",
            "--listen-port",
            "19080",
            "--tag",
            "scholar-sidecar-socks-out",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"protocol": "socks"' in captured.out
    assert '"port": 19080' in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_existing_command_surface_remains_available_with_sidecar(tmp_path, capsys, monkeypatch) -> None:
    """Keep the pre-existing CLI commands available after sidecar addition."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)
    monkeypatch.setattr(cli, "probe_candidates_sequential", lambda candidates, xray_config, options: _batch_summary())
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))

    assert cli.main(["environment"]) == 0
    capsys.readouterr()
    assert cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--allow-network-probe"]) == 0
    capsys.readouterr()
    assert cli.main(["generate", "--config", str(config_path), "--candidates", str(candidates_path)]) == 0
    capsys.readouterr()
    assert cli.main(["run", "--config", str(config_path), "--candidates", str(candidates_path)]) == 0
    capsys.readouterr()
    assert cli.main(["xray", "inspect", "--path", str(tmp_path / "missing-xray")]) == 1
    capsys.readouterr()


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "subscriptions:",
                '  - name: "fixture-source"',
                '    url: "https://example.invalid/subscription"',
                '    format: "auto"',
                "    enabled: false",
                "    headers: {}",
                "filters:",
                "  include_keywords: []",
                "  exclude_keywords: []",
                "  deprioritize_keywords: []",
                "probe:",
                "  timeout_seconds: 5",
                "  concurrency: 1",
                "  cache_ttl_hours: 24",
                "  failure_backoff_hours: 24",
                "  allow_network_probe: true",
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
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(
        '{"candidates":[{"source_name":"fixture","raw_name":"node","protocol":"vless","address":"example.invalid","port":443,"user_id":"00000000-0000-0000-0000-000000000000","security":"reality","server_name":"www.cloudflare.com","public_key":"PUBLIC_KEY_PLACEHOLDER","supported":true,"raw_uri":"vless://00000000-0000-0000-0000-000000000000@example.invalid:443"}]}',
        encoding="utf-8",
    )
    return candidates_path


def _assert_no_secrets(rendered: str) -> None:
    lowered = rendered.lower()
    assert "raw_uri" not in lowered
    assert "00000000-0000-0000-0000-000000000000" not in lowered
    assert "public_key_placeholder" not in lowered
    assert "password" not in lowered
    assert "token" not in lowered
    assert "secret" not in lowered


def _artifact_result(tmp_path: Path) -> dict[str, object]:
    return {
        "summary_path": str(tmp_path / "probe_summary.json"),
        "passed_candidates_path": str(tmp_path / "passed_candidates.json"),
        "passed_count": 1,
        "attempted_count": 1,
        "skipped_count": 0,
        "failed_count": 0,
    }


def _batch_summary():
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
