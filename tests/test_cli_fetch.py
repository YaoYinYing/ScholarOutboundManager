"""Tests for the subscription fetch CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from scholar_outbound_manager import cli
from scholar_outbound_manager.fetcher import FetchSummary
from scholar_outbound_manager.fetcher import FetchedSubscription


def test_fetch_requires_allow_network_fetch_flag(tmp_path, capsys, monkeypatch) -> None:
    """Refuse to fetch when the CLI opt-in flag is missing."""
    config_path = _write_config(tmp_path)
    called = {"fetch": False}

    def fake_fetch(*args, **kwargs):
        called["fetch"] = True
        raise AssertionError("fetch should not run without opt-in")

    monkeypatch.setattr(cli, "fetch_enabled_subscriptions", fake_fetch)

    exit_code = cli.main(["fetch", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "--allow-network-fetch" in captured.err
    assert called["fetch"] is False


def test_fetch_succeeds_and_writes_output(tmp_path, capsys, monkeypatch) -> None:
    """Fetch, parse, and write a sensitive candidate artifact."""
    config_path = _write_config(tmp_path)
    output_path = tmp_path / "candidates.json"
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes: (
            [_fetched_subscription()],
            FetchSummary(
                source_count=1,
                fetched_count=1,
                disabled_count=0,
                failed_count=0,
                total_bytes=120,
                errors=[],
            ),
        ),
    )

    exit_code = cli.main(
        [
            "fetch",
            "--config",
            str(config_path),
            "--output",
            str(output_path),
            "--allow-network-fetch",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["sensitive"] is True
    assert len(payload["candidates"]) == 1
    assert "output_path:" in captured.out


def test_fetch_prints_expected_counts(tmp_path, capsys, monkeypatch) -> None:
    """Print summary counts without leaking secrets."""
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes: (
            [_fetched_subscription(), _unsupported_fetched_subscription()],
            FetchSummary(
                source_count=2,
                fetched_count=2,
                disabled_count=0,
                failed_count=0,
                total_bytes=240,
                errors=[],
            ),
        ),
    )

    exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(tmp_path / "candidates.json")]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "source_count: 2" in captured.out
    assert "fetched_count: 2" in captured.out
    assert "parsed_count: 2" in captured.out
    assert "supported_count: 1" in captured.out
    assert "unsupported_count: 1" in captured.out


def test_fetch_output_does_not_include_subscription_url(tmp_path, capsys, monkeypatch) -> None:
    """Keep the subscription URL out of CLI output."""
    config_path = _write_config(tmp_path, subscription_url="https://example.invalid/token-secret")
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes: (
            [_fetched_subscription()],
            FetchSummary(
                source_count=1,
                fetched_count=1,
                disabled_count=0,
                failed_count=0,
                total_bytes=120,
                errors=[],
            ),
        ),
    )

    exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(tmp_path / "candidates.json")]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    rendered = captured.out + captured.err
    assert "https://example.invalid/token-secret" not in rendered


def test_fetch_output_excludes_sensitive_candidate_material(tmp_path, capsys, monkeypatch) -> None:
    """Avoid printing URI and credential placeholders in fetch output."""
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes: (
            [_fetched_subscription()],
            FetchSummary(
                source_count=1,
                fetched_count=1,
                disabled_count=0,
                failed_count=0,
                total_bytes=120,
                errors=[],
            ),
        ),
    )

    exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(tmp_path / "candidates.json")]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    rendered = captured.out + captured.err
    assert "vless://" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered


def test_fetch_returns_two_when_nothing_is_fetched(tmp_path, capsys, monkeypatch) -> None:
    """Return status 2 when no enabled subscriptions are fetched."""
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes: (
            [],
            FetchSummary(
                source_count=1,
                fetched_count=0,
                disabled_count=1,
                failed_count=0,
                total_bytes=0,
                errors=[],
            ),
        ),
    )

    exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(tmp_path / "candidates.json")]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "fetched_count: 0" in captured.out


def test_fetch_returns_two_when_no_candidates_are_parsed(tmp_path, capsys, monkeypatch) -> None:
    """Return status 2 when fetched content yields zero candidates."""
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes: (
            [FetchedSubscription(source_name="fixture-source", content="# comments only\n", byte_count=16)],
            FetchSummary(
                source_count=1,
                fetched_count=1,
                disabled_count=0,
                failed_count=0,
                total_bytes=16,
                errors=[],
            ),
        ),
    )

    exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(tmp_path / "candidates.json")]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "parsed_count: 0" in captured.out


def test_fetch_rejects_non_positive_timeout(tmp_path, capsys) -> None:
    """Reject non-positive timeout values."""
    config_path = _write_config(tmp_path)

    exit_code = cli.main(
        [
            "fetch",
            "--config",
            str(config_path),
            "--allow-network-fetch",
            "--timeout",
            "0",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "timeout" in captured.err


def test_fetch_rejects_non_positive_max_bytes(tmp_path, capsys) -> None:
    """Reject non-positive byte limits."""
    config_path = _write_config(tmp_path)

    exit_code = cli.main(
        [
            "fetch",
            "--config",
            str(config_path),
            "--allow-network-fetch",
            "--max-bytes",
            "0",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "max-bytes" in captured.err


def test_fetch_returns_one_when_config_is_missing(tmp_path, capsys) -> None:
    """Return 1 when config loading fails."""
    exit_code = cli.main(
        [
            "fetch",
            "--config",
            str(tmp_path / "missing.yaml"),
            "--allow-network-fetch",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.err


def test_fetch_returns_one_when_write_fails(tmp_path, capsys, monkeypatch) -> None:
    """Return 1 when writing the candidate artifact fails."""
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes: (
            [_fetched_subscription()],
            FetchSummary(
                source_count=1,
                fetched_count=1,
                disabled_count=0,
                failed_count=0,
                total_bytes=120,
                errors=[],
            ),
        ),
    )
    monkeypatch.setattr(
        cli,
        "write_candidate_artifact",
        lambda path, payload: (_ for _ in ()).throw(OSError("disk full")),
    )

    exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(tmp_path / "candidates.json")]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "disk full" in captured.err


def test_fetch_does_not_call_probe_or_xray(tmp_path, monkeypatch) -> None:
    """Only call the fake fetcher and not any downstream runtime logic."""
    config_path = _write_config(tmp_path)
    observed = {"fetch": 0}

    def fake_fetch(sources, timeout_seconds, max_bytes):
        observed["fetch"] += 1
        return (
            [_fetched_subscription()],
            FetchSummary(
                source_count=1,
                fetched_count=1,
                disabled_count=0,
                failed_count=0,
                total_bytes=120,
                errors=[],
            ),
        )

    monkeypatch.setattr(cli, "fetch_enabled_subscriptions", fake_fetch)
    monkeypatch.setattr(
        cli,
        "probe_candidates_sequential",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("probe should not run")),
    )
    monkeypatch.setattr(
        cli,
        "prepare_candidate_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run should not start")),
    )

    exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(tmp_path / "candidates.json")]
    )

    assert exit_code == 0
    assert observed["fetch"] == 1


def test_probe_generate_run_and_inspect_remain_available(tmp_path, capsys, monkeypatch) -> None:
    """Keep existing wired subcommands available after adding fetch."""
    config_path = _write_config(tmp_path, allow_network_probe=True)
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(json.dumps({"candidates": [_candidate_mapping()]}), encoding="utf-8")
    monkeypatch.setattr(cli, "probe_candidates_sequential", lambda candidates, xray_config, options: _batch_summary())
    monkeypatch.setattr(cli, "write_probe_artifacts", lambda **kwargs: _artifact_result(tmp_path))
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes: (
            [_fetched_subscription()],
            FetchSummary(
                source_count=1,
                fetched_count=1,
                disabled_count=0,
                failed_count=0,
                total_bytes=120,
                errors=[],
            ),
        ),
    )

    fetch_exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(tmp_path / "fetched.json")]
    )
    capsys.readouterr()
    probe_exit_code = cli.main(
        ["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--allow-network-probe"]
    )
    capsys.readouterr()
    generate_exit_code = cli.main(["generate", "--config", str(config_path), "--candidates", str(candidates_path)])
    capsys.readouterr()
    run_exit_code = cli.main(["run", "--config", str(config_path), "--candidates", str(candidates_path)])
    capsys.readouterr()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest_payload()), encoding="utf-8")
    inspect_exit_code = cli.main(["inspect", "--manifest", str(manifest_path)])
    capsys.readouterr()

    assert fetch_exit_code == 0
    assert probe_exit_code == 0
    assert generate_exit_code == 0
    assert run_exit_code == 0
    assert inspect_exit_code == 0


def _write_config(
    tmp_path: Path,
    *,
    subscription_url: str = "https://example.invalid/subscription",
    allow_network_probe: bool = False,
) -> Path:
    """Write one placeholder config file for fetch CLI tests."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "subscriptions:",
                '  - name: "fixture-source"',
                f'    url: "{subscription_url}"',
                '    format: "auto"',
                "    enabled: true",
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


