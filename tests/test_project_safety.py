"""Project-level documentation and ignore-rule safety tests."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_gitignore_exists() -> None:
    """Require the repository ignore file to exist."""
    assert (PROJECT_ROOT / ".gitignore").exists()


def test_gitignore_contains_required_sensitive_entries() -> None:
    """Require key local-sensitive ignore entries to remain present."""
    gitignore_text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    for entry in (
        ".runtime/",
        "generated/",
        "state_data/",
        "live_test_data/",
        "config.yaml",
        "config.local.yaml",
        "*.local.yaml",
        ".env",
        "*.log",
        ".venv/",
        "venv/",
        "candidates.json",
        "passed_candidates.json",
        "probe_summary.json",
    ):
        assert entry in gitignore_text


def test_readme_exists_and_documents_current_cli_chain() -> None:
    """Require the README to describe the current CLI workflow."""
    readme_text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "probe" in readme_text
    assert "fetch" in readme_text
    assert "inspect" in readme_text
    assert "generate" in readme_text
    assert "run" in readme_text
    assert "--allow-network-probe" in readme_text
    assert "--allow-network-fetch" in readme_text
    assert "--proxy-url" in readme_text
    assert "live a/b fetch smoke test" in readme_text.lower()
    assert "state_data/live_ab/" in readme_text
    assert "http(s) proxy" in readme_text.lower() or "http proxy" in readme_text.lower()
    assert "probe.allow_network_probe" in readme_text
    assert "required together" in readme_text.lower() or "without both" in readme_text.lower()
    assert "proberesult" in readme_text.lower() or "probe evidence" in readme_text.lower()
    assert "can consume plain candidates json" in readme_text.lower()
    assert "passed-candidates artifacts" in readme_text.lower()
    assert "download subscription content" in readme_text.lower()
    assert "does not probe scholar" in readme_text.lower()
    assert "sensitive" in readme_text.lower()
    assert "credentials" in readme_text.lower()
    assert "must not be committed" in readme_text.lower()
    assert "clash-compatible yaml" in readme_text.lower()
    assert "--user-agent" in readme_text
    assert "runtime backend direction" in readme_text.lower()
    assert "top-level `proxies` list" in readme_text
    assert "checksum-aware" in readme_text.lower()
    assert "vless, trojan, shadowsocks, and vmess" in readme_text.lower()
    assert "hysteria2, tuic, and wireguard" in readme_text.lower()
    assert "xray binary preparation" in readme_text.lower()
    assert "xray inspect --path" in readme_text.lower()
    assert "xray install" in readme_text.lower()
    assert ".runtime/xray/xray" in readme_text
    assert "does not silently download xray" in readme_text.lower()
    assert "sidecar socks runtime model" in readme_text.lower()
    assert "production systemd sidecar" in readme_text.lower()
    assert "sidecar service-stage" in readme_text
    assert "sidecar service-install" in readme_text
    assert "sidecar service-start" in readme_text
    assert "sidecar service-enable" in readme_text
    assert "sidecar service-status" in readme_text
    assert "sidecar service-validate" in readme_text
    assert "sidecar service-stop" in readme_text
    assert "sidecar service-disable" in readme_text
    assert "sidecar service-snippet" in readme_text
    assert "select choose" in readme_text.lower()
    assert "select list" in readme_text.lower()
    assert "select explain" in readme_text.lower()
    assert "single-xray multi-port sidecar pool" in readme_text.lower()
    assert "sidecar pool plan" in readme_text.lower()
    assert "sidecar pool check-ports" in readme_text.lower()
    assert "sidecar pool stage" in readme_text.lower()
    assert "sidecar pool validate" in readme_text.lower()
    assert "sidecar pool snippets" in readme_text.lower()
    assert "one xray process with multiple localhost socks ports" in readme_text.lower()
    assert "geo-aware selection" in readme_text.lower()
    assert "geo-nearest candidate from local cache" in readme_text.lower()
    assert "candidate server address does not necessarily equal the true egress ip" in readme_text.lower()
    assert "phase 23a only implements cached geo ranking" in readme_text.lower()
    assert "optional tui" in readme_text.lower()
    assert "scholar-outbound-manager-tui" in readme_text.lower()
    assert 'pip install "scholaroutboundmanager[tui]"' in readme_text.lower()
    assert "selected_candidate.json" in readme_text.lower()
    assert "state_data/geo/" in readme_text.lower()
    assert "--parallel 4" in readme_text
    assert "--keep-all-passed" in readme_text
    assert "each worker starts its own managed xray runtime" in readme_text.lower()
    assert "legacy offline fragment export" in readme_text.lower()
    assert "not the recommended production workflow" in readme_text.lower()
    assert "does not mutate production xray" in readme_text.lower() or "does not modify production xray" in readme_text.lower()
    assert "manual downstream step" in readme_text.lower()
    assert "systemd" in readme_text.lower()
    assert "dedicated user" in readme_text.lower()
    assert "does not modify production xray" in readme_text.lower() or "does not modify production xrayr" in readme_text.lower()
    assert "does not kill external xray processes" in readme_text.lower()
    assert "docker is not the default lifecycle manager" in readme_text.lower()
    assert "do not use `killall xray`" in readme_text.lower()
    assert "do not use `pkill xray`" in readme_text.lower()
    assert "step 5: generate xray fragments from passed candidates" not in readme_text.lower()


def test_security_doc_exists_and_warns_about_sensitive_material() -> None:
    """Require the security document to warn about credential-bearing artifacts."""
    security_doc = PROJECT_ROOT / "docs" / "security.md"
    security_text = security_doc.read_text(encoding="utf-8")

    assert security_doc.exists()
    assert "--allow-network-probe" in security_text
    assert "probe.allow_network_probe" in security_text
    assert "two-key" in security_text.lower() or "two key" in security_text.lower() or "dual" in security_text.lower()
    assert "vless://" in security_text
    assert "UUID" in security_text
    assert "public key" in security_text
    assert "passed_candidates" in security_text
    assert "config.yaml" in security_text
    assert "must not be committed" in security_text.lower()
    assert "/etc/scholar-outbound-manager/" in security_text
    assert "production xray" in security_text.lower()
    assert "not managed by this project" in security_text.lower()
    assert "generated xray fragments are legacy offline exports" in security_text.lower()


def test_config_example_keeps_network_probe_disabled_by_default() -> None:
    """Require the example config to keep live probing disabled by default."""
    example_text = (PROJECT_ROOT / "config.example.yaml").read_text(encoding="utf-8")

    assert "allow_network_probe: false" in example_text
