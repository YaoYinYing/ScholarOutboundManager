"""Tests for the local live A/B fetch smoke-test harness."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def test_read_link_file_ignores_empty_and_comment_lines(tmp_path) -> None:
    """Ignore blank lines and comments when reading one link file."""
    module = _load_script_module()
    links_path = tmp_path / "links.txt"
    links_path.write_text(
        "\n".join(
            [
                "",
                "# comment",
                "https://example.invalid/subscription-a",
                "   ",
                "https://example.invalid/subscription-b",
            ]
        ),
        encoding="utf-8",
    )

    links = module.read_link_file(links_path)

    assert links == [
        "https://example.invalid/subscription-a",
        "https://example.invalid/subscription-b",
    ]


def test_build_group_config_does_not_print_urls(tmp_path, capsys) -> None:
    """Avoid printing while building a local group config."""
    module = _load_script_module()
    payload = module.build_group_config(
        "valid",
        ["https://example.invalid/subscription-a"],
        tmp_path / "work",
        "fake-xray",
    )
    captured = capsys.readouterr()

    assert payload["subscriptions"][0]["url"] == "https://example.invalid/subscription-a"
    assert captured.out == ""
    assert captured.err == ""


def test_redact_live_output_redacts_http_urls() -> None:
    """Redact subscription URLs in captured CLI output."""
    module = _load_script_module()

    redacted = module.redact_live_output("fetching https://example.invalid/token-secret")

    assert "https://example.invalid/token-secret" not in redacted
    assert "<REDACTED_URL>" in redacted


def test_redact_live_output_redacts_vless_uri() -> None:
    """Redact full VLESS URIs in captured CLI output."""
    module = _load_script_module()

    redacted = module.redact_live_output(
        "vless://00000000-0000-0000-0000-000000000000@example.invalid:443"
    )

    assert "vless://" not in redacted
    assert "<REDACTED_VLESS_URI>" in redacted


def test_redact_live_output_redacts_uuid() -> None:
    """Redact UUID values in captured CLI output."""
    module = _load_script_module()

    redacted = module.redact_live_output("uuid=00000000-0000-0000-0000-000000000000")

    assert "00000000-0000-0000-0000-000000000000" not in redacted
    assert "<REDACTED_UUID>" in redacted


def test_summary_does_not_include_raw_link(tmp_path) -> None:
    """Keep raw links out of the redacted summary payload."""
    module = _load_script_module()
    work_dir = tmp_path / "work"
    output_path = work_dir / "valid" / "candidates.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sensitive": True,
                "source_count": 1,
                "fetched_count": 1,
                "failed_count": 0,
                "parsed_count": 1,
                "unsupported_count": 0,
                "fetch_errors": [
                    {
                        "source_name": "valid_001",
                        "category": "http_error",
                        "message": "Subscription source 'valid_001' failed: <REDACTED_URL>",
                        "http_status": 403,
                    }
                ],
                "candidates": [
                    {
                        "source_name": "valid_001",
                        "raw_name": "node-a",
                        "protocol": "vless",
                        "address": "example.invalid",
                        "port": 443,
                        "user_id": "00000000-0000-0000-0000-000000000000",
                        "public_key": "PUBLIC_KEY_PLACEHOLDER",
                        "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
                        "supported": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    group_summary = module.summarize_candidate_artifact(output_path)
    payload = module.build_live_ab_summary(
        {
            "link_count": 1,
            "exit_code": 0,
            **group_summary,
            "output_path": str(output_path),
        },
        {
            "link_count": 1,
            "exit_code": 2,
            "source_count": 1,
            "fetched_count": 0,
            "failed_count": 1,
            "parsed_count": 0,
            "supported_count": 0,
            "unsupported_count": 0,
            "output_path": str(work_dir / "invalid" / "candidates.json"),
        },
    )

    rendered = json.dumps(payload)
    assert "https://example.invalid" not in rendered
    assert "vless://" not in rendered


def test_summarize_candidate_artifact_reads_fetch_error_counts(tmp_path) -> None:
    """Summarize fetch error categories and HTTP status counts."""
    module = _load_script_module()
    output_path = tmp_path / "candidates.json"
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sensitive": True,
                "source_count": 1,
                "fetched_count": 0,
                "failed_count": 2,
                "parsed_count": 0,
                "unsupported_count": 0,
                "fetch_errors": [
                    {
                        "source_name": "valid_001",
                        "category": "http_error",
                        "message": "Subscription source 'valid_001' failed: <REDACTED_URL>",
                        "http_status": 403,
                    },
                    {
                        "source_name": "valid_001",
                        "category": "timeout",
                        "message": "Subscription source 'valid_001' failed: timed out",
                        "http_status": None,
                    },
                ],
                "candidates": [],
            }
        ),
        encoding="utf-8",
    )

    summary = module.summarize_candidate_artifact(output_path)

    assert summary["fetch_error_categories"] == {"http_error": 1, "timeout": 1}
    assert summary["fetch_http_statuses"] == {"403": 1}


def test_run_fetch_command_can_be_simulated_without_network(tmp_path) -> None:
    """Allow tests to inject a fake subprocess runner."""
    module = _load_script_module()
    observed: dict[str, object] = {}

    def fake_runner(command, cwd, text, capture_output, check):
        observed["command"] = command
        observed["cwd"] = cwd
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    result = module.run_fetch_command(
        tmp_path / "config.yaml",
        tmp_path / "candidates.json",
        cwd=tmp_path,
        runner=fake_runner,
    )

    assert result.returncode == 0
    assert observed["command"][2:4] == ["scholar_outbound_manager.cli", "fetch"]
    assert "--allow-network-fetch" in observed["command"]


def test_run_fetch_command_includes_proxy_url_when_provided(tmp_path) -> None:
    """Append the proxy flag when one is provided."""
    module = _load_script_module()
    observed: dict[str, object] = {}

    def fake_runner(command, cwd, text, capture_output, check):
        observed["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    module.run_fetch_command(
        tmp_path / "config.yaml",
        tmp_path / "candidates.json",
        proxy_url="http://oreo:oreo@127.0.0.1:10089",
        cwd=tmp_path,
        runner=fake_runner,
    )

    assert "--proxy-url" in observed["command"]


def test_run_fetch_command_omits_proxy_url_when_not_provided(tmp_path) -> None:
    """Avoid adding the proxy flag when it is not provided."""
    module = _load_script_module()
    observed: dict[str, object] = {}

    def fake_runner(command, cwd, text, capture_output, check):
        observed["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    module.run_fetch_command(
        tmp_path / "config.yaml",
        tmp_path / "candidates.json",
        cwd=tmp_path,
        runner=fake_runner,
    )

    assert "--proxy-url" not in observed["command"]


def test_redact_live_output_redacts_proxy_url_with_credentials() -> None:
    """Redact proxy URLs even when they contain credentials."""
    module = _load_script_module()
    proxy_url = "http://oreo:oreo@127.0.0.1:10089"

    redacted = module.redact_live_output(f"using proxy {proxy_url}")

    assert proxy_url not in redacted
    assert "<REDACTED_URL>" in redacted


def test_main_uses_fake_runner_and_writes_redacted_summary(tmp_path, monkeypatch, capsys) -> None:
    """Run the harness with a fake fetch command and no real network access."""
    module = _load_script_module()
    valid_links = tmp_path / "valid.txt"
    invalid_links = tmp_path / "invalid.txt"
    work_dir = tmp_path / "state_data" / "live_ab"
    valid_links.write_text("https://example.invalid/subscription-a\n", encoding="utf-8")
    invalid_links.write_text("# comment only\n", encoding="utf-8")

    def fake_run_fetch_command(config_path, output_path, *, proxy_url=None, cwd=None, runner=None):
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        if Path(config_path).parent.name == "valid":
            output_file.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "sensitive": True,
                        "source_count": 1,
                        "fetched_count": 1,
                        "failed_count": 0,
                        "parsed_count": 1,
                        "unsupported_count": 0,
                        "fetch_errors": [],
                        "candidates": [
                            {
                                "source_name": "valid_001",
                                "raw_name": "node-a",
                                "protocol": "vless",
                                "address": "example.invalid",
                                "port": 443,
                                "user_id": "00000000-0000-0000-0000-000000000000",
                                "public_key": "PUBLIC_KEY_PLACEHOLDER",
                                "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
                                "supported": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                ["python", "-m", "scholar_outbound_manager.cli", "fetch"],
                0,
                stdout="Fetched from https://example.invalid/subscription-a",
                stderr="",
            )
        output_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "sensitive": True,
                    "source_count": 0,
                    "fetched_count": 0,
                    "failed_count": 0,
                    "parsed_count": 0,
                    "unsupported_count": 0,
                    "fetch_errors": [
                        {
                            "source_name": "invalid_001",
                            "category": "http_error",
                            "message": "Subscription source 'invalid_001' failed: <REDACTED_URL>",
                            "http_status": 403,
                        }
                    ],
                    "candidates": [],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            ["python", "-m", "scholar_outbound_manager.cli", "fetch"],
            2,
            stdout="Fetched Scholar candidate subscriptions.",
            stderr="",
        )

    monkeypatch.setattr(module, "run_fetch_command", fake_run_fetch_command)

    exit_code = module.main(
        [
            "--valid-links",
            str(valid_links),
            "--invalid-links",
            str(invalid_links),
            "--work-dir",
            str(work_dir),
            "--xray-binary",
            "fake-xray",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "https://example.invalid/subscription-a" not in captured.out
    assert "vless://" not in captured.out
    summary = json.loads((work_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["groups"]["valid"]["parsed_count"] == 1
    assert summary["groups"]["invalid"]["parsed_count"] == 0
    assert summary["groups"]["invalid"]["fetch_error_categories"] == {"http_error": 1}
    assert summary["groups"]["invalid"]["fetch_http_statuses"] == {"403": 1}
    assert summary["interpretation"]["secrets_redacted"] is True
    assert "https://example.invalid" not in json.dumps(summary)


def test_parser_accepts_proxy_url_argument() -> None:
    """Accept one optional proxy URL argument."""
    module = _load_script_module()
    parser = module.build_parser()

    args = parser.parse_args(
        [
            "--valid-links",
            "valid.txt",
            "--invalid-links",
            "invalid.txt",
            "--work-dir",
            "state_data/live_ab",
            "--xray-binary",
            "fake-xray",
            "--proxy-url",
            "http://127.0.0.1:7890",
        ]
    )

    assert args.proxy_url == "http://127.0.0.1:7890"


def _load_script_module():
    """Load the smoke-test script as a Python module for unit tests."""
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "live_ab_fetch_test.py"
    spec = importlib.util.spec_from_file_location("live_ab_fetch_test_module", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("live_ab_fetch_test_module", module)
    spec.loader.exec_module(module)
    return module