def _fetched_subscription() -> FetchedSubscription:
    """Build one fetched VLESS subscription payload."""
    content = (
        "vless://00000000-0000-0000-0000-000000000000@example.invalid:443"
        "?security=reality&pbk=PUBLIC_KEY_PLACEHOLDER&sni=www.cloudflare.com#US%20Scholar%20IPv4"
    )
    return FetchedSubscription(source_name="fixture-source", content=content, byte_count=len(content))


def _unsupported_fetched_subscription() -> FetchedSubscription:
    """Build one unsupported fetched subscription payload."""
    content = "vmess://example.invalid:443#Unsupported"
    return FetchedSubscription(source_name="fixture-source", content=content, byte_count=len(content))


def _candidate_mapping() -> dict[str, object]:
    """Build one placeholder candidate mapping."""
    return {
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


def _manifest_payload() -> dict[str, object]:
    """Build one manifest payload for inspect compatibility."""
    return {
        "schema_version": 1,
        "generated_at": "2026-05-25T00:00:00Z",
        "selected": [{"tag": "google-scholar-node-001", "candidate": {"raw_name": "node"}, "probe": None}],
        "rejected": [],
    }


def _artifact_result(tmp_path: Path) -> dict[str, object]:
    """Build one probe artifact summary for CLI compatibility tests."""
    return {
        "summary_path": str(tmp_path / "probe_summary.json"),
        "passed_candidates_path": str(tmp_path / "passed_candidates.json"),
        "passed_count": 1,
        "attempted_count": 1,
        "skipped_count": 0,
        "failed_count": 0,
    }


def _batch_summary():
    """Build one successful batch probe summary for compatibility checks."""
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
