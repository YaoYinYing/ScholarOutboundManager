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
    assert "loaded_count: 1" in captured.out
    assert "filtered_count: 1" in captured.out
    assert "filter_skipped_count: 0" in captured.out


def test_generate_applies_candidate_filters_before_generation(tmp_path, capsys) -> None:
    """Filter candidates before JSON generation and report filter counts."""
    config_path = _write_config(
        tmp_path,
        include_keywords=["Scholar"],
        exclude_keywords=["Exclude"],
        deprioritize_keywords=["slow"],
    )
    candidates_path = _write_candidates(
        tmp_path,
        candidates=[
            _candidate_mapping(raw_name="US Scholar IPv4"),
            _candidate_mapping(raw_name="Exclude Scholar Node"),
            _candidate_mapping(raw_name="slow Scholar Node"),
        ],
    )

    exit_code = cli.main(
        ["generate", "--config", str(config_path), "--candidates", str(candidates_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "loaded_count: 3" in captured.out
    assert "filtered_count: 2" in captured.out
    assert "filter_skipped_count: 1" in captured.out
    manifest_text = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert "Exclude Scholar Node" not in manifest_text


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


def test_fetch_remains_unimplemented(capsys) -> None:
    """Keep fetch in the placeholder state."""
    for command_name in ("fetch",):
        exit_code = cli.main([command_name])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "not implemented in Phase 0.5" in captured.out


def _write_config(
    tmp_path,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    deprioritize_keywords: list[str] | None = None,
):
    """Write one placeholder configuration file for CLI tests."""
    include_keywords = include_keywords or []
    exclude_keywords = exclude_keywords or []
    deprioritize_keywords = deprioritize_keywords or []
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "subscriptions: []",
                "filters:",
                f"  include_keywords: [{', '.join(_quote_yaml(item) for item in include_keywords)}]",
                f"  exclude_keywords: [{', '.join(_quote_yaml(item) for item in exclude_keywords)}]",
                f"  deprioritize_keywords: [{', '.join(_quote_yaml(item) for item in deprioritize_keywords)}]",
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


def _write_candidates(tmp_path, candidates: list[dict[str, object]] | None = None):
    """Write one placeholder candidate file for CLI tests."""
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(
        json.dumps(
            {
                "candidates": candidates or [_candidate_mapping()],
            }
        ),
        encoding="utf-8",
    )
    return candidates_path


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
    }
    candidate.update(overrides)
    return candidate


def _quote_yaml(value: str) -> str:
    """Quote a YAML scalar for compact inline test config output."""
    return f'"{value}"'
