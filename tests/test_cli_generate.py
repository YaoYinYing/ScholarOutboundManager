"""Tests for the offline generate CLI command."""

from __future__ import annotations

import json

from scholar_outbound_manager import cli


def test_generate_command_succeeds_with_offline_candidates(tmp_path, capsys) -> None:
    """Return success and write output artifacts for offline generation."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        ["generate", "--config", str(config_path), "--candidates", str(candidates_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert (tmp_path / "outbounds.json").exists()
    assert (tmp_path / "routes.json").exists()
    assert (tmp_path / "manifest.json").exists()
    assert "selected_count: 1" in captured.out
    assert "rejected_count: 0" in captured.out
    assert f"outbounds_path: {tmp_path / 'outbounds.json'}" in captured.out
    assert f"routes_path: {tmp_path / 'routes.json'}" in captured.out
    assert f"manifest_path: {tmp_path / 'manifest.json'}" in captured.out


def test_generate_requires_candidates_argument(capsys) -> None:
    """Return an argparse error when candidates are omitted."""
    exit_code = cli.main(["generate", "--config", "config.yaml"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "--candidates" in captured.err


def test_generate_returns_nonzero_when_candidate_file_is_missing(tmp_path, capsys) -> None:
    """Return a readable error when the candidate file does not exist."""
    config_path = _write_config(tmp_path)

    exit_code = cli.main(
        ["generate", "--config", str(config_path), "--candidates", str(tmp_path / "missing.json")]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.err
    assert "missing.json" in captured.err


def test_generate_returns_nonzero_when_config_file_is_missing(tmp_path, capsys) -> None:
    """Return a readable error when the config file does not exist."""
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        ["generate", "--config", str(tmp_path / "missing-config.yaml"), "--candidates", str(candidates_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.err
    assert "missing-config.yaml" in captured.err


def test_generate_does_not_print_raw_uri(tmp_path, capsys) -> None:
    """Keep raw URI source material out of console output."""
    config_path = _write_config(tmp_path)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        ["generate", "--config", str(config_path), "--candidates", str(candidates_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "vless://" not in captured.out
    assert "vless://" not in captured.err


def test_other_subcommands_remain_unimplemented(capsys) -> None:
    """Keep fetch and inspect in the placeholder state."""
    for command_name in ("fetch", "inspect"):
        exit_code = cli.main([command_name])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "not implemented in Phase 0.5" in captured.out


def _write_config(tmp_path):
    """Write one placeholder configuration file for CLI tests."""
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
                "  allow_network_probe: false",
                "xray:",
                "  binary_path: xray",
                "  runtime_dir: runtime",
                "  local_socks_host: 127.0.0.1",
                "  local_socks_port: 1080",
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
    """Write one placeholder candidate file for CLI tests."""
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
