"""Tests for config-centered TUI path resolution."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths


def test_resolve_user_data_paths_uses_config_relative_root(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("user_data_dir: state_data\n", encoding="utf-8")

    paths = resolve_user_data_paths(config_path)

    assert paths.root == tmp_path / "state_data"
    assert paths.candidates == tmp_path / "state_data" / "candidates.json"
    assert paths.probe_summary == tmp_path / "state_data" / "probe_summary.json"
    assert paths.action_journal == tmp_path / "state_data" / "tui" / "action_journal.jsonl"


def test_resolve_user_data_paths_honors_custom_user_data_dir(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("user_data_dir: custom_state\n", encoding="utf-8")

    paths = resolve_user_data_paths(config_path)

    assert paths.root == tmp_path / "custom_state"
    assert paths.selected_candidate == tmp_path / "custom_state" / "selected_candidate.json"
