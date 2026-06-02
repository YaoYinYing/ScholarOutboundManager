"""Tests for structured TUI config form helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from scholar_outbound_manager.tui import config_editor
from scholar_outbound_manager.tui.config_form import apply_config_form_patch
from scholar_outbound_manager.tui.config_form import build_config_form_state
from scholar_outbound_manager.tui.config_form import build_config_patch_from_field_update


def test_build_config_form_state_lists_safe_fields_only(tmp_path: Path) -> None:
    config_path = _write_valid_config(tmp_path)

    state = build_config_form_state(config_path)
    keys = {field.key for field in state.fields}

    assert "probe.concurrency" in keys
    assert "xray.binary_path" in keys
    assert "routing.fail_closed" in keys
    assert "subscriptions.0.url" not in keys
    assert "password" not in keys


def test_apply_config_form_patch_updates_probe_concurrency(tmp_path: Path) -> None:
    config_path = _write_valid_config(tmp_path)

    result = apply_config_form_patch(
        config_path,
        build_config_patch_from_field_update("probe.concurrency", 4),
        undo_journal_path=tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl",
    )

    assert result.saved is True
    assert "concurrency: 4" in config_path.read_text(encoding="utf-8")


def test_invalid_patch_refuses_save(tmp_path: Path) -> None:
    config_path = _write_valid_config(tmp_path)

    with pytest.raises(ValueError, match="invalid"):
        apply_config_form_patch(
            config_path,
            build_config_patch_from_field_update("probe.concurrency", "bad"),
            undo_journal_path=tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl",
        )

    assert "concurrency: 1" in config_path.read_text(encoding="utf-8")


def test_unrelated_config_keys_survive_patch(tmp_path: Path) -> None:
    config_path = _write_valid_config(tmp_path)

    apply_config_form_patch(
        config_path,
        build_config_patch_from_field_update("routing.fail_closed", False),
        undo_journal_path=tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl",
    )

    text = config_path.read_text(encoding="utf-8")
    assert "tag_prefix: google-scholar-node-" in text
    assert "fallback_blackhole_tag: blocked-scholar" in text


def test_redacted_diff_hides_secret_values(tmp_path: Path) -> None:
    config_path = _write_valid_config(tmp_path, subscription_url="https://example.invalid/subscription-token")
    original_text = config_path.read_text(encoding="utf-8")

    result = apply_config_form_patch(
        config_path,
        build_config_patch_from_field_update("xray.binary_path", "/opt/xray"),
        undo_journal_path=tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl",
    )

    rendered = config_editor.build_redacted_config_diff(original_text, config_path.read_text(encoding="utf-8"))
    assert "subscription-token" not in rendered
    assert "PASSWORD_PLACEHOLDER" not in rendered
    assert result.message


def test_config_form_save_uses_undo_journal_and_undo_restores(tmp_path: Path) -> None:
    config_path = _write_valid_config(tmp_path)
    undo_path = tmp_path / "state_data" / "tui" / "config_undo_journal.jsonl"

    apply_config_form_patch(
        config_path,
        build_config_patch_from_field_update("probe.concurrency", 3),
        undo_journal_path=undo_path,
    )
    assert undo_path.exists()

    undo = config_editor.undo_last_config_save(config_path=config_path, undo_journal_path=undo_path)

    assert undo.restored is True
    assert "concurrency: 1" in config_path.read_text(encoding="utf-8")


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
