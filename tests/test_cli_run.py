"""Tests for the runtime run CLI command."""

from __future__ import annotations

import json
import os
from pathlib import Path

from scholar_outbound_manager import cli


def test_run_command_prepares_runtime_config(tmp_path, capsys) -> None:
    """Prepare one runtime config from the selected candidate."""
    fake_binary = _write_fake_binary(tmp_path, "success")
    config_path = _write_config(tmp_path, fake_binary)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(["run", "--config", str(config_path), "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert (tmp_path / "runtime" / "candidate_runtime.json").exists()
    assert "candidate_index: 0" in captured.out
    assert "candidate_name: US Scholar IPv4" in captured.out
    assert f"runtime_config_path: {tmp_path / 'runtime' / 'candidate_runtime.json'}" in captured.out
    assert "local_socks_host: 127.0.0.1" in captured.out
    assert "local_socks_port: 1081" in captured.out


def test_run_without_test_config_does_not_execute_fake_binary(tmp_path, capsys) -> None:
    """Do not execute the configured binary unless test-config is requested."""
    marker_path = tmp_path / "fake-binary-marker.txt"
    fake_binary = _write_fake_binary(tmp_path, "success", marker_path=marker_path)
    config_path = _write_config(tmp_path, fake_binary)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(["run", "--config", str(config_path), "--candidates", str(candidates_path)])
    capsys.readouterr()

    assert exit_code == 0
    assert not marker_path.exists()


def test_run_with_test_config_reports_success(tmp_path, capsys) -> None:
    """Report success when the fake Xray config test passes."""
    fake_binary = _write_fake_binary(tmp_path, "success")
    config_path = _write_config(tmp_path, fake_binary)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        ["run", "--config", str(config_path), "--candidates", str(candidates_path), "--test-config"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Xray config test: passed" in captured.out


def test_run_with_test_config_reports_failure(tmp_path, capsys) -> None:
    """Report failure when the fake Xray config test fails."""
    fake_binary = _write_fake_binary(tmp_path, "fail")
    config_path = _write_config(tmp_path, fake_binary)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        ["run", "--config", str(config_path), "--candidates", str(candidates_path), "--test-config"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Xray config test: failed" in captured.out
    assert "returncode: 9" in captured.out


def test_run_with_test_config_reports_timeout(tmp_path, capsys) -> None:
    """Report timeout when the fake Xray config test exceeds the timeout."""
    fake_binary = _write_fake_binary(tmp_path, "sleep")
    config_path = _write_config(tmp_path, fake_binary)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        [
            "run",
            "--config",
            str(config_path),
            "--candidates",
            str(candidates_path),
            "--test-config",
            "--xray-test-timeout",
            "0.1",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Xray config test: failed" in captured.out
    assert "timed_out: True" in captured.out


def test_run_requires_candidates_argument(capsys) -> None:
    """Return an argparse error when candidates are omitted."""
    exit_code = cli.main(["run", "--config", "config.yaml"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "--candidates" in captured.err


def test_run_rejects_out_of_range_candidate_index(tmp_path, capsys) -> None:
    """Reject candidate indices outside the loaded list."""
    fake_binary = _write_fake_binary(tmp_path, "success")
    config_path = _write_config(tmp_path, fake_binary)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        ["run", "--config", str(config_path), "--candidates", str(candidates_path), "--candidate-index", "1"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.err


def test_run_rejects_unsupported_candidate(tmp_path, capsys) -> None:
    """Reject unsupported selected candidates."""
    fake_binary = _write_fake_binary(tmp_path, "success")
    config_path = _write_config(tmp_path, fake_binary)
    candidates_path = _write_candidates(
        tmp_path,
        supported=False,
        unsupported_reason="Unsupported transport.",
    )

    exit_code = cli.main(["run", "--config", str(config_path), "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Unsupported transport." in captured.err


def test_run_rejects_runtime_config_name_with_path_separator(tmp_path, capsys) -> None:
    """Reject runtime config names that contain path separators."""
    fake_binary = _write_fake_binary(tmp_path, "success")
    config_path = _write_config(tmp_path, fake_binary)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        [
            "run",
            "--config",
            str(config_path),
            "--candidates",
            str(candidates_path),
            "--runtime-config-name",
            "nested/runtime.json",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "runtime-config-name" in captured.err


def test_run_rejects_absolute_runtime_config_name(tmp_path, capsys) -> None:
    """Reject absolute runtime config names."""
    fake_binary = _write_fake_binary(tmp_path, "success")
    config_path = _write_config(tmp_path, fake_binary)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        [
            "run",
            "--config",
            str(config_path),
            "--candidates",
            str(candidates_path),
            "--runtime-config-name",
            str(tmp_path / "runtime.json"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "absolute path" in captured.err


def test_run_rejects_non_positive_xray_timeout(tmp_path, capsys) -> None:
    """Reject non-positive Xray config test timeouts."""
    fake_binary = _write_fake_binary(tmp_path, "success")
    config_path = _write_config(tmp_path, fake_binary)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        [
            "run",
            "--config",
            str(config_path),
            "--candidates",
            str(candidates_path),
            "--xray-test-timeout",
            "0",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "xray-test-timeout" in captured.err


def test_run_output_excludes_sensitive_values(tmp_path, capsys) -> None:
    """Keep runtime CLI output free of sensitive candidate material."""
    fake_binary = _write_fake_binary(tmp_path, "success")
    config_path = _write_config(tmp_path, fake_binary)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(["run", "--config", str(config_path), "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "vless://" not in captured.out
    assert "PUBLIC_KEY_PLACEHOLDER" not in captured.out
    assert "00000000-0000-0000-0000-000000000000" not in captured.out


def test_fetch_probe_and_inspect_remain_unimplemented(capsys) -> None:
    """Keep unrelated CLI subcommands in the placeholder state."""
    for command_name in ("fetch", "probe", "inspect"):
        exit_code = cli.main([command_name])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "not implemented in Phase 0.5" in captured.out


def test_generate_behavior_remains_available(tmp_path, capsys) -> None:
    """Keep the generate command wired after adding run support."""
    fake_binary = _write_fake_binary(tmp_path, "success")
    config_path = _write_config(tmp_path, fake_binary)
    candidates_path = _write_candidates(tmp_path)

    exit_code = cli.main(
        ["generate", "--config", str(config_path), "--candidates", str(candidates_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Generated Scholar outbound artifacts." in captured.out


def _write_config(tmp_path: Path, fake_binary: Path) -> Path:
    """Write one placeholder config file for run CLI tests."""
    runtime_dir = tmp_path / "runtime"
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
                f"  binary_path: {fake_binary}",
                f"  runtime_dir: {runtime_dir}",
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


def _write_candidates(
    tmp_path: Path,
    *,
    supported: bool = True,
    unsupported_reason: str | None = None,
) -> Path:
    """Write one placeholder candidate file for run CLI tests."""
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
                        "supported": supported,
                        "unsupported_reason": unsupported_reason,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return candidates_path


def _write_fake_binary(tmp_path: Path, mode: str, marker_path: Path | None = None) -> Path:
    """Write one fake Xray binary script for run CLI tests."""
    script_path = tmp_path / f"fake-run-xray-{mode}.py"
    marker_line = f"Path({str(marker_path)!r}).write_text('executed', encoding='utf-8')" if marker_path else ""
    script_path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "from pathlib import Path",
                "import sys",
                "import time",
                "",
                f"MODE = {mode!r}",
                marker_line,
                "if MODE == 'success':",
                "    raise SystemExit(0)",
                "if MODE == 'fail':",
                "    raise SystemExit(9)",
                "if MODE == 'sleep':",
                "    time.sleep(1.0)",
                "    raise SystemExit(0)",
                "raise SystemExit(3)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    os.chmod(script_path, 0o755)
    return script_path
