"""Tests for the subscription fetch CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from scholar_outbound_manager import cli
from scholar_outbound_manager.fetcher import FetchErrorRecord
from scholar_outbound_manager.fetcher import FetchSummary
from scholar_outbound_manager.fetcher import FetchedSubscription
from scholar_outbound_manager.fetcher import FetchTransportOptions


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
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [_fetched_subscription()],
            _summary(source_count=1, fetched_count=1, disabled_count=0, failed_count=0, total_bytes=120),
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
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [_fetched_subscription(), _unsupported_fetched_subscription()],
            _summary(source_count=2, fetched_count=2, disabled_count=0, failed_count=0, total_bytes=240),
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
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [_fetched_subscription()],
            _summary(source_count=1, fetched_count=1, disabled_count=0, failed_count=0, total_bytes=120),
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
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [_fetched_subscription()],
            _summary(source_count=1, fetched_count=1, disabled_count=0, failed_count=0, total_bytes=120),
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
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [],
            _summary(source_count=1, fetched_count=0, disabled_count=1, failed_count=0, total_bytes=0),
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
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [FetchedSubscription(source_name="fixture-source", content="# comments only\n", byte_count=16)],
            _summary(source_count=1, fetched_count=1, disabled_count=0, failed_count=0, total_bytes=16),
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
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--timeout", "0"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "timeout" in captured.err


def test_fetch_rejects_non_positive_max_bytes(tmp_path, capsys) -> None:
    """Reject non-positive byte limits."""
    config_path = _write_config(tmp_path)

    exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--max-bytes", "0"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "max-bytes" in captured.err


def test_fetch_returns_one_when_config_is_missing(tmp_path, capsys) -> None:
    """Return 1 when config loading fails."""
    exit_code = cli.main(["fetch", "--config", str(tmp_path / "missing.yaml"), "--allow-network-fetch"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error:" in captured.err


def test_fetch_returns_one_when_write_fails(tmp_path, capsys, monkeypatch) -> None:
    """Return 1 when writing the candidate artifact fails."""
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [_fetched_subscription()],
            _summary(source_count=1, fetched_count=1, disabled_count=0, failed_count=0, total_bytes=120),
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

    def fake_fetch(sources, timeout_seconds, max_bytes, transport_options=None):
        observed["fetch"] += 1
        return (
            [_fetched_subscription()],
            _summary(source_count=1, fetched_count=1, disabled_count=0, failed_count=0, total_bytes=120),
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
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [_fetched_subscription()],
            _summary(source_count=1, fetched_count=1, disabled_count=0, failed_count=0, total_bytes=120),
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


def test_fetch_prints_error_category_counts(tmp_path, capsys, monkeypatch) -> None:
    """Print non-secret fetch error category counts."""
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [],
            _summary(
                source_count=1,
                fetched_count=0,
                disabled_count=0,
                failed_count=2,
                total_bytes=0,
                errors=["safe", "safe"],
                error_records=[
                    FetchErrorRecord("fixture-source", "http_error", "safe", http_status=403),
                    FetchErrorRecord("fixture-source", "timeout", "safe"),
                ],
            ),
        ),
    )

    exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(tmp_path / "candidates.json")]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "fetch_error_http_error_count: 1" in captured.out
    assert "fetch_error_timeout_count: 1" in captured.out


def test_fetch_prints_http_status_counts(tmp_path, capsys, monkeypatch) -> None:
    """Print HTTP status counts when structured diagnostics include them."""
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [],
            _summary(
                source_count=1,
                fetched_count=0,
                disabled_count=0,
                failed_count=1,
                total_bytes=0,
                errors=["safe"],
                error_records=[FetchErrorRecord("fixture-source", "http_error", "safe", http_status=403)],
            ),
        ),
    )

    exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(tmp_path / "candidates.json")]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "http_status_403_count: 1" in captured.out


def test_fetch_artifact_contains_fetch_errors(tmp_path, monkeypatch) -> None:
    """Write structured fetch errors into the candidate artifact."""
    config_path = _write_config(tmp_path)
    output_path = tmp_path / "candidates.json"
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [],
            _summary(
                source_count=1,
                fetched_count=0,
                disabled_count=0,
                failed_count=1,
                total_bytes=0,
                errors=["safe"],
                error_records=[
                    FetchErrorRecord(
                        "fixture-source",
                        "http_error",
                        "Subscription source 'fixture-source' failed: HTTP 403.",
                        http_status=403,
                    )
                ],
            ),
        ),
    )

    exit_code = cli.main(["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(output_path)])

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert payload["fetch_errors"][0]["category"] == "http_error"
    assert payload["fetch_errors"][0]["http_status"] == 403


def test_fetch_output_excludes_secret_words_and_urls(tmp_path, capsys, monkeypatch) -> None:
    """Avoid printing secret-bearing or URL-bearing diagnostics."""
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [],
            _summary(
                source_count=1,
                fetched_count=0,
                disabled_count=0,
                failed_count=1,
                total_bytes=0,
                errors=["Subscription source 'fixture-source' failed: <REDACTED_URL> <REDACTED>"],
                error_records=[
                    FetchErrorRecord(
                        "fixture-source",
                        "url_error",
                        "Subscription source 'fixture-source' failed: <REDACTED_URL> <REDACTED>",
                    )
                ],
            ),
        ),
    )

    exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(tmp_path / "candidates.json")]
    )
    captured = capsys.readouterr()

    rendered = captured.out + captured.err
    assert exit_code == 2
    assert "https://" not in rendered
    assert "token=" not in rendered.lower()
    assert "password=" not in rendered.lower()


def test_fetch_passes_proxy_url_into_transport_options(tmp_path, capsys, monkeypatch) -> None:
    """Pass proxy transport options into the fetch layer."""
    config_path = _write_config(tmp_path)
    observed: dict[str, object] = {}

    def fake_fetch_enabled_subscriptions(sources, timeout_seconds, max_bytes, transport_options=None):
        observed["transport_options"] = transport_options
        return (
            [_fetched_subscription()],
            _summary(source_count=1, fetched_count=1, disabled_count=0, failed_count=0, total_bytes=120),
        )

    monkeypatch.setattr(cli, "fetch_enabled_subscriptions", fake_fetch_enabled_subscriptions)

    exit_code = cli.main(
        [
            "fetch",
            "--config",
            str(config_path),
            "--output",
            str(tmp_path / "candidates.json"),
            "--allow-network-fetch",
            "--proxy-url",
            "http://127.0.0.1:7890",
        ]
    )
    capsys.readouterr()

    assert exit_code == 0
    assert isinstance(observed["transport_options"], FetchTransportOptions)
    assert observed["transport_options"].proxy_url == "http://127.0.0.1:7890"


def test_fetch_passes_explicit_user_agent_into_fetch_layer(tmp_path, capsys, monkeypatch) -> None:
    """Pass the CLI User-Agent override into the fetch layer."""
    config_path = _write_config(tmp_path)
    observed: dict[str, object] = {}

    def fake_fetch_enabled_subscriptions(
        sources,
        timeout_seconds,
        max_bytes,
        transport_options=None,
        user_agent=None,
    ):
        observed["user_agent"] = user_agent
        return (
            [_fetched_subscription()],
            _summary(source_count=1, fetched_count=1, disabled_count=0, failed_count=0, total_bytes=120),
        )

    monkeypatch.setattr(cli, "fetch_enabled_subscriptions", fake_fetch_enabled_subscriptions)

    exit_code = cli.main(
        [
            "fetch",
            "--config",
            str(config_path),
            "--output",
            str(tmp_path / "candidates.json"),
            "--allow-network-fetch",
            "--user-agent",
            "Clash.Meta",
        ]
    )
    capsys.readouterr()

    assert exit_code == 0
    assert observed["user_agent"] == "Clash.Meta"


def test_fetch_rejects_user_agent_with_newline(tmp_path, capsys) -> None:
    """Reject newline-bearing User-Agent overrides."""
    config_path = _write_config(tmp_path)

    exit_code = cli.main(
        [
            "fetch",
            "--config",
            str(config_path),
            "--allow-network-fetch",
            "--user-agent",
            "Clash.Meta\nBad",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "User-Agent must not contain newlines" in captured.err


def test_fetch_output_does_not_print_user_agent(tmp_path, capsys, monkeypatch) -> None:
    """Keep the explicit User-Agent out of CLI output."""
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes, transport_options=None, user_agent=None: (
            [_fetched_clash_yaml_subscription()],
            _summary(source_count=1, fetched_count=1, disabled_count=0, failed_count=0, total_bytes=240),
        ),
    )

    exit_code = cli.main(
        [
            "fetch",
            "--config",
            str(config_path),
            "--allow-network-fetch",
            "--output",
            str(tmp_path / "candidates.json"),
            "--user-agent",
            "Clash.Meta",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Clash.Meta" not in (captured.out + captured.err)


def test_fetch_clash_yaml_output_contains_vless_candidate_without_unsupported_url(tmp_path, monkeypatch) -> None:
    """Parse Clash YAML subscriptions without misreading health-check URLs."""
    config_path = _write_config(tmp_path)
    output_path = tmp_path / "candidates.json"
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes, transport_options=None, user_agent=None: (
            [_fetched_clash_yaml_subscription()],
            _summary(source_count=1, fetched_count=1, disabled_count=0, failed_count=0, total_bytes=240),
        ),
    )

    exit_code = cli.main(
        ["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(output_path)]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["parsed_count"] == 1
    assert payload["unsupported_count"] == 0
    assert payload["candidates"][0]["protocol"] == "vless"
    assert payload["candidates"][0]["raw_name"] == "Test VLESS Reality"
    assert "unsupported-url" not in json.dumps(payload)
    assert "http://www.gstatic.com/generate_204" not in json.dumps(payload)


def test_fetch_rejects_invalid_proxy_url_without_echoing_it(tmp_path, capsys) -> None:
    """Reject unsupported proxy URLs without printing them."""
    config_path = _write_config(tmp_path)
    proxy_url = "socks5://user:pass@example.invalid:1080"

    exit_code = cli.main(
        [
            "fetch",
            "--config",
            str(config_path),
            "--allow-network-fetch",
            "--proxy-url",
            proxy_url,
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "proxy URL must use http or https" in captured.err
    assert proxy_url not in (captured.out + captured.err)


def test_fetch_output_does_not_include_proxy_url(tmp_path, capsys, monkeypatch) -> None:
    """Keep proxy URLs out of CLI output."""
    config_path = _write_config(tmp_path)
    proxy_url = "http://oreo:oreo@127.0.0.1:10089"
    monkeypatch.setattr(
        cli,
        "fetch_enabled_subscriptions",
        lambda sources, timeout_seconds, max_bytes, transport_options=None: (
            [],
            _summary(source_count=1, fetched_count=0, disabled_count=0, failed_count=0, total_bytes=0),
        ),
    )

    exit_code = cli.main(
        [
            "fetch",
            "--config",
            str(config_path),
            "--allow-network-fetch",
            "--proxy-url",
            proxy_url,
            "--output",
            str(tmp_path / "candidates.json"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert proxy_url not in (captured.out + captured.err)


def test_fetch_still_requires_network_opt_in_even_with_proxy_url(tmp_path, capsys, monkeypatch) -> None:
    """Keep the explicit fetch opt-in gate in place even when a proxy is provided."""
    config_path = _write_config(tmp_path)
    called = {"fetch": False}

    def fake_fetch(*args, **kwargs):
        called["fetch"] = True
        raise AssertionError("fetch should not run without opt-in")

    monkeypatch.setattr(cli, "fetch_enabled_subscriptions", fake_fetch)

    exit_code = cli.main(
        [
            "fetch",
            "--config",
            str(config_path),
            "--proxy-url",
            "http://127.0.0.1:7890",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "--allow-network-fetch" in captured.err
    assert called["fetch"] is False


def _summary(
    *,
    source_count: int,
    fetched_count: int,
    disabled_count: int,
    failed_count: int,
    total_bytes: int,
    errors: list[str] | None = None,
    error_records: list[FetchErrorRecord] | None = None,
) -> FetchSummary:
    """Build one FetchSummary with explicit defaults for tests."""
    return FetchSummary(
        source_count=source_count,
        fetched_count=fetched_count,
        disabled_count=disabled_count,
        failed_count=failed_count,
        total_bytes=total_bytes,
        errors=errors or [],
        error_records=error_records or [],
    )


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


def _fetched_clash_yaml_subscription() -> FetchedSubscription:
    """Build one fetched Clash YAML payload with a health-check URL."""
    content = """
proxies:
  - name: "Test VLESS Reality"
    type: vless
    server: example.invalid
    port: 443
    uuid: "00000000-0000-0000-0000-000000000000"
    network: tcp
    tls: true
    reality-opts:
      public-key: PUBLIC_KEY_PLACEHOLDER
      short-id: SHORT_ID_PLACEHOLDER
    servername: www.cloudflare.com
    client-fingerprint: chrome
proxy-groups:
  - name: Auto
    type: url-test
    proxies:
      - Test VLESS Reality
    url: http://www.gstatic.com/generate_204
    interval: 300
""".strip()
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
    """Build one probe artifact summary for compatibility tests."""
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
