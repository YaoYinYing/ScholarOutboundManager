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
    assert "live a/b fetch smoke test" in readme_text.lower()
    assert "state_data/live_ab/" in readme_text
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


def test_config_example_keeps_network_probe_disabled_by_default() -> None:
    """Require the example config to keep live probing disabled by default."""
    example_text = (PROJECT_ROOT / "config.example.yaml").read_text(encoding="utf-8")

    assert "allow_network_probe: false" in example_text
