"""Tests for local-only runtime environment inspection."""

from __future__ import annotations

from scholar_outbound_manager.environment import format_runtime_environment_inspection
from scholar_outbound_manager.environment import inspect_runtime_environment


def test_inspect_runtime_environment_detects_proxy_env_names_without_values(monkeypatch) -> None:
    """Return proxy variable names without exposing their values."""
    monkeypatch.setenv("HTTPS_PROXY", "http://oreo:oreo@127.0.0.1:10089")

    inspection = inspect_runtime_environment()

    assert inspection.system_proxy_detected is True
    assert inspection.proxy_env_vars == ["HTTPS_PROXY"]
    rendered = format_runtime_environment_inspection(inspection)
    assert "http://oreo:oreo@127.0.0.1:10089" not in rendered


def test_inspect_runtime_environment_linux_without_proxy_is_vps_candidate(monkeypatch) -> None:
    """Treat Linux without proxy env as a VPS-candidate hint."""
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    monkeypatch.setattr("scholar_outbound_manager.environment.sys.platform", "linux")

    inspection = inspect_runtime_environment()

    assert inspection.trust_level == "vps_candidate"
    assert inspection.system_proxy_detected is False


def test_inspect_runtime_environment_darwin_warns_about_tun(monkeypatch) -> None:
    """Treat Darwin as development-only because TUN isolation cannot be proven locally."""
    monkeypatch.setattr("scholar_outbound_manager.environment.sys.platform", "darwin")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)

    inspection = inspect_runtime_environment()

    assert inspection.trust_level == "development_only"
    assert inspection.tun_hint_detected is True
    assert any("VPS" in warning for warning in inspection.warnings)


def test_format_runtime_environment_inspection_excludes_proxy_url(monkeypatch) -> None:
    """Never print proxy URL values in the environment formatter."""
    monkeypatch.setenv("HTTPS_PROXY", "http://oreo:oreo@127.0.0.1:10089")

    rendered = format_runtime_environment_inspection(inspect_runtime_environment())

    assert "http://oreo:oreo@127.0.0.1:10089" not in rendered
    assert "HTTPS_PROXY" in rendered
