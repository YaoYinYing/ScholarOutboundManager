"""Tests for transactional TUI config editor helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scholar_outbound_manager.tui import config_editor


def test_load_config_draft_reads_config_text(tmp_path: Path) -> None:
    """Load the on-disk config text into the draft."""
    config_path = _write_valid_config(tmp_path, subscription_url="https://example.invalid/subscription")

    draft = config_editor.load_config_draft(config_path)

    assert draft.path == str(config_path)
    assert "subscriptions:" in draft.original_text
    assert draft.current_text == draft.original_text


def test_redacted_config_preview_hides_subscription_url(tmp_path: Path) -> None:
    """Never render subscription URLs into the TUI preview."""
    config_path = _write_valid_config(tmp_path, subscription_url="https://example.invalid/subscription-token")

    draft = config_editor.load_config_draft(config_path)

    assert "https://example.invalid/subscription-token" not in draft.redacted_preview
    assert "<REDACTED_URL>" in draft.redacted_preview


def test_redacted_config_preview_hides_password_auth_token_and_uuid() -> None:
    """Hide common secret fields from redacted preview output."""
    preview = config_editor.build_redacted_config_preview(
        "\n".join(
            [
                'password: "PASSWORD_PLACEHOLDER"',
                'auth: "AUTH_SECRET"',
                'token: "TOKEN_VALUE"',
                'public_key: "PUBLIC_KEY_PLACEHOLDER"',
                'server_name: "example.invalid"',
                'server: "1.2.3.4"',
                "uuid: 00000000-0000-0000-0000-000000000000",
            ]
        )
    )

    assert "PASSWORD_PLACEHOLDER" not in preview
    assert "AUTH_SECRET" not in preview
    assert "TOKEN_VALUE" not in preview
    assert "PUBLIC_KEY_PLACEHOLDER" not in preview
    assert "example.invalid" not in preview
    assert "1.2.3.4" not in preview
    assert "00000000-0000-0000-0000-000000000000" not in preview


def test_redacted_config_preview_hides_secret_like_header_keys() -> None:
    """Hide common secret-bearing header and token keys from preview output."""
    preview = config_editor.build_redacted_config_preview(
        "\n".join(
            [
                "subscriptions:",
                "  - headers:",
                '      Authorization: "Bearer super-secret"',
                '      Cookie: "sessionid=super-secret"',
                '      X-Api-Key: "api-key-secret"',
                '      access_token: "access-token-secret"',
                "probe:",
                "  concurrency: 2",
            ]
        )
    )

    assert "Bearer super-secret" not in preview
    assert "sessionid=super-secret" not in preview
    assert "api-key-secret" not in preview
    assert "access-token-secret" not in preview
    assert "concurrency: 2" in preview


def test_build_config_diff_redacts_secrets() -> None:
    """Redacted diff must not leak changed secret values."""
    diff = config_editor.build_config_diff(
        'url: "https://example.invalid/old-token"\npassword: oldsecret\n',
        'url: "https://example.invalid/new-token"\npassword: newsecret\n',
    )

    assert "old-token" not in diff
    assert "new-token" not in diff
    assert "oldsecret" not in diff
    assert "newsecret" not in diff


def test_build_config_diff_redacts_changed_header_and_token_values() -> None:
    """Redacted diff must hide changed Authorization, Cookie, and access-token values."""
    diff = config_editor.build_config_diff(
        "\n".join(
            [
                "subscriptions:",
                "  - headers:",
                '      Authorization: "Bearer old-secret"',
                '      Cookie: "sessionid=old-secret"',
                '      access_token: "old-token-value"',
            ]
        )
        + "\n",
        "\n".join(
            [
                "subscriptions:",
                "  - headers:",
                '      Authorization: "Bearer new-secret"',
                '      Cookie: "sessionid=new-secret"',
                '      access_token: "new-token-value"',
            ]
        )
        + "\n",
    )

    assert "old-secret" not in diff
    assert "new-secret" not in diff
    assert "old-token-value" not in diff
    assert "new-token-value" not in diff


def test_save_config_draft_validates_before_writing(tmp_path: Path) -> None:
    """Reject invalid config before touching the file."""
    config_path = _write_valid_config(tmp_path)
    draft = config_editor.update_config_draft_text(
        config_editor.load_config_draft(config_path),
        "subscriptions: [\n",
    )

    with pytest.raises(ValueError, match="invalid"):
        config_editor.save_config_draft(draft, undo_journal_path=tmp_path / "undo.jsonl")

    assert "subscriptions:" in config_path.read_text(encoding="utf-8")
    assert not (tmp_path / "undo.jsonl").exists()


def test_save_config_draft_writes_atomically_and_creates_undo_journal(tmp_path: Path) -> None:
    """Persist the new config and append one sensitive undo entry."""
    config_path = _write_valid_config(tmp_path)
    undo_path = tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl"
    original_text = config_path.read_text(encoding="utf-8")
    updated_text = original_text.replace("allow_network_probe: false", "allow_network_probe: true")
    draft = config_editor.update_config_draft_text(config_editor.load_config_draft(config_path), updated_text)

    result = config_editor.save_config_draft(draft, undo_journal_path=undo_path)

    assert result.saved is True
    assert "allow_network_probe: true" in config_path.read_text(encoding="utf-8")
    assert not list(config_path.parent.glob(f".{config_path.name}.*.tmp"))
    journal_lines = undo_path.read_text(encoding="utf-8").splitlines()
    assert len(journal_lines) == 1
    entry = json.loads(journal_lines[0])
    assert entry["config_path"] == str(config_path)
    assert entry["previous_text"] == original_text
    assert entry["reason"] == "tui_config_save"


def test_undo_last_config_save_restores_previous_config(tmp_path: Path) -> None:
    """Restore the saved previous config through the undo journal."""
    config_path = _write_valid_config(tmp_path)
    undo_path = tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl"
    original_text = config_path.read_text(encoding="utf-8")
    modified_text = original_text.replace("allow_network_probe: false", "allow_network_probe: true")
    config_editor.save_config_draft(
        config_editor.update_config_draft_text(config_editor.load_config_draft(config_path), modified_text),
        undo_journal_path=undo_path,
    )

    result = config_editor.undo_last_config_save(config_path=config_path, undo_journal_path=undo_path)

    assert result.restored is True
    assert config_path.read_text(encoding="utf-8") == original_text
    assert result.path == str(config_path)


def test_undo_last_config_save_supports_multi_step_stack(tmp_path: Path) -> None:
    """Repeated undo should walk back through matching saved states."""
    config_path = _write_valid_config(tmp_path)
    undo_path = tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl"
    original_text = config_path.read_text(encoding="utf-8")
    first_text = original_text.replace("allow_network_probe: false", "allow_network_probe: true")
    second_text = first_text.replace("concurrency: 1", "concurrency: 2")
    config_editor.save_config_draft(
        config_editor.update_config_draft_text(config_editor.load_config_draft(config_path), first_text),
        undo_journal_path=undo_path,
    )
    config_editor.save_config_draft(
        config_editor.update_config_draft_text(config_editor.load_config_draft(config_path), second_text),
        undo_journal_path=undo_path,
    )

    assert config_editor.has_undo_journal_entry(config_path=config_path, undo_journal_path=undo_path) is True

    first = config_editor.undo_last_config_save(config_path=config_path, undo_journal_path=undo_path)
    assert first.restored is True
    assert config_path.read_text(encoding="utf-8") == first_text
    assert config_editor.has_undo_journal_entry(config_path=config_path, undo_journal_path=undo_path) is True

    second = config_editor.undo_last_config_save(config_path=config_path, undo_journal_path=undo_path)
    assert second.restored is True
    assert config_path.read_text(encoding="utf-8") == original_text
    assert config_editor.has_undo_journal_entry(config_path=config_path, undo_journal_path=undo_path) is False


def test_has_undo_journal_entry_tracks_availability(tmp_path: Path) -> None:
    """Report whether one config has undo history available."""
    config_path = _write_valid_config(tmp_path)
    undo_path = tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl"
    assert config_editor.has_undo_journal_entry(config_path=config_path, undo_journal_path=undo_path) is False

    updated_text = config_path.read_text(encoding="utf-8").replace("allow_network_probe: false", "allow_network_probe: true")
    config_editor.save_config_draft(
        config_editor.update_config_draft_text(config_editor.load_config_draft(config_path), updated_text),
        undo_journal_path=undo_path,
    )

    assert config_editor.has_undo_journal_entry(config_path=config_path, undo_journal_path=undo_path) is True


def test_has_undo_journal_entry_ignores_stale_save_entries(tmp_path: Path) -> None:
    """Undo availability should ignore save rows that do not match the current config hash."""
    config_path = _write_valid_config(tmp_path)
    undo_path = tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl"
    undo_path.parent.mkdir(parents=True, exist_ok=True)
    undo_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-06-02T00:00:00Z",
                "config_path": str(config_path),
                "previous_sha256": "a",
                "next_sha256": "not-the-current-sha",
                "previous_text": "subscriptions: []\n",
                "next_redacted_summary": "subscriptions: []",
                "reason": "tui_config_save",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert config_editor.has_undo_journal_entry(config_path=config_path, undo_journal_path=undo_path) is False
    with pytest.raises(ValueError, match="current config state"):
        config_editor.undo_last_config_save(config_path=config_path, undo_journal_path=undo_path)


def test_legacy_save_entry_without_next_sha256_is_ignored(tmp_path: Path) -> None:
    """Legacy journal rows without next_sha256 should not crash or count as undoable."""
    config_path = _write_valid_config(tmp_path)
    undo_path = tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl"
    undo_path.parent.mkdir(parents=True, exist_ok=True)
    undo_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-06-02T00:00:00Z",
                "config_path": str(config_path),
                "previous_sha256": "a",
                "previous_text": "subscriptions: []\n",
                "next_redacted_summary": "subscriptions: []",
                "reason": "tui_config_save",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert config_editor.has_undo_journal_entry(config_path=config_path, undo_journal_path=undo_path) is False
    with pytest.raises(ValueError, match="current config state"):
        config_editor.undo_last_config_save(config_path=config_path, undo_journal_path=undo_path)


def test_has_undo_journal_entry_ignores_pure_undo_audit_entries(tmp_path: Path) -> None:
    """Undo availability should depend on save entries, not audit-only undo rows."""
    config_path = _write_valid_config(tmp_path)
    undo_path = tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl"
    undo_path.parent.mkdir(parents=True, exist_ok=True)
    undo_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-06-02T00:00:00Z",
                "config_path": str(config_path),
                "previous_sha256": "a",
                "next_sha256": "b",
                "previous_text": "subscriptions: []\n",
                "next_redacted_summary": "subscriptions: []",
                "reason": "tui_config_undo",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert config_editor.has_undo_journal_entry(config_path=config_path, undo_journal_path=undo_path) is False


def _write_valid_config(tmp_path: Path, *, subscription_url: str = "https://example.invalid/subscription") -> Path:
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
                "  allow_network_probe: false",
                "xray:",
                '  binary_path: "/usr/local/bin/xray"',
                f'  runtime_dir: "{tmp_path / ".runtime"}"',
                '  local_socks_host: "127.0.0.1"',
                "  local_socks_port: 1081",
                "output:",
                '  outbounds_path: "generated/outbounds.json"',
                '  routes_path: "generated/routes.json"',
                '  manifest_path: "generated/manifest.json"',
                '  history_dir: "state_data/history"',
                "generation:",
                '  tag_prefix: "google-scholar-node-"',
                "  max_passed_nodes: 2",
                '  fallback_blackhole_tag: "blocked-scholar"',
                "  previous_output_max_age_hours: 24",
                "routing:",
                '  mode: "dedicated_inbound"',
                "  inbound_tags:",
                '    - "scholar-in"',
                "  fail_closed: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path
