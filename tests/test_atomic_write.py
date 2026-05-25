"""Tests for atomic JSON writing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scholar_outbound_manager.state.atomic_write import atomic_write_json


def test_atomic_write_json_writes_content_and_creates_parent(tmp_path: Path) -> None:
    """Write JSON content into a nested path atomically."""
    target_path = tmp_path / "nested" / "manifest.json"
    payload = {"tag": "google-scholar-node-001", "passed": True}

    atomic_write_json(target_path, payload)

    assert target_path.exists()
    with target_path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    assert loaded == payload


def test_atomic_write_json_cleans_up_temp_file_on_failure(tmp_path: Path) -> None:
    """Remove temporary files when JSON serialization fails."""
    target_path = tmp_path / "nested" / "manifest.json"

    with pytest.raises(TypeError):
        atomic_write_json(target_path, {"bad": object()})

    temp_files = list((tmp_path / "nested").glob(".manifest.json.*.tmp"))
    assert temp_files == []
