"""Tests for the explicit Xray CLI commands."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager import cli


def test_xray_inspect_missing_path_returns_one(tmp_path, capsys) -> None:
    """Return 1 when the binary path does not exist."""
    exit_code = cli.main(["xray", "inspect", "--path", str(tmp_path / "missing-xray")])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "exists: false" in captured.out


def test_xray_inspect_fake_executable_returns_zero(tmp_path, capsys) -> None:
    """Inspect a fake executable and report success."""
    binary_path = tmp_path / "xray"
    binary_path.write_text("#!/bin/sh\nprintf 'Xray 1.2.3\\n'\n", encoding="utf-8")
    binary_path.chmod(0o755)

    exit_code = cli.main(["xray", "inspect", "--path", str(binary_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "executable: true" in captured.out
    assert "version: Xray 1.2.3" in captured.out


def test_xray_install_without_allow_download_returns_one_and_does_not_call_installer(
    tmp_path, capsys, monkeypatch
) -> None:
    """Keep download opt-in explicit."""
    called = {"installer": False}

    def fake_install_xray_binary(*args, **kwargs):
        called["installer"] = True
        raise AssertionError("installer should not be called")

    monkeypatch.setattr(cli, "install_xray_binary", fake_install_xray_binary)

    exit_code = cli.main(["xray", "install", "--install-dir", str(tmp_path / "runtime")])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "--allow-download" in captured.err
    assert called["installer"] is False


def test_xray_install_with_allow_download_can_be_monkeypatched_to_success(tmp_path, capsys, monkeypatch) -> None:
    """Allow the install command to succeed through a fake installer."""
    observed: dict[str, object] = {}

    def fake_install_xray_binary(version, install_dir, *, allow_download, platform_asset=None, downloader=None):
        observed["version"] = version
        observed["install_dir"] = install_dir
        observed["allow_download"] = allow_download
        observed["platform_asset"] = platform_asset
        from scholar_outbound_manager.xray.binary import XrayInstallResult

        return XrayInstallResult(
            binary_path=str(Path(install_dir) / "xray"),
            version="Xray 1.2.3",
            downloaded=True,
            installed=True,
            error=None,
        )

    monkeypatch.setattr(cli, "install_xray_binary", fake_install_xray_binary)

    exit_code = cli.main(
        [
            "xray",
            "install",
            "--install-dir",
            str(tmp_path / "runtime"),
            "--version",
            "v26.5.9",
            "--allow-download",
            "--os",
            "Linux",
            "--arch",
            "x86_64",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert observed["version"] == "v26.5.9"
    assert observed["allow_download"] is True
    assert "Installed Xray binary." in captured.out


def test_xray_install_output_does_not_contain_download_url(tmp_path, capsys, monkeypatch) -> None:
    """Keep download URLs out of CLI output."""
    def fake_install_xray_binary(version, install_dir, *, allow_download, platform_asset=None, downloader=None):
        from scholar_outbound_manager.xray.binary import XrayInstallResult

        return XrayInstallResult(
            binary_path=str(Path(install_dir) / "xray"),
            version="Xray 1.2.3",
            downloaded=True,
            installed=True,
            error=None,
        )

    monkeypatch.setattr(cli, "install_xray_binary", fake_install_xray_binary)

    exit_code = cli.main(
        ["xray", "install", "--install-dir", str(tmp_path / "runtime"), "--allow-download"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "https://github.com/XTLS/Xray-core" not in (captured.out + captured.err)


def test_xray_install_does_not_modify_config_yaml(tmp_path, capsys, monkeypatch) -> None:
    """Do not mutate config.yaml during install."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("xray:\n  binary_path: fake-xray\n", encoding="utf-8")

    def fake_install_xray_binary(version, install_dir, *, allow_download, platform_asset=None, downloader=None):
        from scholar_outbound_manager.xray.binary import XrayInstallResult

        return XrayInstallResult(
            binary_path=str(Path(install_dir) / "xray"),
            version="Xray 1.2.3",
            downloaded=True,
            installed=True,
            error=None,
        )

    monkeypatch.setattr(cli, "install_xray_binary", fake_install_xray_binary)

    exit_code = cli.main(
        ["xray", "install", "--install-dir", str(tmp_path / "runtime"), "--allow-download"]
    )
    capsys.readouterr()

    assert exit_code == 0
    assert config_path.read_text(encoding="utf-8") == "xray:\n  binary_path: fake-xray\n"


def test_existing_subcommands_remain_available_after_xray_addition(tmp_path, capsys, monkeypatch) -> None:
    """Keep the existing command surface available."""
    config_path = _write_config(tmp_path, allow_network_probe=True)
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(
        '{"candidates":[{"source_name":"fixture","raw_name":"node","protocol":"vless","address":"example.invalid","port":443,"user_id":"00000000-0000-0000-0000-000000000000","security":"reality","server_name":"www.cloudflare.com","public_key":"PUBLIC_KEY_PLACEHOLDER","supported":true}]}',
        encoding="utf-8",
    )
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

    assert cli.main(["fetch", "--config", str(config_path), "--allow-network-fetch", "--output", str(tmp_path / "fetched.json")]) == 0
    capsys.readouterr()
    assert cli.main(["environment"]) == 0
    capsys.readouterr()
    assert cli.main(["probe", "--config", str(config_path), "--candidates", str(candidates_path), "--allow-network-probe"]) == 0
    capsys.readouterr()
    assert cli.main(["generate", "--config", str(config_path), "--candidates", str(candidates_path)]) == 0
    capsys.readouterr()
    assert cli.main(["run", "--config", str(config_path), "--candidates", str(candidates_path)]) == 0
    capsys.readouterr()


def test_xray_cli_output_does_not_contain_token_secret_or_password(tmp_path, capsys, monkeypatch) -> None:
    """Keep Xray CLI output free of obvious secret words."""
    def fake_install_xray_binary(version, install_dir, *, allow_download, platform_asset=None, downloader=None):
        from scholar_outbound_manager.xray.binary import XrayInstallResult

        return XrayInstallResult(
            binary_path=str(Path(install_dir) / "xray"),
            version="Xray 1.2.3",
            downloaded=True,
            installed=True,
            error=None,
        )

    monkeypatch.setattr(cli, "install_xray_binary", fake_install_xray_binary)

    exit_code = cli.main(
        ["xray", "install", "--install-dir", str(tmp_path / "runtime"), "--allow-download"]
    )
    captured = capsys.readouterr()

    rendered = (captured.out + captured.err).lower()
    assert exit_code == 0
    assert "token=" not in rendered
    assert "secret=" not in rendered
    assert "password=" not in rendered


def _write_config(tmp_path: Path, *, allow_network_probe: bool) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "subscriptions:",
                '  - name: "fixture-source"',
                '    url: "https://example.invalid/subscription"',
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


def _summary(*, source_count: int, fetched_count: int, disabled_count: int, failed_count: int, total_bytes: int):
    from scholar_outbound_manager.fetcher import FetchSummary

    return FetchSummary(
        source_count=source_count,
        fetched_count=fetched_count,
        disabled_count=disabled_count,
        failed_count=failed_count,
        total_bytes=total_bytes,
        errors=[],
        error_records=[],
    )


def _fetched_subscription():
    from scholar_outbound_manager.fetcher import FetchedSubscription

    content = (
        "vless://00000000-0000-0000-0000-000000000000@example.invalid:443"
        "?security=reality&pbk=PUBLIC_KEY_PLACEHOLDER&sni=www.cloudflare.com#US%20Scholar%20IPv4"
    )
    return FetchedSubscription(source_name="fixture-source", content=content, byte_count=len(content))


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
