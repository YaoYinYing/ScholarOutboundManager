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
    assert "vless, trojan, shadowsocks, and vmess by default" in readme_text.lower()
    assert "hysteria2 through the xray backend is experimental and disabled by default" in readme_text.lower()
    assert "unsupported protocols such as tuic and wireguard" in readme_text.lower()
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
    assert "redacted human-readable labels" in readme_text.lower()
    assert "region hints are heuristic" in readme_text.lower()
    assert "use `candidate_id` for stable selection" in readme_text.lower()
    assert "artifact consistency" in readme_text.lower()
    assert "artifact check" in readme_text.lower()
    assert "artifact explain-probe" in readme_text.lower()
    assert "candidate_id belongs to the artifact run" in readme_text.lower()
    assert "redacted but human-readable candidate labels first" in readme_text.lower()
    assert "switching selected sidecar candidate" in readme_text.lower()
    assert "--skip-xray-binary-copy" in readme_text
    assert "service-restart" in readme_text.lower()
    assert "region hint selection" in readme_text.lower()
    assert "it is not geoip" in readme_text.lower()
    assert "single-xray multi-port sidecar pool" in readme_text.lower()
    assert "sidecar pool plan" in readme_text.lower()
    assert "sidecar pool check-ports" in readme_text.lower()
    assert "sidecar pool stage" in readme_text.lower()
    assert "sidecar pool validate" in readme_text.lower()
    assert "sidecar pool snippets" in readme_text.lower()
    assert "one xray process with multiple localhost socks ports" in readme_text.lower()
    assert "geo-aware selection" in readme_text.lower()
    assert "geo-nearest candidate from local cache" in readme_text.lower()
    assert "geo db, host geo cache, and candidate geo cache are separate layers" in readme_text.lower()
    assert "select never performs network lookup" in readme_text.lower()
    assert "select never downloads a geo db" in readme_text.lower()
    assert "geo refresh-plan" in readme_text.lower()
    assert "dry-run only in this phase" in readme_text.lower()
    assert "raw egress ip values should not be stored by default" in readme_text.lower()
    assert "state_data/geo/db/geolite2-city.mmdb" in readme_text.lower()
    assert "geo cache-inspect" in readme_text.lower()
    assert "geo db-info" in readme_text.lower()
    assert "candidate server address does not necessarily equal the true egress ip" in readme_text.lower()
    assert "phase 23a only implements cached geo ranking" in readme_text.lower()
    assert "optional tui" in readme_text.lower()
    assert "scholar-outbound-manager-tui" in readme_text.lower()
    assert 'pip install "scholaroutboundmanager[tui]"' in readme_text.lower()
    assert "scholar-outbound-manager tui" in readme_text.lower()
    assert "internal textual widget ids are sanitized" in readme_text.lower()
    assert "tui workflow control plane" in readme_text.lower()
    assert "config edits are transactional" in readme_text.lower()
    assert "`config.yaml` is changed only after validation and save" in readme_text.lower()
    assert "undo is backed by a sensitive journal under `state_data/tui/`" in readme_text.lower()
    assert "network fetch/probe and systemd actions remain explicit operations" in readme_text.lower()
    assert "tabs are for operations" in readme_text.lower()
    assert "wizard is for first deployment or full refresh" in readme_text.lower()
    assert "mutating actions require confirmation" in readme_text.lower()
    assert "cli remains the source of truth" in readme_text.lower()
    assert "dashboard | preflight | fetch & probe | artifacts | selection | sidecar | pool | troubleshooting | snippets" in readme_text.lower()
    assert "selected_candidate.json" in readme_text.lower()
    assert "state_data/geo/" in readme_text.lower()
    assert "web panel security model" in readme_text.lower()
    assert 'pip install "scholaroutboundmanager[web]"' in readme_text.lower()
    assert "scholar-outbound-manager web user-init --username admin --password-stdin" in readme_text.lower()
    assert "scholar-outbound-manager web serve --host 127.0.0.1 --port 8790" in readme_text.lower()
    assert "default listen is `127.0.0.1` only" in readme_text.lower()
    assert "public bind is refused unless explicitly allowed" in readme_text.lower()
    assert "http is allowed only for localhost, intended for ssh forwarding" in readme_text.lower()
    assert "ssh tunnel or tailscale/reverse proxy with https" in readme_text.lower()
    assert "ssh -L 8790:127.0.0.1:8790 oreoz" in readme_text
    assert "password + totp" in readme_text.lower()
    assert "httponly" in readme_text.lower()
    assert "samesite=strict" in readme_text.lower()
    assert "secure" in readme_text.lower()
    assert "auth logs are fail2ban-friendly" in readme_text.lower()
    assert "somweb_auth event=(login_failed|totp_failed|csrf_failed|api_unauthorized)" in readme_text.lower()
    assert "root web user is forbidden" in readme_text.lower()
    assert "running the web panel as root is refused by default" in readme_text.lower()
    assert "web panel never displays raw sensitive artifacts" in readme_text.lower()
    assert "not a production xray/xrayr/`x-ui` editor" in readme_text.lower()
    assert "--parallel 4" in readme_text
    assert "--keep-all-passed" in readme_text
    assert "each worker starts its own managed xray runtime" in readme_text.lower()
    assert "hysteria2 support through xray" in readme_text.lower()
    assert "hysteria2 through xray is experimental" in readme_text.lower()
    assert "hysteria2 is disabled by default for production safety" in readme_text.lower()
    assert "--enable-experimental-hysteria2" in readme_text
    assert "xray names the outbound protocol `hysteria`" in readme_text.lower()
    assert "hysteria2 auth is written to `streamsettings.hysteriasettings.auth`" in readme_text.lower()
    assert "clash `sni` and `servername` are mapped to `streamsettings.tlssettings.servername`" in readme_text.lower()
    assert "clash `skip-cert-verify` is mapped to `streamsettings.tlssettings.allowinsecure`" in readme_text.lower()
    assert "obfs and obfs-password are preserved for review but remain fail-closed" in readme_text.lower()
    assert "xray outbound architecture" in readme_text.lower()
    assert "subscription adapters normalize external formats" in readme_text.lower()
    assert "xray outbound specs model protocol, transport, tls, reality, and hysteria" in readme_text.lower()
    assert "xray renderer emits official xray json" in readme_text.lower()
    assert "new protocol support should add a spec builder and renderer tests" in readme_text.lower()
    assert "do not patch xray json directly in parser code" in readme_text.lower()
    assert "do not silently ignore unmapped protocol fields" in readme_text.lower()
    assert "hysteria2 support follows xray's hysteria outbound plus hysteria transport structure" in readme_text.lower()
    assert "persistent ssl eof in live vps probe means transport-layer failure, not scholar blocking" in readme_text.lower()
    assert "hysteria2 cold-start transport retries" in readme_text.lower()
    assert "local socks readiness does not imply outbound hysteria2 readiness" in readme_text.lower()
    assert "transport retries run inside the same managed xray process" in readme_text.lower()
    assert "scholar blocks such as google_sorry, http 403, http 429, home-blocked, and query-blocked are not retried" in readme_text.lower()
    assert "artifact explain-probe" in readme_text.lower()
    assert "--protocol hysteria2" in readme_text.lower()
    assert "--error-category ssl_eof" in readme_text.lower()
    assert "experimental hysteria2 diagnosis" in readme_text.lower()
    assert "--transport-retry-count 2" in readme_text
    assert "--transport-retry-backoff 1.5" in readme_text
    assert "--hysteria2-warmup-attempts 1" in readme_text
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
