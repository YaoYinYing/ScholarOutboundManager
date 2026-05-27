"""Tests for sidecar pool CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from scholar_outbound_manager import cli


def test_sidecar_pool_plan_writes_redacted_plan(tmp_path: Path, capsys) -> None:
    """Plan one pool and write its redacted artifact."""
    candidates_path = _write_passed_candidates(tmp_path)
    output_path = tmp_path / "sidecar_pool_plan.json"

    exit_code = cli.main(
        [
            "sidecar",
            "pool",
            "plan",
            "--candidates",
            str(candidates_path),
            "--output",
            str(output_path),
            "--max-count",
            "1",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert "entry_count: 1" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_sidecar_pool_check_ports_reports_availability(tmp_path: Path, capsys, monkeypatch) -> None:
    """Report port availability for each plan entry."""
    plan_path = _write_plan(tmp_path)
    monkeypatch.setattr(cli, "check_pool_ports_available", lambda plan: {0: True, 1: False})

    exit_code = cli.main(["sidecar", "pool", "check-ports", "--plan", str(plan_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "pool_index: 0" in captured.out
    assert "available: false" in captured.out


def test_sidecar_pool_stage_does_not_install_or_start_service(tmp_path: Path, capsys, monkeypatch) -> None:
    """Stage pool files without calling systemctl."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_passed_candidates(tmp_path)
    plan_path = _write_plan(tmp_path)
    source_binary = tmp_path / "xray"
    source_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    source_binary.chmod(0o755)
    called = {"stage": False, "systemctl": False}

    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(cli, "check_pool_ports_available", lambda plan: {0: True, 1: True})

    def fake_stage(**kwargs):
        called["stage"] = True
        return type(
            "Paths",
            (),
            {
                "xray_binary_path": str(tmp_path / "opt" / "xray" / "xray"),
                "runtime_config_path": str(tmp_path / "etc" / "scholar_sidecar_runtime.json"),
                "metadata_path": str(tmp_path / "var" / "scholar_sidecar_pool.metadata.json"),
            },
        )()

    def fail_run_systemctl(*args, **kwargs):
        called["systemctl"] = True
        raise AssertionError("pool stage must not call systemctl")

    monkeypatch.setattr(cli, "stage_single_xray_pool_files", fake_stage)
    monkeypatch.setattr(cli, "run_systemctl", fail_run_systemctl)

    exit_code = cli.main(
        [
            "sidecar",
            "pool",
            "stage",
            "--config",
            str(config_path),
            "--candidates",
            str(candidates_path),
            "--plan",
            str(plan_path),
            "--install-root",
            str(tmp_path / "opt"),
            "--config-dir",
            str(tmp_path / "etc"),
            "--state-dir",
            str(tmp_path / "var"),
            "--source-xray-binary",
            str(source_binary),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert called["stage"] is True
    assert called["systemctl"] is False
    assert "staged: true" in captured.out


def test_sidecar_pool_validate_outputs_redacted_results(tmp_path: Path, capsys, monkeypatch) -> None:
    """Validate pool ports through a monkeypatched validator."""
    plan_path = _write_plan(tmp_path)
    monkeypatch.setattr(
        cli,
        "validate_pool_sidecar",
        lambda plan, query="ppr", request_timeout=15.0: [
            {
                "pool_index": 0,
                "listen_port": 19080,
                "tcp_connect": True,
                "home_status": 200,
                "query_status": 200,
                "scholar_stage": "full_access",
                "passed": True,
                "failure_markers": [],
            },
            {
                "pool_index": 1,
                "listen_port": 19081,
                "tcp_connect": True,
                "home_status": 200,
                "query_status": 403,
                "scholar_stage": "query_blocked",
                "passed": False,
                "failure_markers": ["stage_query_blocked"],
            },
        ],
    )

    exit_code = cli.main(["sidecar", "pool", "validate", "--plan", str(plan_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    payload = json.loads(captured.out)
    assert payload[0]["scholar_stage"] == "full_access"
    _assert_no_secrets(captured.out + captured.err)


def test_sidecar_pool_snippets_outputs_json(tmp_path: Path, capsys) -> None:
    """Render downstream SOCKS snippets as JSON."""
    plan_path = _write_plan(tmp_path)

    exit_code = cli.main(["sidecar", "pool", "snippets", "--plan", str(plan_path), "--json"])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload[0]["protocol"] == "socks"
    assert payload[1]["settings"]["servers"][0]["port"] == 19081


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


def _write_passed_candidates(tmp_path: Path) -> Path:
    path = tmp_path / "passed_candidates.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sensitive": True,
                "candidates": [
                    {
                        "candidate": {
                            "source_name": "fixture",
                            "raw_name": "node-a",
                            "protocol": "vless",
                            "address": "example.invalid",
                            "port": 443,
                            "user_id": "00000000-0000-0000-0000-000000000000",
                            "security": "reality",
                            "server_name": "www.cloudflare.com",
                            "public_key": "PUBLIC_KEY_PLACEHOLDER",
                            "supported": True,
                            "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
                        },
                        "probe": {
                            "candidate_id": "candidate-001",
                            "home_status": 200,
                            "query_status": 200,
                            "blocked": False,
                            "timeout": False,
                            "error": None,
                            "failure_markers": [],
                            "latency_ms": 10,
                            "checked_at": "2026-05-27T00:00:00Z",
                            "passed": True,
                        },
                    },
                    {
                        "candidate": {
                            "source_name": "fixture",
                            "raw_name": "node-b",
                            "protocol": "trojan",
                            "address": "example-b.invalid",
                            "port": 443,
                            "password": "PASSWORD_PLACEHOLDER",
                            "security": "tls",
                            "server_name": "www.cloudflare.com",
                            "supported": True,
                        },
                        "probe": {
                            "candidate_id": "candidate-002",
                            "home_status": 200,
                            "query_status": 200,
                            "blocked": False,
                            "timeout": False,
                            "error": None,
                            "failure_markers": [],
                            "latency_ms": 10,
                            "checked_at": "2026-05-27T00:00:00Z",
                            "passed": True,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_plan(tmp_path: Path) -> Path:
    plan_path = tmp_path / "sidecar_pool_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "single_xray_multi_port",
                "created_at": "2026-05-27T00:00:00Z",
                "listen_host": "127.0.0.1",
                "base_port": 19080,
                "count": 2,
                "entries": [
                    {
                        "pool_index": 0,
                        "candidate_id": "candidate-001",
                        "candidate_protocol": "vless",
                        "listen_host": "127.0.0.1",
                        "listen_port": 19080,
                        "inbound_tag": "scholar-sidecar-socks-in-0",
                        "outbound_tag": "scholar-sidecar-out-0",
                        "socks_tag": "scholar-sidecar-socks-out-0",
                    },
                    {
                        "pool_index": 1,
                        "candidate_id": "candidate-002",
                        "candidate_protocol": "trojan",
                        "listen_host": "127.0.0.1",
                        "listen_port": 19081,
                        "inbound_tag": "scholar-sidecar-socks-in-1",
                        "outbound_tag": "scholar-sidecar-out-1",
                        "socks_tag": "scholar-sidecar-socks-out-1",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return plan_path


def _assert_no_secrets(rendered: str) -> None:
    lowered = rendered.lower()
    assert "raw_uri" not in lowered
    assert "00000000-0000-0000-0000-000000000000" not in lowered
    assert "public_key_placeholder" not in lowered
    assert "password_placeholder" not in lowered
